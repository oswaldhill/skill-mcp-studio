"""MCP 端点凭据来源（引用/托管）的解析、存储与脱敏。

## 为什么需要本模块

端点库里的 ``auth_token`` 只有一个含义：**明文 token 字符串**。它会被原样抄进
每个客户端配置（``Authorization: Bearer <token>``）。用户已经把手里的 token 存进了
macOS「登录」钥匙串（服务名 ``hermes-unified-mcp`` / 账户 ``hozonauto``），希望客户端
配置别再落明文 —— 但开关端点时把 ``auth_token`` 填成 ``keychain:hermes-unified-mcp``
这样的字符串，只会得到一个真的被当作 token 发出去的无效值。

所以「认证凭据从哪来」必须是**结构化字段**，而不是拼在 token 字符串里的约定：

| ``auth_mode`` | 含义 | 明文来源 |
|---|---|---|
| ``token``（默认） | 现状：``auth_token`` 里的明文直接下发 | ``auth_token`` |
| ``env`` | 由环境变量提供 | ``auth_token_env`` 对应的 ``os.environ`` 项 |
| ``keychain`` | 由系统钥匙串（macOS Keychain / Linux Secret Service）提供 | ``security`` / ``secret-tool`` |
| ``file`` | 由本机凭据文件提供（CI / 无钥匙串环境兜底） | ``auth_file`` 路径内容 |

``token`` 模式刻意保持**逐字节不变**，既有用户的配置与测试都不受影响。

## 安全取舍

* 明文只在本进程内流转：探活（:mod:`mcp_probe`）与客户端配置渲染
  （:mod:`mcp_fixer_render`）都需要真实 token，但它们不回显、不落盘进端点库。
* 对外输出一律走 :func:`mask_token`（前 4 后 4）或 :func:`redact_profile`（整段替换），
  ``--auth-secret-status`` / 管理台只显示「来源 + 脱敏值 + 是否取得到」。
* 客户端配置里引用路径只携带**变量名 / 服务名 / 文件路径**，绝不携带明文。

## 失败语义

「取不到 token」不是异常，而是可诊断的状态：:func:`resolve_auth` 返回
``ok=False`` 并附 ``error``（例如钥匙串条目不存在、``security`` 被拒，
或 macOS 上 GUI 进程首次访问钥匙串弹窗超时）。调用方据此把探活判为
「凭据不可用」，而不是笼统的 401。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional

#: 端点 ``auth_mode`` 的合法取值。``token`` 是历史默认值（明文落进客户端配置）。
AUTH_MODES = ("token", "env", "keychain", "file")

#: 未声明 ``auth_token_env`` 时的历史回落名（与 mcp_probe 旧行为一致）。
DEFAULT_ENV_VAR = "HERMES_MCP_AUTH_TOKEN"

#: 钥匙串调用的超时（秒）。macOS 首次访问会让用户点「允许」，但 GUI 子进程若在
#: 无人值守时被弹窗阻塞，整条审计链会挂住；给一个保守上限并报成可读错误。
_KEYCHAIN_TIMEOUT = 10.0

#: 脱敏占位符（与 config_porter.REDACTED 同值，便于导出包互相识别）。
REDACTED = "<redacted>"

#: ``security`` 在「条目存在但访问被拒」时的退出码（实测值）。
_KEYCHAIN_DENIED_RC = 161


def normalize_auth_mode(profile: Dict[str, Any]) -> str:
    """Return the profile's effective ``auth_mode`` (defaults to ``token``).

    未知取值按 ``token`` 处理并**不抛错**：``auth_mode`` 是新增字段，老配置里
    可能有人手写成其它值；把它当作明文字段读取至少行为可预期，而加载期抛错
    会让整份配置不可用。
    """
    raw = profile.get("auth_mode")
    if isinstance(raw, str) and raw.strip().lower() in AUTH_MODES:
        return raw.strip().lower()
    return "token"


def mask_token(token: str) -> str:
    """Mask a secret for display: ``abcd…wxyz`` (or ``****`` when short)."""
    token = (token or "").strip()
    if not token:
        return ""
    if len(token) <= 8:
        return "****"
    return token[:4] + "…" + token[-4:]


def redact_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-copied profile with明文 ``auth_token`` replaced by ``<redacted>``.

    供端点库列表 / 管理台快照使用：``auth_mode`` 不是 ``token`` 时 ``auth_token``
    本就应该为空，但历史数据可能两者并存（用户切换了模式但旧 token 没清），
    因此**不按 mode 判断**，只要非空就脱敏。
    """
    out = dict(profile)
    if out.get("auth_token"):
        out["auth_token"] = REDACTED
    return out


