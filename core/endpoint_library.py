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
from tool_registry import normalized_name


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
    attached = set()
    for tool in config.get("mcp_tools", []) or []:
        if endpoint_key in resolve_client_attach(tool, config):
            name = tool.get("name", "")
            if name:
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


def endpoint_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Endpoint library as an ordered list of ``{key, ...profile}``.

    The ``key`` field is injected so GUI/CLI callers never rely on dict iteration
    order for the library table (stage-5 §3 端点库管理).
    """
    profiles = config.get("profiles")
    if profiles is None:
        # legacy unified_mcp wrapped into one profile
        from profile_loader import _wrap_legacy

        wrapped = _wrap_legacy(config)
        return [{"key": key, **dict(profile)} for key, profile in wrapped.items()]
    if not isinstance(profiles, dict):
        raise ProfileError("'profiles:' must be a mapping")
    return [{"key": key, **dict(profile)} for key, profile in profiles.items() if profile is not None]
