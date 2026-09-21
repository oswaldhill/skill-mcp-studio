"""Stage-4 per-skill enable/disable (ADR-18 / ADR-21).

The toggle reuses the mcp_fixer safety shape — backup, atomic write,
post-write validate, automatic rollback on failure — but the "write" of a
symlink is ``os.symlink(temp_name) + os.replace(temp_name, target)`` (ADR-21)
so there is no unlink-then-symlink window. ``disable`` records the prior link
target so a failed validate can restore it exactly rather than leaving the
skill in an indeterminate state.

Design §6.1 / §8.2 / §9 error-exit table.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from file_atomic import backup_path as _backup_path
from skill_state import classify_skill_state, repo_skill_names, skill_link_form


def _result(name: str, skills_dir: str, status: str, message: str) -> Dict[str, str]:
    return {
        "name": name,
        "path": skills_dir,
        "status": status,
        "message": message,
    }


def _first_skills_dir(tool: Dict[str, Any]) -> Optional[str]:
    paths = tool.get("skills_paths") or []
    if not paths:
        return None
    return os.path.expanduser(paths[0])


def _atomic_symlink(rel_or_abs_target: str, link_path: str) -> None:
    """Create/replace a symlink atomically via temp + os.replace (ADR-21).

    The temp name is a sibling dotfile so the final ``os.replace`` stays on one
    filesystem (atomic on POSIX for both files and symlinks).
    """
    directory = os.path.dirname(link_path) or "."
    base = os.path.basename(link_path)
    temp = os.path.join(directory, f".{base}.symlink-{os.getpid()}.tmp")
    try:
        os.symlink(rel_or_abs_target, temp)
        os.replace(temp, link_path)
    finally:
        if os.path.islink(temp) or os.path.exists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass


def _relative_target(repo_skill: str, skills_dir: str) -> str:
    """Prefer a relative target so the link survives repo relocation (fixer.py style).

    Both sides are ``realpath``-ed first: the OS resolves a relative symlink
    from the link's *physical* directory, so computing against logical paths
    misses the repo whenever an intermediate symlink adds depth (macOS
    ``/var -> /private/var``, i.e. every tempfile-based sandbox).
    """
    try:
        return os.path.relpath(os.path.realpath(repo_skill), os.path.realpath(skills_dir))
    except ValueError:
        return repo_skill


def enable_skill(tool: Dict[str, Any], skill: str, unified_dir: str, *, dry_run: bool = False) -> Dict[str, str]:
    """Enable one skill for one client by creating its per-skill symlink."""
    name = tool.get("name", "Unknown")
    skills_dir = _first_skills_dir(tool)
    if skills_dir is None:
        return _result(name, "", "error", "tool has no skills_paths; cannot toggle")
    if not tool.get("fix_supported", True):
        return _result(name, skills_dir, "unsupported", "skill toggle is not supported for this client")

    if skill not in repo_skill_names(unified_dir):
        return _result(name, skills_dir, "error", f"skill {skill!r} not in repo")

    form = skill_link_form(skills_dir, unified_dir)
    if form == "root":
        return _result(name, skills_dir, "skip", "root-symlink form: enable whole repo instead of per-skill")
    if form == "mixed":
        return _result(name, skills_dir, "skip", "mixed form: migrate to per-skill links first")

    link_path = os.path.join(skills_dir, skill)
    repo_skill = os.path.join(os.path.expanduser(unified_dir), skill)

    if classify_skill_state(skills_dir, unified_dir, skill) == "enabled":
        return _result(name, skills_dir, "unchanged", "skill is already enabled")

    if dry_run:
        return _result(name, skills_dir, "dry-run", f"would enable {skill} via per-skill symlink")

    previous_target = None
    if os.path.islink(link_path):
        try:
            previous_target = os.readlink(link_path)
        except OSError:
            previous_target = None

    os.makedirs(skills_dir, exist_ok=True)
    target = _relative_target(repo_skill, skills_dir)
    try:
        _atomic_symlink(target, link_path)
    except OSError as exc:
        return _result(name, skills_dir, "error", f"atomic symlink failed: {exc}")

    if classify_skill_state(skills_dir, unified_dir, skill) != "enabled":
        # validate failed -> restore the prior link (or remove if none existed)
        try:
            if previous_target is not None:
                _atomic_symlink(previous_target, link_path)
            elif os.path.islink(link_path) or os.path.lexists(link_path):
                os.unlink(link_path)
        except OSError as rollback_exc:
            return _result(name, skills_dir, "error", f"validate failed; rollback failed: {rollback_exc}")
        return _result(name, skills_dir, "error", "post-write validate failed; rolled back")

    return _result(name, skills_dir, "updated", f"enabled {skill}")


def disable_skill(tool: Dict[str, Any], skill: str, unified_dir: str, *, dry_run: bool = False) -> Dict[str, str]:
    """Disable one skill for one client by removing its per-skill symlink."""
    name = tool.get("name", "Unknown")
    skills_dir = _first_skills_dir(tool)
    if skills_dir is None:
        return _result(name, "", "error", "tool has no skills_paths; cannot toggle")
    if not tool.get("fix_supported", True):
        return _result(name, skills_dir, "unsupported", "skill toggle is not supported for this client")

    if skill not in repo_skill_names(unified_dir):
        return _result(name, skills_dir, "error", f"skill {skill!r} not in repo")

    form = skill_link_form(skills_dir, unified_dir)
    if form == "root":
        return _result(name, skills_dir, "skip", "root-symlink form: disable whole repo instead of per-skill")
    if form == "mixed":
        return _result(name, skills_dir, "skip", "mixed form: migrate to per-skill links first")

    link_path = os.path.join(skills_dir, skill)

    if classify_skill_state(skills_dir, unified_dir, skill) == "disabled":
        return _result(name, skills_dir, "unchanged", "skill is already disabled")

    if dry_run:
        return _result(name, skills_dir, "dry-run", f"would disable {skill} by removing its symlink")

    previous_target = None
    if os.path.islink(link_path):
        try:
            previous_target = os.readlink(link_path)
        except OSError:
            previous_target = None

    if not os.path.lexists(link_path):
        return _result(name, skills_dir, "unchanged", "no symlink to remove")

    # atomic remove: rename the link aside, then verify (rollback restores it)
    backup_name = _backup_path(link_path)
    try:
        os.replace(link_path, backup_name)
    except OSError as exc:
        return _result(name, skills_dir, "error", f"disable failed: {exc}")

    if classify_skill_state(skills_dir, unified_dir, skill) != "disabled":
        # validate failed -> restore the prior link
        try:
            os.replace(backup_name, link_path)
        except OSError as rollback_exc:
            return _result(
                name, skills_dir, "error",
                f"validate failed; rollback failed (backup at {backup_name}): {rollback_exc}",
            )
        return _result(name, skills_dir, "error", "post-write validate failed; rolled back")

    # success: drop the backup
    try:
        if os.path.lexists(backup_name):
            os.unlink(backup_name)
    except OSError:
        pass

    return _result(name, skills_dir, "updated", f"disabled {skill}")