def auth_configured(profile: Dict[str, Any]) -> bool:
    """Whether the profile declares *some* credential (without fetching it)."""
    mode = normalize_auth_mode(profile)
    if mode == "env":
        return bool(str(profile.get("auth_token_env") or "").strip())
    if mode == "keychain":
        return bool(str(profile.get("auth_keychain") or "").strip())
    if mode == "file":
        return bool(str(profile.get("auth_file") or "").strip())
    return bool(profile.get("auth_token"))


# ── 凭据读取 ────────────────────────────────────────────────────────────


def _read_secret_file(path: str) -> str:
    with open(os.path.expanduser(path), "r", encoding="utf-8") as handle:
        return handle.read().strip()


def _macos_keychain_read(service: str, account: str) -> str:
    """Read a generic password from the macOS login keychain via ``security``.

    ``security find-generic-password -w`` 会先查访问控制：条目是由用户（或其它
    进程）写入时，当前进程首次读取通常会给出一条系统授权对话框。失败时抛
    ``RuntimeError`` —— 调用方据此把端点判为「凭据不可用」而非 401。
    """
    account = account or os.environ.get("USER", "")
    command = ["security", "find-generic-password", "-s", service, "-w"]
    if account:
        command.extend(["-a", account])
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        # 2026-11-04 实测：无人值守时 `security` 会在授权对话框上一直等，
        # 超时后既不返回内容也不给错误 —— 只说「读取失败」没用，必须告诉用户
        # 「发生了什么、在哪点、还能怎么办」。
        raise RuntimeError(
            f"钥匙串条目 {service!r} 读取超时（{_KEYCHAIN_TIMEOUT:.0f}s）："
            "通常是授权对话框未响应。请在系统弹窗点「总是允许」，"
            "或先手动执行 security find-generic-password -s "
            f"{service} -w 完成一次授权"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"钥匙串读取失败：{exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else f"security 退出码 {completed.returncode}"
        if completed.returncode == _KEYCHAIN_DENIED_RC:
            reason = (
                "系统拒绝访问该条目（exit 161）。请在弹窗点「总是允许」；"
                "若没有弹窗，用「钥匙串访问」App 打开该条目 → 访问控制 → 允许，"
                "或改用 --endpoint-auth-mode file"
            )
        raise RuntimeError(f"钥匙串条目 {service!r} 不可读：{reason}")
    token = (completed.stdout or "").strip()
    if not token:
        raise RuntimeError(f"钥匙串条目 {service!r} 内容为空")
    return token


def _linux_keychain_read(service: str, account: str) -> str:
    """Read a secret from the Linux Secret Service via ``secret-tool``."""
    tool = shutil.which("secret-tool")
    if not tool:
        raise RuntimeError("未找到 secret-tool（libsecret），无法读取钥匙串")
    command = [tool, "lookup", "service", service]
    if account:
        command.extend(["account", account])
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"钥匙串读取失败：{exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"钥匙串条目 {service!r} 不可读（secret-tool 退出码 {completed.returncode}）")
    token = (completed.stdout or "").strip()
    if not token:
        raise RuntimeError(f"钥匙串条目 {service!r} 内容为空")
    return token


def keychain_supported() -> bool:
    """Whether this OS exposes a keychain CLI we can drive."""
    if sys.platform == "darwin":
        return shutil.which("security") is not None
    return shutil.which("secret-tool") is not None


def keychain_read(service: str, account: str = "") -> str:
    """Read one keychain secret by service name (raises ``RuntimeError``)."""
    if not service:
        raise RuntimeError("未指定钥匙串服务名")
    if sys.platform == "darwin":
        return _macos_keychain_read(service, account)
    if shutil.which("secret-tool"):
        return _linux_keychain_read(service, account)
    raise RuntimeError("当前平台不支持钥匙串读取（仅 macOS / Linux Secret Service）")


def keychain_write(service: str, secret: str, account: str = "") -> None:
    """Store one keychain secret (``security add-generic-password -U``)."""
    if not service:
        raise ValueError("未指定钥匙串服务名")
    secret = (secret or "").strip()
    if not secret:
        raise ValueError("密钥不能为空")
    if sys.platform == "darwin":
        account = account or os.environ.get("USER", "")
        command = [
            "security", "add-generic-password",
            "-U", "-s", service, "-w", secret, "-a", account,
        ]
        try:
            written = subprocess.run(
                command, capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"钥匙串写入超时（{_KEYCHAIN_TIMEOUT:.0f}s）：授权对话框可能未响应") from exc
        except OSError as exc:
            raise RuntimeError(f"钥匙串写入失败：{exc}") from exc
        if written.returncode != 0:
            detail = (written.stderr or "").strip().splitlines()
            reason = detail[-1] if detail else f"security 退出码 {written.returncode}"
            hint = ""
            if "Operation not permitted" in reason:
                # 2026-11-04 实测：父进程被沙箱限制时，`security` 连新建条目都会被拒。
                hint = ("（当前进程没有钥匙串写权限：可能是沙箱/权限限制，"
                        "在终端里手动执行同一条命令即可，或改用 --endpoint-auth-mode file）")
            raise RuntimeError(f"钥匙串写入失败：{reason}{hint}")
        # 写后立即回读：`security add-generic-password -U` 在某些钥匙串状态下
        # 静默不更新，只有回读才能确认「真的存进去了」。
        keychain_read(service, account)
        return
    tool = shutil.which("secret-tool")
    if not tool:
        raise RuntimeError("当前平台不支持钥匙串写入（仅 macOS / Linux Secret Service）")
    account = account or os.environ.get("USER", "")
    try:
        completed = subprocess.run(
            [tool, "store", f"--label={service}", "service", service, "account", account],
            input=secret, capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"钥匙串写入失败：{exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"钥匙串写入失败（secret-tool 退出码 {completed.returncode}）")


def keychain_delete(service: str, account: str = "") -> None:
    """Delete one keychain secret; a missing entry is not an error."""
    if not service:
        return
    if sys.platform == "darwin":
        account = account or os.environ.get("USER", "")
        command = ["security", "delete-generic-password", "-s", service]
        if account:
            command.extend(["-a", account])
        subprocess.run(command, capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT)
        return
    tool = shutil.which("secret-tool")
    if tool:
        subprocess.run(
            [tool, "clear", "service", service], capture_output=True, text=True,
            timeout=_KEYCHAIN_TIMEOUT,
        )


def keychain_entry_exists(service: str, account: str = "") -> bool:
    """Whether the keychain entry exists — **without** reading its secret.

    macOS 用 ``find-generic-password`` 不带 ``-w``：只返回元数据、不触发内容
    授权，因此可以在每次渲染管理台时安全调用（带 ``-w`` 的读取会弹窗，见
    :func:`keychain_read`）。
    """
    if not service:
        return False
    if sys.platform == "darwin":
        command = ["security", "find-generic-password", "-s", service]
        if account or os.environ.get("USER"):
            command.extend(["-a", account or os.environ.get("USER", "")])
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0
    tool = shutil.which("secret-tool")
    if not tool:
        return False
    command = [tool, "lookup", "service", service]
    if account:
        command.extend(["account", account])
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def resolve_auth_fields(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a profile's credential into renderer/transport fields.

    返回 ``{mode, token, env_var, keychain_service, file_path, evaluated_token}``：

    * ``mode=token``：``token`` 是明文（历史行为，逐字节不变）；
    * ``mode=env``：只给 ``env_var``（变量名），``token`` 为空；
    * ``mode=keychain`` / ``file``：只给 ``keychain_service`` / ``file_path``，
      ``token`` 为空 —— **引用型从不在本函数里读明文**，读明文是探活的事
      （见 :func:`resolve_auth`），渲染配置只需要知道「引用怎么写」。

    这个划分是刻意的：``--fix-mcp`` 不应因为钥匙串授权弹窗未点而失败。
    """
    mode = normalize_auth_mode(profile)
    return {
        "mode": mode,
        "token": str(profile.get("auth_token") or "") if mode == "token" else "",
        "env_var": str(profile.get("auth_token_env") or "") if mode == "env" else "",
        "keychain_service": str(profile.get("auth_keychain") or "") if mode == "keychain" else "",
        "file_path": str(profile.get("auth_file") or "") if mode == "file" else "",
        # 引用型在客户端配置里使用的**合法**变量名。由调用方按端点 key 派生并传入
        # （见 mcp_fixer.fix_mcp_tool），保证同一端点在所有客户端里用同一个名字，
        # 用户注入一次即可；缺省为空表示「没有可用的合法变量名」。
        "template_var": str(profile.get("auth_env_name") or ""),
        "evaluated_token": "",
    }


def resolve_auth(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the profile's credential into ``{ok, mode, source, token, error}``.

    ``source`` 是**可展示的来源描述**（变量名 / 钥匙串服务名 / 文件路径），
    绝不含明文。``ok=False`` 时 ``error`` 给出可直接展示的失败原因。
    """
    mode = normalize_auth_mode(profile)
    if mode == "env":
        name = str(profile.get("auth_token_env") or DEFAULT_ENV_VAR)
        token = os.environ.get(name, "")
        return {
            "ok": bool(token),
            "mode": mode,
            "source": name,
            "token": token,
            "error": "" if token else f"环境变量 {name} 未设置或为空",
        }
    if mode == "keychain":
        service = str(profile.get("auth_keychain") or "")
        account = str(profile.get("auth_keychain_account") or "")
        try:
            token = keychain_read(service, account)
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "mode": mode, "source": service, "token": "", "error": str(exc)}
        return {"ok": bool(token), "mode": mode, "source": service, "token": token, "error": ""}
    if mode == "file":
        path = str(profile.get("auth_file") or "")
        if not path:
            return {"ok": False, "mode": mode, "source": "", "token": "", "error": "未指定凭据文件路径"}
        try:
            token = _read_secret_file(path)
        except OSError as exc:
            return {"ok": False, "mode": mode, "source": path, "token": "", "error": f"凭据文件不可读：{exc.strerror or exc}"}
        return {
            "ok": bool(token),
            "mode": mode,
            "source": path,
            "token": token,
            "error": "" if token else f"凭据文件 {path} 为空",
        }
    token = str(profile.get("auth_token") or "")
    return {
        "ok": bool(token),
        "mode": mode,
        "source": "auth_token（明文）" if token else "",
        "token": token,
        "error": "" if token else "",
    }


def resolve_for_fix(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the credential specifically for **writing client configs**.

    与 :func:`resolve_auth` 的差别：客户端配置只需要知道「引用怎么写」，
    因此 ``env`` / ``keychain`` / ``file`` 三种引用模式**不需要读到明文**
    （配置里写的是变量名 / 服务名 / 路径）。只有 ``token`` 模式才需要明文。
    这样 --fix-mcp 在钥匙串尚未授权时也不会失败。
    """
    mode = normalize_auth_mode(profile)
    if mode == "token":
        return resolve_auth(profile)
    return {
        "ok": auth_configured(profile),
        "mode": mode,
        "source": str(
            profile.get("auth_token_env")
            or profile.get("auth_keychain")
            or profile.get("auth_file")
            or ""
        ),
        "token": str(profile.get("auth_token") or ""),
        "error": "" if auth_configured(profile) else f"auth_mode={mode} 但未声明对应的来源字段",
    }


def injection_hint(auth_mode: str, var_name: str) -> str:
    """给出「把真值注入客户端环境」的可复制命令 / 说明。

    客户端配置里的 ``${env:VAR}``（以及 Codex 的 ``bearer_token_env_var``）都由
    客户端**自己的进程环境**求值。钥匙串 / 文件模式没有原生求值语法，所以真值
    必须出现在客户端的环境里；支持根 env 块的客户端由 ``--fix-mcp`` 自动写入，
    其余客户端需要用户在自己的 shell profile 里 export 一次。
    """
    if not var_name:
        return ""
    if auth_mode == "keychain":
        return f"export {var_name}=$(security find-generic-password -s <钥匙串服务名> -w)"
    if auth_mode == "file":
        return f"export {var_name}=$(cat <凭据文件路径>)"
    return f"export {var_name}=<token>"


def describe_auth(profile: Dict[str, Any], *, check: bool = False) -> Dict[str, Any]:
    """Status payload for ``--auth-secret-status`` / GUI status cards.

    ``check=False``（默认）**不读取**凭据，只用不触发授权的方式判断「存不存在」
    （``security find-generic-password`` 不带 ``-w`` 只返回元数据）。

    为什么默认不读：钥匙串内容读取会弹出系统授权对话框，而 GUI 子进程 / 后台
    巡检 / CI 里没人点「允许」——实测 ``security ... -w`` 在这种环境下挂到超时
    （10s）才失败，把一次「报告状态」变成一次 10 秒卡顿 + 一条误导性的失败。
    ``check=True`` 只给「用户显式点『读取并验证』」这类交互路径用。

    无论哪种模式，返回体都**永远不会包含完整明文**（只有 :func:`mask_token`）。
    """
    mode = normalize_auth_mode(profile)
    configured = auth_configured(profile)
    source = str(
        profile.get("auth_token_env")
        or profile.get("auth_keychain")
        or profile.get("auth_file")
        or ""
    )
    check_error = ""
    if check:
        resolved = resolve_auth(profile)
        source = resolved.get("source") or source
        check_error = resolved.get("error") or ""
        available = resolved.get("ok")
    else:
        available = _available_without_reading(profile, mode, configured)
    return {
        "mode": mode,
        "configured": configured,
        "source": source,
        "available": available,
        "masked": "",
        "error": check_error,
        "checked": check,
    }


def _available_without_reading(
    profile: Dict[str, Any], mode: str, configured: bool
) -> Optional[bool]:
    """Best-effort availability that never triggers an authorization prompt.

    * ``env`` → 当前进程 ``os.environ`` 里有没有这个变量（与探活同一条读取路径）
    * ``keychain`` → 条目是否存在（``security`` 不带 ``-w``，只返回元数据）
    * ``file`` → 文件是否存在且非空（读文件不弹窗）
    * ``token`` → ``auth_token`` 是否非空（这是配置里本来就有的值）

    返回 ``None`` 表示「没声明来源」，UI 据此显示「未配置」而非「不可用」。
    """
    if not configured:
        return None if mode == "token" else False
    if mode == "env":
        name = str(profile.get("auth_token_env") or DEFAULT_ENV_VAR)
        return bool(os.environ.get(name))
    if mode == "keychain":
        return keychain_entry_exists(
            str(profile.get("auth_keychain") or ""),
            str(profile.get("auth_keychain_account") or ""),
        )
    if mode == "file":
        path = str(profile.get("auth_file") or "")
        try:
            return bool(_read_secret_file(path))
        except OSError:
            return False
    return True


def scrub_env(token: str) -> Optional[str]:
    """Return the env var name that currently holds ``token``, if any.

    GUI 由 launchd 启动时读不到 shell 环境，用户可能把 ``HERMES_MCP_AUTH_TOKEN``
    导出在 ``~/.zshrc`` 里、以为已经生效；工具则只能看到「没有 token」。这里
    用于把「看起来没配置」与「配置了但本进程读不到」区分开。
    """
    if not token:
        return None
    for name, value in os.environ.items():
        if value and value == token:
            return name
    return None
