"""Endpoint library: endpoint keys + per-client attachment (stage 5, read side).

Stage-5 pivots the check model from "one active endpoint" to an **endpoint
library** (``profiles``, semantically unchanged) plus a **per-client attachment**
relationship.  This module is the single place that resolves *which endpoints a
client is expected to mount*:

- explicit ``mcp_attach: [key, ...]`` on the client entry wins;
- absent ``mcp_attach`` defaults to **every** endpoint in the library, which
  reproduces the stage-2 ``--all-profiles`` full-matrix behaviour exactly, so a
  config that never mentions ``mcp_attach`` renders byte-for-byte as before.

Write-side CRUD (add/remove/update endpoint, set attachment) is provided by the
CLI in a later stage; this module only exposes the read + validation surface so
the check model and GUI can consume it today.
"""

from __future__ import annotations

from typing import Any, Dict, List

from profile_loader import ProfileError, list_profiles
from tool_registry import effective_tools, normalized_name


def list_endpoints(config: Dict[str, Any]) -> List[str]:
    """Return endpoint (profile) keys in display order, legacy-aware."""
    return list_profiles(config)


def resolve_client_attach(tool: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    """Endpoint keys a client is expected to mount.

    Explicit ``mcp_attach`` wins (order preserved, validated elsewhere by
    ``validate_attachment``).  Otherwise the client attaches to every endpoint in
    the library — the stage-2 full-matrix behaviour.
    """
    attach = tool.get("mcp_attach")
    if attach:
        if not isinstance(attach, list) or not all(isinstance(k, str) for k in attach):
            raise ProfileError(
                f"client {tool.get('name', '?')!r}: 'mcp_attach' must be a list of endpoint keys"
            )
        return list(attach)
    return list_profiles(config)


def has_explicit_attach(config: Dict[str, Any]) -> bool:
    """True when at least one client declares ``mcp_attach``.

    Gates the check-model switch: when nothing declares an attachment the whole
    library keeps the stage-2 full-matrix behaviour (every client checked against
    every endpoint), so existing configs render byte-for-byte unchanged.
    """
    return any(bool(tool.get("mcp_attach")) for tool in config.get("mcp_tools", []) or [])


def clients_attached_to(config: Dict[str, Any], endpoint_key: str) -> set:
    """Normalized client names expected to mount ``endpoint_key``.

    Returns ``None``-free set.  Callers that need the default "all clients"
    should branch on ``has_explicit_attach`` first.
    """
    # 遍历源 = 主干 mcp_tools（既有语义：未声明者默认挂全部端点）+ 其余来源里
    # **显式声明**了 mcp_attach 的客户端。
    #
    # 为什么要补第二段：``check_agents`` 遍历 ``effective_tools``（主干 + tools 段
    # + 自动发现，本机 22 个），而这里原先只遍历主干 ``mcp_tools``（本机 7 个）。
    # 只在自动发现清单里的客户端（本机 VS Code）因此**不进循环**，即使它在
    # ``client_mcp_attach`` / ``discovered_tools.yaml`` 里已经声明了挂载，
    # 也永远算不进集合，被过滤逻辑整条剔除 —— records 里没有它，GUI 的
    # 「MCP」列恒为 0/2，修复多少次都不变（2026-11-16 用户实测）。
    #
    # 为什么第二段只收「显式声明」的：未声明者的语义是「挂载全部端点」。
    # 若把它们也补进来，收窄就退化成「谁都保留」，与既有契约冲突；
    # 而它们在主干 mcp_tools 里时已由第一段覆盖，不存在遗漏。
    attached = set()
    for tool in config.get("mcp_tools", []) or []:
        if endpoint_key in resolve_client_attach(tool, config):
            name = tool.get("name", "")
            if name:
                attached.add(normalized_name(name))
    trunk = {normalized_name(t.get("name", "")) for t in (config.get("mcp_tools") or []) if isinstance(t, dict)}
    try:
        extra = list(effective_tools(config) or [])
    except Exception:  # noqa: BLE001 - 注册表异常时退回主干，不影响既有行为
        extra = []
    for tool in extra:
        name = tool.get("name", "")
        if not name:
            continue
        if not tool.get("mcp_attach"):
            continue            # 未声明 → 交给第一段/main-tools 语义，不在此扩展
        if normalized_name(name) in trunk:
            continue            # 主干已覆盖，避免重复
        if endpoint_key in resolve_client_attach(tool, config):
            attached.add(normalized_name(name))
    return attached


def attach_map(config: Dict[str, Any]) -> Dict[str, List[str]]:
    """Client name -> endpoint keys it is expected to mount (declared-only).

    Clients without an explicit ``mcp_attach`` are omitted from the map (their
    default is "all endpoints"); ``resolve_client_attach`` is the authoritative
    resolver.
    """
    registry = config.get("mcp_tools", []) or []
    mapping: Dict[str, List[str]] = {}
    for tool in registry:
        attach = tool.get("mcp_attach")
        if attach:
            mapping[tool.get("name", "Unknown")] = list(attach)
    return mapping


def validate_attachment(config: Dict[str, Any]) -> None:
    """Fail fast when any ``mcp_attach`` names an endpoint that does not exist.

    Raises ``ProfileError`` (exit-code-2 channel) so a typo in an attachment key
    can never silently widen/drop a client's checks.
    """
    available = set(list_profiles(config))
    for tool in config.get("mcp_tools", []) or []:
        attach = tool.get("mcp_attach")
        if not attach:
            continue
        for key in attach:
            if key not in available:
                raise ProfileError(
                    f"client {tool.get('name', '?')!r}: mcp_attach references "
                    f"unknown endpoint {key!r}; available: {sorted(available)}"
                )


def endpoint_entries(config: Dict[str, Any], *, mask_secrets: bool = False) -> List[Dict[str, Any]]:
    """Endpoint library as an ordered list of ``{key, ...profile}``.

    The ``key`` field is injected so GUI/CLI callers never rely on dict iteration
    order for the library table (stage-5 §3 端点库管理).

    ``mask_secrets=True`` 时把 ``auth_token`` 明文替换为 ``<redacted>``（见
    :func:`auth_secret.redact_profile`）。**管理台快照必须走这个开关**：快照是
    前端消费的结构，明文一旦进了 DOM（哪怕只是 ``data-*`` 属性），就等同于
    把一个长期有效的令牌暴露给了任何能读页面源码的人。
    """
    profiles = config.get("profiles")
    if profiles is None:
        # legacy unified_mcp wrapped into one profile
        from profile_loader import _wrap_legacy

        wrapped = _wrap_legacy(config)
        entries = [{"key": key, **dict(profile)} for key, profile in wrapped.items()]
    elif not isinstance(profiles, dict):
        raise ProfileError("'profiles:' must be a mapping")
    else:
        entries = [{"key": key, **dict(profile)} for key, profile in profiles.items() if profile is not None]
    if not mask_secrets:
        return entries
    from auth_secret import redact_profile

    return [redact_profile(entry) for entry in entries]
