"""Stage-4 skill-state tri-state classification (ADR-17).

The four-layer audit (install -> skills path -> MCP config -> live endpoint) is
extended to a 5th layer: per-skill enable/disable consistency across clients.

This module is the single place that normalizes the heterogeneous per-client
"enabled/disabled" semantics (Claude Code ``disabledMcpServers``, Codex profile
disables, or just a symlink's presence) into one tri-state:

    enabled       -- a valid symlink in the client skills dir points at the
                     matching repo skill (or, for root-form clients, the whole
                     repo is linked so every repo skill is on).
    disabled      -- the skill exists in the repo but the client does not have
                     a valid enable link for it.
    not_in_repo   -- the skill name is absent from the shared repo; such skills
                     never enter the per-client ``skill_states`` dict (ADR-17).

The same fields feed ``combined_checker.result_ok`` (optional, only under
``--strict-skill-state``) so a CLI run and a GUI run can never disagree on the
5th layer either.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List

from skills_analyser import scan_skills_distribution


@lru_cache(maxsize=None)
def repo_skill_names(unified_dir: str) -> List[str]:
    """Return the sorted, non-dot skill directory names under the shared repo.

    The inventory is sourced from ``skills_analyser.scan_skills_distribution``
    (design §5: the skills analyser is the single toggle-candidate source) and
    narrowed to non-dot directories — a skill is a directory in the repo.
    Hidden (dot-prefixed) entries and plain files are excluded.

    Semantics fixed by decision D11 (决策记录 §11): every non-dot subdir counts
    (2026-09-04 survey: 175/175 carry SKILL.md, incl. _core/bin/scripts/mcp),
    so there is no SKILL.md second-pass filter — L2/L5 inventories stay in sync.
    """
    distribution = scan_skills_distribution(unified_dir)
    return [
        name
        for name in distribution.get("skill_names", [])
        if not name.startswith(".")
    ]


def _read_frontmatter(repo: str, rel_path: str) -> Dict[str, str]:
    """Best-effort read of one SKILL.md's ``name``/``description``/``homepage``.

    ``rel_path`` is directory-relative to ``repo`` (``""`` for a top-level skill
    or ``apple/apple-notes`` for a nested one). Missing file, bad YAML, or a
    non-dict frontmatter all degrade to empty strings; the caller applies its
    own display-name fallback. Capped to 8 KiB so a huge skill body is never
    slurped into memory for a one-line description.
    """
    import re
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml is a declared dependency
        return {"name": "", "description": "", "homepage": ""}

    out: Dict[str, str] = {"name": "", "description": "", "homepage": ""}
    try:
        with open(os.path.join(repo, rel_path, "SKILL.md"), encoding="utf-8") as fh:
            head = fh.read(8192)
    except OSError:
        return out
    # frontmatter only ever lives at the top of SKILL.md
    prefix_re = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
    m = prefix_re.match(head)
    if not m:
        return out
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    # 显示名优先取 frontmatter 的 name（其次 title），否则回退目录名。
    fname = data.get("name") or data.get("title") or ""
    if isinstance(fname, str):
        out["name"] = fname.strip()
    desc = data.get("description") or ""
    md = data.get("metadata")
    if not desc and isinstance(md, dict):
        desc = md.get("short-description") or ""
    out["description"] = str(desc).strip()
    home = data.get("homepage") or ""
    if not home and isinstance(md, dict):
        home = md.get("homepage") or ""
    if isinstance(home, str):
        out["homepage"] = home.strip()
    return out


def read_skill_meta(unified_dir: str, skill_names: List[str]) -> Dict[str, Dict[str, str]]:
    """Read one-line metadata per skill from its ``SKILL.md`` frontmatter.

    Returns ``{skill_name: {"name": ..., "description": ..., "homepage": ...}}``.
    Purely read-only and best-effort: a missing file, unparseable frontmatter,
    or absent ``description`` / ``homepage`` keys degrades to an empty value
    rather than failing the snapshot (the skills manager UI renders both as
    optional one-liners; ``homepage`` powers the "官网" affordance when present).
    """
    repo = os.path.expanduser(unified_dir)
    meta: Dict[str, Dict[str, str]] = {}
    for name in skill_names:
        fm = _read_frontmatter(repo, name)
        meta[name] = {
            "name": fm.get("name") or name,
            "description": fm.get("description") or "",
            "homepage": fm.get("homepage") or "",
        }
    return meta


def read_nested_meta(unified_dir: str, skill_nesting: Dict[str, List[str]]) -> Dict[str, Dict[str, str]]:
    """Read one-line metadata for every nested (read-only) sub-skill.

    ``skill_nesting`` is the ``{top_dir: ["apple/apple-notes", ...]}`` map from
    :func:`scan_skill_nesting`. Returns ``{rel_path: {"name": ..., "description":
    ..., "homepage": ...}}`` keyed by the same relative paths so the GUI can show
    a nested skill's one-line description inside the fold-out tree. Missing or
    unparseable nested SKILL.md files degrade to empty strings, never raise.
    """
    repo = os.path.expanduser(unified_dir)
    meta: Dict[str, Dict[str, str]] = {}
    for rels in (skill_nesting or {}).values():
        for rel in rels:
            fm = _read_frontmatter(repo, rel)
            fallback = rel.rsplit(os.sep, 1)[-1] if os.sep in rel else rel
            meta[rel] = {
                "name": fm.get("name") or fallback,
                "description": fm.get("description") or "",
                "homepage": fm.get("homepage") or "",
            }
    return meta


def scan_skill_nesting(unified_dir: str) -> Dict[str, List[str]]:
    """Map each top-level container dir to its nested SKILL.md relative paths.

    A "container" is a non-dot top-level directory that also contains skills
    *deeper than one level down* (``apple/apple-notes/SKILL.md`` type nesting).
    The return value is ``{top_dir_name: ["apple/apple-notes", ...]}``; leaf
    top-level skills are absent from the mapping. Purely read-only discovery
    used by the skills manager to power the "按目录折叠" affordance: nested
    skills remain shown read-only and are NOT added to the managed toggle set
    (that set is still the flat top-level inventory from ``repo_skill_names``).
    """
    expanded = os.path.expanduser(unified_dir)
    result: Dict[str, List[str]] = {}
    if not os.path.isdir(expanded):
        return result
    for top in sorted(os.listdir(expanded)):
        if top.startswith("."):
            continue
        top_path = os.path.join(expanded, top)
        if not os.path.isdir(top_path):
            continue
        nested: List[str] = []
        for root, dirs, files in os.walk(top_path):
            # skip hidden subdirs to mirror the top-level dot filter
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            rel = os.path.relpath(root, expanded)
            # depth 0 is the top dir itself; we only want one-or-more levels down
            if rel.count(os.sep) >= 1 and "SKILL.md" in files:
                nested.append(rel)
        if nested:
            result[top] = sorted(nested)
    return result


def _norm(value: str) -> str:
    return os.path.normpath(os.path.expanduser(value))


def classify_skill_state(client_dir: str, unified_dir: str, skill: str) -> str:
    """Return ``enabled`` / ``disabled`` / ``not_in_repo`` for one skill.

    The判定 shares the exact-match rule with
    ``checker._per_skill_link_states`` (ADR-17): a per-skill symlink is enabled
    only when its ``realpath`` resolves to the **matching repo skill directory**
    (the entry's own name under the unified repo) — a link that points
    elsewhere inside the repo (another skill / repo root) is not that skill's
    enable link. Anything else (missing link, wrong target, native disabled
    marker) is disabled. A skill absent from the repo is ``not_in_repo``
    (excluded from drift by the caller).
    """
    if skill not in repo_skill_names(unified_dir):
        return "not_in_repo"
    client = os.path.expanduser(client_dir)
    repo = os.path.expanduser(unified_dir)

    # realpath both sides so macOS /tmp -> /private/tmp and other prefix symlinks
    # never make a valid link look disabled (same realpath basis as
    # checker._per_skill_link_states, which compares entry realpath ==
    # realpath(unified/<name>)).
    repo_real = os.path.realpath(repo)
    skill_real = os.path.realpath(os.path.join(repo, skill))

    # Root-form client: the whole skills dir is a symlink at the repo. Every
    # repo skill is then effectively on; a symlink to anywhere else is disabled.
    if os.path.islink(client):
        try:
            target = os.path.realpath(client)
        except OSError:
            return "disabled"
        return "enabled" if target == repo_real else "disabled"

    # Per-skill-form client: look for a per-skill symlink inside the dir.
    link = os.path.join(client, skill)
    if os.path.islink(link):
        try:
            target = os.path.realpath(link)
        except OSError:
            return "disabled"
        return "enabled" if target == skill_real else "disabled"

    # Real dir without the skill symlink, or a non-existent client dir: disabled.
    return "disabled"


def skill_link_form(client_dir: str, unified_dir: str) -> str:
    """Return the client's link form: ``root`` / ``per_skill`` / ``mixed``.

    - ``root``     -- the skills dir itself is a symlink to the repo.
    - ``per_skill``-- the dir is real and every entry is a symlink (or empty);
                      single-skill enable/disable is supported (ADR-21).
    - ``mixed``    -- real entries coexist with symlinks, or a real dir holds
                      no symlinks at all; needs migration before per-skill ops.

    Hidden (dot-prefixed) entries are ignored: clients drop runtime state into
    their skills dir (Codex materializes ``.system/``), and hidden names are
    outside the skill inventory by the dot rule — they must not block the form.
    """
    client = _norm(client_dir)
    if os.path.islink(client):
        return "root"
    if not os.path.isdir(client):
        # Nothing exists yet: enabling creates per-skill symlinks directly.
        return "per_skill"
    try:
        entries = [e for e in os.listdir(client) if not e.startswith(".")]
    except OSError:
        return "mixed"
    if not entries:
        return "per_skill"
    has_symlink = any(os.path.islink(os.path.join(client, e)) for e in entries)
    has_other = any(not os.path.islink(os.path.join(client, e)) for e in entries)
    if has_other:
        return "mixed"
    return "per_skill" if has_symlink else "mixed"


def read_skill_states(
    client_dir: str, unified_dir: str, native_disabled=frozenset()
) -> Dict[str, str]:
    """Return ``{skill: enabled|disabled}`` for repo skills only.

    ``not_in_repo`` skills are excluded by construction (ADR-17 §4.2). A
    root-form client marks every repo skill enabled; per-skill clients read
    each link individually. ``native_disabled`` (client-runtime markers, see
    ``native_disable.read_native_disabled``) overrides an otherwise-valid
    enable link — the client ignores that skill even though it is linked.
    """
    states = {
        skill: classify_skill_state(client_dir, unified_dir, skill)
        for skill in repo_skill_names(unified_dir)
    }
    if native_disabled:
        for skill in states:
            if skill in native_disabled:
                states[skill] = "disabled"
    return states


def write_skill_state(
    tool: Dict,
    skill: str,
    state: str,
    unified_dir: str,
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Write one skill's state for one client (design §5 write entry).

    Dispatches to the toggle operations (``skill_toggle``), which carry the
    backup -> atomic write -> validate -> rollback safety shape (ADR-18). The
    import is lazy because ``skill_toggle`` imports this module.
    """
    from skill_toggle import disable_skill, enable_skill  # local import: cycle guard

    if state == "enabled":
        return enable_skill(tool, skill, unified_dir, dry_run=dry_run)
    if state == "disabled":
        return disable_skill(tool, skill, unified_dir, dry_run=dry_run)
    raise ValueError(f"unknown skill state {state!r}; expected 'enabled' or 'disabled'")
