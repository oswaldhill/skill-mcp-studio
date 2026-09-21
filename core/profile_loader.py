"""Load, validate, and select endpoint profiles.

Phase-1 endpoint-profile abstraction: the single ``unified_mcp`` section evolves
into a ``profiles`` collection plus ``active_profile``.  This module is the only
place that knows how to:

- select a profile (explicit ``--profile`` > ``active_profile``);
- wrap a legacy ``unified_mcp`` section back into a single profile so existing
  configs keep working unchanged;
- validate the structural version (``schema_version``).

Engine modules (``combined_checker``, ``mcp_fixer``, ``mcp_probe``) receive a
plain profile dict and never touch ``config`` internals.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import yaml

from capability_templates import TemplateError, load_templates, resolve_capabilities
from names import normalized_name


class ProfileError(ValueError):
    """Raised when a profile cannot be resolved or fails validation."""


LEGACY_AUTH_TOKEN_ENV = "HERMES_MCP_AUTH_TOKEN"


def apply_profile_sources(config: Dict[str, Any]) -> Dict[str, Any]:
    """Merge external ``profile_sources`` overlay files into ``config`` in place.

    Stage-4 follow-up (local topology isolation): the trunk ``config.yaml`` stays
    free of personal endpoints. ``profile_sources`` lists extra YAML files whose
    ``profiles`` / ``templates`` / ``active_profile`` are merged over the inline
    values — later sources win, and every source wins over the inline config.
    A missing file is skipped silently (it simply exists on another machine);
    an unreadable or malformed one fails through ``ProfileError`` (exit code 2).
    """
    sources = config.get("profile_sources") or []
    if not isinstance(sources, list):
        raise ProfileError("'profile_sources' must be a list of file paths")
    for raw_path in sources:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ProfileError(
                f"profile_sources entries must be path strings, got {raw_path!r}"
            )
        path = os.path.expanduser(raw_path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            raise ProfileError(f"profile source {raw_path!r} could not be read: {exc}") from exc
        if data is None:
            continue
        if not isinstance(data, dict):
            raise ProfileError(f"profile source {raw_path!r} must be a YAML mapping")

        source_profiles = data.get("profiles")
        if source_profiles is not None:
            if not isinstance(source_profiles, dict) or not source_profiles:
                raise ProfileError(
                    f"profile source {raw_path!r}: 'profiles' must be a non-empty mapping"
                )
            profiles = config.get("profiles")
            if not isinstance(profiles, dict):
                profiles = {}
            profiles.update(source_profiles)
            # 过滤 null 值（软删除标记：主干端点经 --remove-endpoint 后在本地文件写入 null）
            profiles = {k: v for k, v in profiles.items() if v is not None}
            config["profiles"] = profiles

        if "active_profile" in data:
            config["active_profile"] = data["active_profile"]

        # B3 fix: allow a profile source to carry a personal unified_skills_dir
        # override (machine-local path), so the trunk config.yaml stays free of
        # personal topology. Later sources win, like the other overlay keys.
        if "unified_skills_dir" in data:
            override_dir = data["unified_skills_dir"]
            if isinstance(override_dir, str) and override_dir.strip():
                config["unified_skills_dir"] = override_dir

        source_templates = data.get("templates")
        if isinstance(source_templates, dict) and source_templates:
            templates = config.get("templates")
            if not isinstance(templates, dict):
                templates = {}
            templates.update(source_templates)
            config["templates"] = templates

        # Stage-5 P3 attachment overlay: client_mcp_attach maps client name ->
        # endpoint keys and is applied onto each matching mcp_tools entry so the
        # check model keeps reading plain ``mcp_attach`` (no overlay awareness).
        # ARCH-4 fix: validate every overlay-referenced endpoint key exists
        # BEFORE mutating the registry, so a malformed overlay fails loudly at
        # load time (exit 2) rather than silently producing a half-applied state.
        attach_overlay = data.get("client_mcp_attach")
        if isinstance(attach_overlay, dict) and attach_overlay:
            valid_keys = set(list_profiles(config))
            for client_name, endpoints in attach_overlay.items():
                if not isinstance(endpoints, list):
                    raise ProfileError(
                        f"profile source {raw_path!r}: client_mcp_attach[{client_name!r}] must be a list"
                    )
                for ep_key in endpoints:
                    if not isinstance(ep_key, str) or ep_key not in valid_keys:
                        raise ProfileError(
                            f"profile source {raw_path!r}: client_mcp_attach[{client_name!r}] "
                            f"references unknown endpoint {ep_key!r}; valid: {sorted(valid_keys)}"
                        )
            registry = config.get("mcp_tools")
            if not isinstance(registry, list):
                registry = []
                config["mcp_tools"] = registry
            lookup = {
                normalized_name(tool.get("name", "")): tool
                for tool in registry
                if isinstance(tool, dict) and tool.get("name")
            }
            for client_name, endpoints in attach_overlay.items():
                if isinstance(client_name, str):
                    matched = lookup.get(normalized_name(client_name))
                    if matched is not None:
                        matched["mcp_attach"] = list(endpoints)

        # 本机停用清单：overlay 可声明 ``disabled_tools: [名称...]``，把 trunk
        # 注册表里的某客户端标记为「本机不再纳入管理」。仅本机覆盖，不删 trunk
        # 共享条目；合并为并集注入 config，供 effective_tools / run_scan 兜底过滤。
        raw_disabled = data.get("disabled_tools")
        if isinstance(raw_disabled, list):
            merged = {normalized_name(n) for n in config.get("disabled_tools") or [] if isinstance(n, str)}
            for n in raw_disabled:
                if isinstance(n, str) and n.strip():
                    merged.add(normalized_name(n))
            config["disabled_tools"] = sorted(merged)
    return config


def _wrap_legacy(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Wrap a legacy ``unified_mcp`` section into a single-profile mapping.

    The section name is taken from ``unified_mcp.name`` so migration is
    surfaced to the caller through the profile name.
    """
    legacy = config.get("unified_mcp") or {}
    if not isinstance(legacy, dict) or not legacy:
        return {}
    # Copy so we never mutate the caller's config.
    profile = dict(legacy)
    profile.setdefault("transport", "streamable-http")
    profile.setdefault("url_policy", "strict")
    profile.setdefault("auth_token_env", LEGACY_AUTH_TOKEN_ENV)
    profile.setdefault("probe_timeout", 8.0)
    name = legacy.get("name") or "default"
    return {name: {"name": legacy.get("name", name), **profile}}


