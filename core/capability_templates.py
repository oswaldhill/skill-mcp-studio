"""Capability-group template loading and resolution (phase 2).

``required_capabilities`` in a profile can either list tool names inline (phase-1
behavior) or reference named templates via ``extends``.  This module resolves the
references into an ordinary ``{group: [tool, ...]}`` mapping so the engine's
``_has_group`` semantics stay unchanged.

Merge semantics (设计 §4.1 / ADR-7 / ADR-8 / 阶段二 §14.1 落地):

- only ``profile -> template`` references are supported (no template nesting);
- referenced templates union their groups in order, unioning tools per group;
- handwritten groups override referenced groups (whole-group replace);
- no ``extends`` => the handwritten mapping is returned unchanged.

Template sources (later wins): inline ``config['templates']`` < project-level
directory ``<config_dir>/.skill-mcp-studio/templates/`` (随主仓库分发, 阶段二
§14.1 延期项落地) < user directory ``~/.config/skill-mcp-studio/templates/``.

Failure mode (评审 CLI-4 整改): every ``*.yaml``/``*.yml`` file in a template
directory must parse and normalize; malformed or unreadable files fail fast with
``TemplateError`` (exit code 2) listing every offender — never silently skipped.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


class TemplateError(ValueError):
    """Raised when a capability template cannot be loaded or resolved."""


def _default_user_dir() -> str:
    """User-level template directory, platform-aware.

    - Windows: ``%APPDATA%\\skill-mcp-studio\\templates`` (Roaming standard);
    - POSIX (macOS / Linux): ``~/.config/skill-mcp-studio/templates`` (XDG).
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "skill-mcp-studio", "templates")
    return os.path.join(
        os.path.expanduser("~"), ".config", "skill-mcp-studio", "templates"
    )


def _normalize_template(name: str, template: Any) -> Dict[str, Any]:
    if not isinstance(template, dict):
        raise TemplateError(f"template {name!r} must be a mapping")
    caps = template.get("capabilities")
    if not isinstance(caps, dict) or not caps:
        raise TemplateError(
            f"template {name!r} requires a non-empty 'capabilities' mapping"
        )
    normalized: Dict[str, List[str]] = {}
    for group, tools in caps.items():
        if not isinstance(group, str) or not group:
            raise TemplateError(
                f"template {name!r}: capability group names must be non-empty strings"
            )
        if not isinstance(tools, list) or not tools or not all(
            isinstance(t, str) and t for t in tools
        ):
            raise TemplateError(
                f"template {name!r}: group {group!r} tools must be a non-empty list of strings"
            )
        normalized[group] = list(tools)
    tags = template.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list):
        raise TemplateError(f"template {name!r}: 'tags' must be a list")
    return {"tags": tags, "capabilities": normalized}


def load_templates(
    config: Dict[str, Any],
    user_dir: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load capability templates from every source, later sources winning.

    Overlay priority (ADR-8 + 阶段二 §14.1):
    inline ``config['templates']`` < project-level ``project_dir`` < user
    ``user_dir`` (same-name templates replace earlier ones).  Malformed files in
    either directory raise ``TemplateError`` (fail fast, review CLI-4).
    Unknown/absent ``templates`` yields ``{}`` (no templates defined).
    """
    templates: Dict[str, Dict[str, Any]] = {}
    raw = config.get("templates")
    if raw is not None:
        if not isinstance(raw, dict):
            raise TemplateError("'templates:' must be a mapping of name -> template")
        for name, template in raw.items():
            templates[name] = _normalize_template(name, template)
    templates.update(_load_dir_templates(project_dir, "project"))
    templates.update(_load_dir_templates(user_dir or _default_user_dir(), "user"))
    return templates


def _load_dir_templates(directory: Optional[str], label: str) -> Dict[str, Dict[str, Any]]:
    """Load ``*.yaml``/``*.yml`` templates from a directory (file stem = name).

    Each file holds a single template: ``capabilities:`` (+ optional ``tags:``).
    Any malformed / unreadable file fails fast with ``TemplateError`` listing all
    offenders (评审 CLI-4：绝不静默跳过).
    """
    import yaml

    if not directory or not os.path.isdir(directory):
        return {}
    loaded: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, filename)
        name = os.path.splitext(filename)[0]
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path}: unreadable or invalid YAML ({exc})")
            continue
        try:
            if not isinstance(data, dict) or "capabilities" not in data:
                raise TemplateError("missing required 'capabilities:' mapping")
            loaded[name] = _normalize_template(name, data)
        except TemplateError as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        raise TemplateError(
            f"malformed {label} template(s) in {directory} (fix or remove):\n  "
            + "\n  ".join(errors)
        )
    return loaded


def resolve_capabilities(
    profile: Dict[str, Any],
    templates: Dict[str, Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Return the profile's effective ``required_capabilities`` after ``extends``."""
    required = profile.get("required_capabilities") or {}
    if not isinstance(required, dict):
        raise TemplateError("'required_capabilities:' must be a mapping")

    extends = required.get("extends")
    handwritten = {
        group: (list(tools) if isinstance(tools, list) else tools)
        for group, tools in required.items()
        if group != "extends"
    }

    if not extends:
        return handwritten

    if isinstance(extends, str):
        extends = [extends]
    if not isinstance(extends, list) or not extends:
        raise TemplateError(
            "'required_capabilities.extends:' must be a template name or non-empty list of names"
        )

    resolved: Dict[str, List[str]] = {}
    for tpl_name in extends:
        if not isinstance(tpl_name, str) or not tpl_name:
            raise TemplateError("'extends' entries must be non-empty template names")
        template = templates.get(tpl_name)
        if template is None:
            raise TemplateError(
                f"unknown template {tpl_name!r}; defined: {sorted(templates)}"
            )
        for group, tools in template["capabilities"].items():
            merged = resolved.get(group, [])
            seen = set(merged)
            for tool in tools:
                if tool not in seen:
                    merged.append(tool)
                    seen.add(tool)
            resolved[group] = merged

    # handwritten groups override referenced groups (whole-group replace)
    for group, tools in handwritten.items():
        resolved[group] = list(tools) if isinstance(tools, list) else tools

    return resolved