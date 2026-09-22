"""Bounded Streamable HTTP probe for a remote MCP endpoint."""

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from mcp_checker import is_valid_mcp_url


def _ssl_context() -> ssl.SSLContext:
    """Build a verifying TLS context with a usable CA trust store.

    macOS python.org framework builds ship without a linked system CA store, so
    ``ssl.create_default_context()`` alone cannot verify real HTTPS endpoints
    (``CERTIFICATE_VERIFY_FAILED``). ``certifi`` is a declared dependency (see
    ``pyproject.toml``); we load its bundle explicitly. Verification is always
    enforced — a security audit tool must never downgrade to ``CERT_NONE``.
    """
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:  # pragma: no cover - declared dependency, defensive only
        import warnings

        warnings.warn("certifi 未安装，TLS 校验将依赖系统默认 CA（macOS python.org 构建可能失败）")
        return context
    context.load_verify_locations(certifi.where())
    return context


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
    auth_env = token_env or "HERMES_MCP_AUTH_TOKEN"
    auth_token = token if token is not None else os.environ.get(auth_env, "")
    # 探活是「尽力而为」的可用性观测：远程 MCP 网关偶发抖动（单次 socket 超时）
    # 并不等于端点故障。这里对 initialize 与 tools/list 两个阶段的瞬时网络错误
    # 均重试 ``retries`` 次；一旦拿到业务响应（result 或 error）就停止重试，因此
    # 成功路径与不重试时行为完全一致（error 仍为 ""），审计结论 result_ok 不受
    # 影响，只是少报一次「假故障」。
    transient = (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError)
    attempts = max(1, int(retries) + 1)
    initialize: Dict[str, Any] = {}
    session_id = ""
    for attempt in range(attempts):
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
            }, token=auth_token, timeout=timeout)
            break
        except transient as error:
            if attempt + 1 >= attempts:
                result["error"] = str(error)
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