def _validate_schema_version(config: Dict[str, Any]) -> None:
    version = config.get("schema_version")
    if version is None:
        return  # legacy configs predate the field; treat as v1
    if version != 1 and version != 2:
        raise ProfileError(
            f"unsupported schema_version {version!r}; this build supports 1 and 2"
        )


def load_profile(
    config: Dict[str, Any],
    profile_name: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the selected profile.

    ``config_path``（可选）用于定位项目级模板目录
    ``<config 所在目录>/.skill-mcp-studio/templates/``（阶段二 §14.1 落地）。

    Returns ``{"name": 段名, "profile": 字典, "config": 完整 config}``.
    """
    _validate_schema_version(config)
    profiles = config.get("profiles")
    if profiles is None:
        # Legacy structure: unified_mcp without profiles.
        wrapped = _wrap_legacy(config)
        if not wrapped:
            raise ProfileError(
                "no profiles found: declare 'profiles:' (or legacy 'unified_mcp:')"
            )
        name = profile_name or next(iter(wrapped))
        if name not in wrapped:
            raise ProfileError(
                f"profile {name!r} not found; available: {sorted(wrapped)}"
            )
        return _resolve_profile(name, wrapped[name], config, config_path)

    if not isinstance(profiles, dict) or not profiles:
        raise ProfileError("'profiles:' must be a non-empty mapping")
    name = profile_name or config.get("active_profile")
    if not name:
        raise ProfileError(
            "no profile selected: pass --profile or set 'active_profile:'"
        )
    if name not in profiles:
        raise ProfileError(
            f"profile {name!r} not found; available: {sorted(profiles)}"
        )
    profile = profiles[name]
    if not isinstance(profile, dict):
        raise ProfileError(f"profile {name!r} must be a mapping")
    return _resolve_profile(name, dict(profile), config, config_path)


def list_profiles(config: Dict[str, Any]) -> List[str]:
    """Return the set of selectable profile names (legacy or new)."""
    profiles = config.get("profiles")
    if profiles is not None and isinstance(profiles, dict):
        return sorted(k for k, v in profiles.items() if v is not None)
    return sorted(_wrap_legacy(config))


def _project_templates_dir(config_path: Optional[str]) -> Optional[str]:
    """项目级模板目录：``<config 所在目录>/.skill-mcp-studio/templates/``。

    阶段二 §14.1 落地——项目级模板随主仓库分发。config_path 缺省（如测试直接
    构造 config 字典）时返回 None，退化为「仅内置 + 用户模板」。
    """
    if not config_path:
        return None
    return os.path.join(
        os.path.dirname(os.path.abspath(config_path)),
        ".skill-mcp-studio",
        "templates",
    )


def _resolve_profile(
    name: str,
    profile: Dict[str, Any],
    config: Dict[str, Any],
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve ''.``required_capabilities.extends`` and wrap the bundle.

    Templates are loaded from ``config['templates']`` overlaid by the project-level
    directory (``<config_dir>/.skill-mcp-studio/templates/``) then the user
    directory.  A ``TemplateError`` propagates as ``ProfileError`` so callers keep
    a single failure channel at load time (exit code 2).
    """
    transport = profile.get("transport", "streamable-http")
    if transport not in ("streamable-http", "stdio"):
        # 阶段二 §4.2/§9：transport 合法取值仅 streamable-http/stdio；
        # 非法值在加载期 fail fast（退出码 2），绝不静默降级为 HTTP 探测。
        raise ProfileError(
            f"profile {name!r} has unsupported transport {transport!r}; "
            "expected 'streamable-http' or 'stdio'"
        )
    try:
        templates = load_templates(config, project_dir=_project_templates_dir(config_path))
        profile["required_capabilities"] = resolve_capabilities(profile, templates)
    except TemplateError as exc:
        raise ProfileError(str(exc)) from exc
    return {"name": name, "profile": profile, "config": config}