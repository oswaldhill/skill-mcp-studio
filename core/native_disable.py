"""Stage-4 follow-up: client-native disabled markers (收尾清单第 7 项).

Survey (2026-09-04, this machine): none of the 8 managed clients currently
exposes a native per-skill disable marker — Codex ``config.toml``, Claude Code
``.claude.json``, Cursor settings and OpenCode ``opencode.jsonc`` were all
checked; symlink presence IS the effective mechanism. Hermes Agent's native
``hermes skills config`` is not locally discoverable (no ``hermes`` binary).

This module is the config-driven read hook so a future client plugs in without
core changes — declare on the ``mcp_tools`` entry::

    native_disable:
      path: ~/.client/state.json
      format: json          # json | yaml | toml
      key_path: [disabledSkills]

Read-only by design: markers are owned by the client runtime, never written by
this tool. Unreadable specs fail open to "no native disables" — the symlink
truth still governs. ``skill_state.read_skill_states`` applies the overlay;
``classify_skill_state`` stays pure filesystem truth (toggle writes need it).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Set

import yaml


def _nested(data: Any, key_path: List[str]) -> Any:
    current = data
    for key in key_path or []:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def read_native_disabled(tool: Dict[str, Any]) -> Set[str]:
    """Return the set of skill names the client runtime natively disables.

    Absent spec, missing file, unknown format, malformed content or a missing
    key all return an empty set (fail-open: never fabricate a disable).
    """
    spec = tool.get("native_disable") if isinstance(tool, dict) else None
    if not isinstance(spec, dict):
        return set()
    path = os.path.expanduser(spec.get("path") or "")
    if not path or not os.path.isfile(path):
        return set()
    fmt = spec.get("format", "json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if fmt == "yaml":
            data = yaml.safe_load(text)
        elif fmt == "toml":
            import tomllib  # stdlib since 3.11

            data = tomllib.loads(text)
        else:
            data = json.loads(text)
    except (OSError, ValueError, yaml.YAMLError):
        return set()
    values = _nested(data, spec.get("key_path") or [])
    if not isinstance(values, list):
        return set()
    return {str(item) for item in values if isinstance(item, (str, int))}
