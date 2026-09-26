"""Endpoint-library write store (stage-5 P3): CRUD over ``profile_sources``.

The trunk ``config.yaml`` stays free of personal topology, so endpoint-library
mutations (add/remove/update endpoint, set per-client attachment) are persisted
to the first *existing* ``profile_sources`` overlay file — i.e. the same local
file that already carries the real endpoint.  If no source file exists yet, a
missing one under the primary source path may be created; otherwise the first
``profile_sources`` entry is used as the write target.

Every write reuses the mcp_fixer safety shape: read-original -> render validated
YAML -> atomic replace -> re-parse validation -> rollback on failure.  All CRUD
functions accept ``dry_run`` and return a ``{status, message, path, backup}``
dict (never raise on user data; only on programmer misuse).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import yaml

from mcp_fixer import _atomic_write, _backup_path


def _source_paths(config: Dict[str, Any]) -> List[str]:
    sources = config.get("profile_sources") or []
    return [os.path.expanduser(p) for p in sources if isinstance(p, str) and p.strip()]


def _write_target(config: Dict[str, Any], allow_create: bool = True) -> str:
    """Choose the overlay file endpoint mutations are written to.

    Prefers the first existing source file (it already carries personal topology);
    falls back to the first source path (creating the parent dir if allowed), or
    an empty string when no ``profile_sources`` are configured at all.
    """
    for path in _source_paths(config):
        if os.path.isfile(path):
            return path
    if allow_create and _source_paths(config):
        return _source_paths(config)[0]
    return ""


def _load_target(path: str) -> Dict[str, Any]:
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        return data if isinstance(data, dict) else {}
    return {}


def _dump(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _persist(path: str, data: Dict[str, Any], dry_run: bool) -> Dict[str, str]:
    """Atomically write ``data`` to ``path`` (unless dry-run), with rollback."""
    rendered = _dump(data)
    if dry_run:
        return {"status": "dry-run", "message": rendered, "path": path, "backup": ""}

    # Profile overlay may carry auth_token; always tighten to owner-only (0600)
    # regardless of pre-existing mode, so a previously world-readable overlay
    # (legacy 0644 default) is repaired on the next write.  ADR-19/D-3.
    mode = 0o600
    backup = _backup_path(path) if os.path.isfile(path) else ""
    try:
        if backup:
            import shutil

            shutil.copy2(path, backup)
        _atomic_write(path, rendered, mode)
    except OSError as exc:
        return {"status": "error", "message": f"write failed: {exc}", "path": path, "backup": backup}
    # re-parse validation: a malformed result is rolled back atomically.
    try:
        reloaded = _load_target(path)
    except yaml.YAMLError as exc:
        try:
            if backup and os.path.isfile(backup):
                _atomic_write(path, open(backup, "r", encoding="utf-8").read(), mode)
        except OSError:
            pass
        return {"status": "error", "message": f"re-parse failed: {exc}", "path": path, "backup": backup}
    if reloaded is None:
        reloaded = {}
    # deep structural sanity: profiles mapping must survive
    if "profiles" in data and not isinstance(data.get("profiles"), dict):
        return {"status": "error", "message": "profiles must be a mapping", "path": path, "backup": backup}
    return {"status": "ok", "message": "written", "path": path, "backup": backup}


def _ensure_profiles(data: Dict[str, Any]) -> Dict[str, Any]:
    if "profiles" not in data or not isinstance(data.get("profiles"), dict):
        data["profiles"] = {}
    return data


def add_endpoint(
    config: Dict[str, Any],
    key: str,
    profile: Dict[str, Any],
    *,
    dry_run: bool = False,
    active: bool = False,
    auth_token: Optional[str] = None,
) -> Dict[str, str]:
    """Add (or overwrite) one endpoint in the store. Set it active when ``active``."""
    path = _write_target(config)
    if not _source_paths(config):
        return {"status": "error", "message": "no profile_sources configured; add one first", "path": "", "backup": ""}
    data = _ensure_profiles(_load_target(path))
    data["profiles"][key] = dict(profile)
    if auth_token is not None:
        data["profiles"][key]["auth_token"] = auth_token
    if active:
        data["active_profile"] = key
    return _persist(path, data, dry_run)


def remove_endpoint(config: Dict[str, Any], key: str, *, dry_run: bool = False) -> Dict[str, str]:
    path = _write_target(config)
    if not _source_paths(config):
        return {"status": "error", "message": "no profile_sources configured", "path": "", "backup": ""}
    data = _load_target(path)
    profiles = data.get("profiles")
    # ① 本地文件里已有该 key → 直接删除。
    if isinstance(profiles, dict) and key in profiles:
        profiles.pop(key)
        if data.get("active_profile") == key:
            data["active_profile"] = ""
        return _persist(path, data, dry_run)
    # ② 主干 config.yaml 里有该 key 但本地文件无 → 软删除：写入 null 覆盖主干。
    trunk_profiles = config.get("profiles") or {}
    if isinstance(trunk_profiles, dict) and key in trunk_profiles:
        if not isinstance(profiles, dict):
            profiles = {}
            data["profiles"] = profiles
        profiles[key] = None
        if data.get("active_profile") == key:
            data["active_profile"] = ""
        return _persist(path, data, dry_run)
    return {"status": "unchanged", "message": f"endpoint {key!r} not present", "path": path, "backup": ""}


def update_endpoint(
    config: Dict[str, Any],
    key: str,
    *,
    url: Optional[str] = None,
    name: Optional[str] = None,
    auth_token: Optional[str] = None,
    command: Optional[str] = None,
    transport: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, str]:
    path = _write_target(config)
    if not _source_paths(config):
        return {"status": "error", "message": "no profile_sources configured", "path": "", "backup": ""}
    data = _load_target(path)
    profiles = data.get("profiles")
    # ① 本地文件已有 → 直接更新。
    if isinstance(profiles, dict) and key in profiles:
        if url is not None:
            profiles[key]["url"] = url
        if name is not None:
            profiles[key]["name"] = name
        if auth_token is not None:
            profiles[key]["auth_token"] = auth_token
        if command is not None:
            profiles[key]["command"] = command
        if transport is not None:
            profiles[key]["transport"] = transport
        return _persist(path, data, dry_run)
    # ② 主干有但本地无 → 先复制主干条目到本地再更新。
    trunk_profiles = config.get("profiles") or {}
    if isinstance(trunk_profiles, dict) and key in trunk_profiles:
        if not isinstance(profiles, dict):
            profiles = {}
            data["profiles"] = profiles
        profiles[key] = dict(trunk_profiles[key])
        if url is not None:
            profiles[key]["url"] = url
        if name is not None:
            profiles[key]["name"] = name
        if auth_token is not None:
            profiles[key]["auth_token"] = auth_token
        if command is not None:
            profiles[key]["command"] = command
        if transport is not None:
            profiles[key]["transport"] = transport
        return _persist(path, data, dry_run)
    return {"status": "error", "message": f"endpoint {key!r} not present", "path": path, "backup": ""}


def set_client_attach(
    config: Dict[str, Any],
    client_name: str,
    endpoints: List[str],
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Set the ``mcp_attach`` list for one client in the store.

    Because ``profile_sources`` just merges profiles/templates/active_profile, a
    per-client attachment lives on the client entry in the trunk registry.  We
    persist it as a dedicated ``client_mcp_attach`` overlay key and teach
    ``apply_profile_sources`` to apply it (see profile_loader).  This keeps the
    trunk registry untouched while still allowing GUI-driven attachment edits.
    """
    path = _write_target(config)
    if not _source_paths(config):
        return {"status": "error", "message": "no profile_sources configured", "path": "", "backup": ""}
    data = _load_target(path)
    attaches = data.setdefault("client_mcp_attach", {})
    if not isinstance(attaches, dict):
        attaches = {}
        data["client_mcp_attach"] = attaches
    attaches[client_name] = list(endpoints)
    return _persist(path, data, dry_run)
