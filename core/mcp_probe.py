"""Bounded Streamable HTTP probe for a remote MCP endpoint."""

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from mcp_checker import is_valid_mcp_url


#: 系统 CA 包候选路径，按「该平台 Python 的默认上下文是否真的空」逐条兜底。
#: 实测（2026-11-04）：macOS 的 python.org framework 构建
#: ``ssl.create_default_context()`` 加载到的根证书数 **为 0**，
#: 于是所有 HTTPS 探活都以 ``CERTIFICATE_VERIFY_FAILED`` 失败 —— 而依赖
#: ``certifi`` 的写法只有在「用户恰好装了 certifi」时才对。
#: 本机实测三个解释器（/usr/local/bin/python3、framework 3.13、/usr/bin/python3）
#: 全部没有 certifi，等于所有端点都被判成「连不上」。
SYSTEM_CA_BUNDLES = (
    "/etc/ssl/cert.pem",                                  # macOS（libressl 软链到系统钥匙串导出的根）
    "/etc/ssl/certs/ca-certificates.crt",                  # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",                    # RHEL/Fedora
    "/etc/ssl/ca-bundle.pem",                              # openSUSE
    "/etc/ssl/cert.pem",                                   # Alpine/FreeBSD
)


def _ssl_context() -> ssl.SSLContext:
    """Build a verifying TLS context with a usable CA trust store.

    macOS python.org framework builds ship without a linked system CA store, so
    ``ssl.create_default_context()`` alone cannot verify real HTTPS endpoints
    (``CERTIFICATE_VERIFY_FAILED``).

    取信任库的优先级（每一步都只在「前一步没拿到根证书」时才走）：

    1. ``certifi``（若已安装）—— 跨平台最一致，也是 ``pyproject.toml`` 的声明依赖；
    2. 系统 CA 包（见 :data:`SYSTEM_CA_BUNDLES`）—— certifi 缺失时的兜底。
       它是本次修复的重点：此前 certifi 缺失就**直接返回空上下文**，任何
       半吊子安装（装好了工具、没装依赖）都会让全部端点显示「连接失败」。

    **校验强度不降级**：两条路径都是 ``load_verify_locations``，绝不落到
    ``CERT_NONE`` / ``check_hostname=False`` —— 审计工具不能为了「看起来能连」
    而放弃证书校验。若一条信任库都找不到，抛 ``RuntimeError`` 说明原因，
    而不是静默构造一个必然失败的上下文。
    """
    context = ssl.create_default_context()
    if context.get_ca_certs():
        return context  # 平台本身就带根证书（Linux 常见），无需额外加载

    try:
        import certifi
    except ImportError:
        certifi = None  # noqa: F841 - 下面按「有没有拿到根证书」判断，不按异常类型
    else:
        context.load_verify_locations(certifi.where())
        if context.get_ca_certs():
            return context

    for bundle in SYSTEM_CA_BUNDLES:
        if not os.path.isfile(bundle):
            continue
        try:
            context.load_verify_locations(bundle)
        except (OSError, ssl.SSLError):
            continue
        if context.get_ca_certs():
            return context

    raise RuntimeError(
        "找不到可用的 CA 信任库：certifi 未安装，且系统 CA 包（"
        + " / ".join(SYSTEM_CA_BUNDLES)
        + "）均不可用。请安装 certifi（pip install certifi）或在系统装上 CA 证书；"
        "本工具不会为「能连上」而关闭证书校验。"
    )


def _decode_response(body: str) -> Dict[str, Any]:
    body = body.strip()
    if not body:
        return {}
    if body.startswith("{"):
        return json.loads(body)
    for line in body.splitlines():
        if line.startswith("data:"):
            candidate = line[5:].strip()
            if candidate and candidate != "[DONE]":
                return json.loads(candidate)
    return {}


