"""Stage-4 follow-up: root -> per_skill link migration (design §14.1 P2).

Single-skill enable/disable needs the per-skill symlink form, but real clients
are root-form (whole-dir symlink) today. ``migrate_client_links`` converts one
client with the mcp_fixer safety shape (ADR-18):

    staging build -> backup root link -> atomic swap -> validate -> rollback

Both swap steps are ``os.replace`` on one filesystem, so the client is never
left without a skills dir except between the two renames; a failed validate
restores the original root symlink exactly.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Dict, List

from mcp_fixer import _backup_path
from skill_state import read_skill_states, repo_skill_names, skill_link_form


def _result(name: str, skills_dir: str, status: str, message: str) -> Dict[str, str]:
    return {"name": name, "path": skills_dir, "status": status, "message": message}


def _first_skills_dir(tool: Dict[str, Any]) -> str | None:
    paths = tool.get("skills_paths") or []
    if not paths:
        return None
    return os.path.expanduser(paths[0])


def _validate_migration(skills_dir: str, unified_dir: str, expected_skills: List[str]) -> bool:
    """Post-write check: per_skill form and every repo skill enabled."""
    if skill_link_form(skills_dir, unified_dir) != "per_skill":
        return False
    states = read_skill_states(skills_dir, unified_dir)
    if len(states) != len(expected_skills):
        return False
    return all(state == "enabled" for state in states.values())


def migrate_client_links(
    tool: Dict[str, Any], unified_dir: str, *, dry_run: bool = False
) -> Dict[str, str]:
    """Migrate one client from root-symlink form to per-skill symlinks."""
    name = tool.get("name", "Unknown")
    skills_dir = _first_skills_dir(tool)
    if skills_dir is None:
        return _result(name, "", "error", "tool has no skills_paths; cannot migrate")
    if not tool.get("fix_supported", True):
        return _result(
            name, skills_dir, "unsupported", "link migration is not supported for this client"
        )

    form = skill_link_form(skills_dir, unified_dir)
    if form == "per_skill":
        return _result(name, skills_dir, "unchanged", "already in per-skill symlink form")
    if form == "mixed":
        return _result(name, skills_dir, "skip", "mixed form needs manual cleanup before migration")

    skills = repo_skill_names(unified_dir)
    if not skills:
        return _result(name, skills_dir, "error", "repo has no skills; refusing to migrate")

    if dry_run:
        return _result(
            name, skills_dir, "dry-run",
            f"would migrate root symlink to {len(skills)} per-skill symlinks",
        )

    # form == "root": skills_dir itself is a symlink at the repo. Build the
    # per-skill directory in a sibling staging dir first (same filesystem), so
    # the root link only moves aside once everything is ready.
    repo = os.path.expanduser(unified_dir)
    staging = tempfile.mkdtemp(
        prefix=".skill-migrate-", dir=os.path.dirname(skills_dir) or "."
    )
    try:
        for skill in skills:
            # realpath on both sides: the OS resolves relative symlinks from
            # the link's physical dir; logical paths miss the repo whenever an
            # intermediate symlink adds depth (macOS /var -> /private/var).
            target = os.path.relpath(
                os.path.realpath(os.path.join(repo, skill)), os.path.realpath(staging)
            )
            os.symlink(target, os.path.join(staging, skill))
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return _result(name, skills_dir, "error", f"staging build failed: {exc}")

    backup_name = _backup_path(skills_dir)
    try:
        os.replace(skills_dir, backup_name)  # atomic unlink of the root symlink
        os.replace(staging, skills_dir)      # atomic placement of the per-skill dir
    except OSError as exc:
        try:
            if os.path.lexists(backup_name) and not os.path.lexists(skills_dir):
                os.replace(backup_name, skills_dir)
            shutil.rmtree(staging, ignore_errors=True)
        except OSError:
            pass
        return _result(name, skills_dir, "error", f"migration swap failed: {exc}")

    if _validate_migration(skills_dir, unified_dir, skills):
        # success: drop the root-link backup (state is fully re-expressed)
        try:
            if os.path.lexists(backup_name):
                os.unlink(backup_name)
        except OSError:
            pass
        return _result(
            name, skills_dir, "migrated",
            f"migrated root symlink to {len(skills)} per-skill symlinks",
        )

    # validate failed -> rollback: drop the per-skill dir, restore the root link
    try:
        shutil.rmtree(skills_dir)
        os.replace(backup_name, skills_dir)
    except OSError as rollback_exc:
        return _result(
            name, skills_dir, "error",
            f"validate failed; rollback failed (backup at {backup_name}): {rollback_exc}",
        )
    return _result(name, skills_dir, "error", "post-write validate failed; rolled back")