def _post(
    url: str,
    payload: Dict[str, Any],
    *,
    session_id: str = "",
    token: str = "",
    timeout: float = 8.0,
) -> Tuple[Dict[str, Any], str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return _decode_response(response.read().decode("utf-8")), response.headers.get("Mcp-Session-Id", session_id)


def _is_probeable_url(url: str, url_policy: str) -> bool:
    """Apply a profile-level URL policy to decide whether probing is allowed.

    ``strict`` keeps the production baseline (HTTPS + hostname + ``/mcp``);
    ``relaxed`` permits local/non-standard endpoints (http or arbitrary path).
    """
    if url_policy == "relaxed":
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("https", "http") and bool(parsed.hostname)
        except (TypeError, ValueError):
            return False
    return is_valid_mcp_url(url)


def token_needs_resolution(profile: Dict[str, Any]) -> bool:
    """Whether the profile's credential must be resolved by us before probing.

    引用型（``env`` / ``keychain`` / ``file``）都需要：客户端在配置里拿到的是
    占位符，探活必须自己按引用取出真值，结论才与客户端一致。
    """
    from auth_secret import normalize_auth_mode

    return normalize_auth_mode(profile) in ("env", "keychain", "file")


def probe_mcp(
    url: str,
    *,
    transport: str = "streamable-http",
    command: Optional[str] = None,
    args: Optional[list] = None,
    env: Optional[Dict[str, Any]] = None,
    timeout: float = 8.0,
    token: Optional[str] = None,
    token_env: Optional[str] = None,
    url_policy: str = "strict",
    retries: int = 0,
    auth_keychain: Optional[str] = None,
    auth_file: Optional[str] = None,
) -> Dict[str, Any]:
    # 阶段二 §4.2：transport 白名单。非法值在加载期由 profile_loader 拒绝
    # （退出码 2）；此处为防御性兜底，绝不静默落入 HTTP 分支。
    if transport not in ("streamable-http", "stdio"):
        return {
            "initialize_ok": False,
            "tools_list_ok": False,
            "tool_names": [],
            "error": (
                f"unsupported transport {transport!r}; "
                "expected 'streamable-http' or 'stdio'"
            ),
        }
    # stdio transport (phase 2): same ProbeResult, different transport.
    # 评审 CLI-5b：经由 transport.py 的统一分派（ProbeSpec → Transport 注册表），
    # 不再直连 probe_stdio；HTTP 分支保持原位（零重写）。
    if transport == "stdio":
        from transport import ProbeSpec, dispatch_probe

        if not command:
            return {
                "initialize_ok": False,
                "tools_list_ok": False,
                "tool_names": [],
                "error": "stdio transport requires a 'command' (argv list)",
            }
        return dispatch_probe(
            ProbeSpec(
                transport="stdio",
                command=command,
                args=tuple(args or ()),
                env=dict(env or {}),
            ),
            timeout=timeout,
        )

    result = {
        "initialize_ok": False,
        "tools_list_ok": False,
        "tool_names": [],
        "error": "",
    }
    if not _is_probeable_url(url, url_policy):
        result["error"] = "MCP URL must use HTTPS and end in /mcp"
        return result
    # 凭据来源优先级：显式 keychain / file 引用 → 显式 token → 环境变量。
    #
    # 为什么把引用型放在最前面：端点声明 ``auth_mode=keychain`` / ``file`` 时，
    # 客户端配置里写的是引用而不是明文，探活**必须按引用取到真值**，否则探活
    # 与客户端的行为就不一致（探活 401、客户端能用，或反之）。
    #
    # 取不到（钥匙串条目不存在、``security`` 被拒、文件不可读）时**不静默回落**
    # 到环境变量：回落会把「凭据来源配置错了」伪装成「端点故障」，用户会去查
    # 网络。这里直接把原因写进 error，GUI/CLI 原样展示。
    if auth_keychain or auth_file:
        from auth_secret import resolve_auth

        source = {"auth_mode": "keychain" if auth_keychain else "file"}
        if auth_keychain:
            source["auth_keychain"] = auth_keychain
        else:
            source["auth_file"] = auth_file
        resolved = resolve_auth(source)
        if not resolved["ok"]:
            result["error"] = f"凭据不可用：{resolved['error']}"
            return result
        auth_token = resolved["token"]
    else:
        auth_env = token_env or "HERMES_MCP_AUTH_TOKEN"
        auth_token = token if token is not None else os.environ.get(auth_env, "")
    # 探活是「尽力而为」的可用性观测：远程 MCP 网关偶发抖动（单次 socket 超时）
    # 并不等于端点故障。这里对 initialize 与 tools/list 两个阶段的瞬时网络错误
    # 均重试 ``retries`` 次；一旦拿到业务响应（result 或 error）就停止重试，因此
    # 成功路径与不重试时行为完全一致（error 仍为 ""），审计结论 result_ok 不受
    # 影响，只是少报一次「假故障」。
    transient = (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError)
    attempts = max(1, int(retries) + 1)
    # Round 39：整个 initialize 阶段**共享一个 deadline**，重试只消耗剩余预算。
    #
    # 动机（实测）：`retries=1` 原本让每次尝试各自吃满 `timeout`，于是
    #   retries=0 → 10.14s / retries=1 → 16.21s（同一个 'read operation timed out'）
    # —— 对「端点根本不可达」这种确定性超时，第二次尝试注定同样超时，
    # 多花的 6s 是纯等待。而审计要逐端点跑，这个浪费会被放大。
    #
    # 注意这里**不改变重试语义**：瞬时抖动（作者原意要吸收的「单次 socket 超时」）
    # 仍然会重试，只是重试必须在原定预算内完成。这正是 `transport.py` 对 stdio
    # 两次握手已经采用的做法（其注释：single deadline budget covering spawn +
    # both handshakes, previously each handshake got its own timeout → up to 2×）。
    phase_deadline = time.monotonic() + timeout
    last_error = ""
    initialize: Dict[str, Any] = {}
    session_id = ""
    for attempt in range(attempts):
        remaining = phase_deadline - time.monotonic()
        if remaining <= 0:  # 预算已耗尽：不再发起注定超时的尝试
            result["error"] = last_error or "probe budget exhausted before initialize"
            return result
        try:
            initialize, session_id = _post(url, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "skill-mcp-studio", "version": "1.0"},
                },
            }, token=auth_token, timeout=remaining)
            break
        except transient as error:
            last_error = str(error)
            if attempt + 1 >= attempts:
                result["error"] = last_error
                return result
    try:
        if initialize.get("error") or not initialize.get("result"):
            result["error"] = str(initialize.get("error") or "initialize returned no result")
            return result
        result["initialize_ok"] = True
        try:
            _post(url, {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }, session_id=session_id, token=auth_token, timeout=timeout)
        except (urllib.error.HTTPError, ValueError):
            pass
        listed: Dict[str, Any] = {}
        for attempt in range(attempts):
            try:
                listed, _ = _post(url, {
                    "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
                }, session_id=session_id, token=auth_token, timeout=timeout)
                break
            except transient as error:
                # 与 initialize 阶段对称：tools/list 的瞬时网络错误同样重试，
                # 拿到业务响应（result 或 error 结构）即停。成功路径 error 仍为 ""，
                # 审计结论 result_ok 不受影响，只是少报一次「假故障」。
                if attempt + 1 >= attempts:
                    result["error"] = str(error)
                    return result
        tools = listed.get("result", {}).get("tools", [])
        result["tool_names"] = sorted(
            tool.get("name", "") for tool in tools if isinstance(tool, dict) and tool.get("name")
        )
        result["tools_list_ok"] = bool(tools)
        if not tools:
            result["error"] = str(listed.get("error") or "tools/list returned no tools")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as error:
        result["error"] = str(error)
    return result
