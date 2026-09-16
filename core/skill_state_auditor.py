"""Stage-4 skill-state auditor (design doc §4.3 / §6.2).

Three audit capabilities, all read-only with respect to the real clients:

1. drift detection      -- the same repo skill marked enabled in one client and
                           disabled in another is a drift row;
2. disable-effective    -- a ``disabled`` state must leave no symlink residue in
                           the client skills dir (config-layer verification, the
                           runtime injection check stays far-future, §14 open 4);
3. rollback idempotence -- ``enable -> disable -> enable -> disable`` on a
                           sandbox copy restores the starting state and repeats
                           identically (fixture-driven, never touches the real
                           client dir, §6.2 step 4).
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from typing import Any, Dict, List

from skill_state import classify_skill_state
from skill_toggle import disable_skill, enable_skill


def audit_skill_states(result: Dict[str, Any]) -> Dict[str, Any]:
    """Detect cross-client skill-state drift from a ``check_agents`` result.

    Returns ``{"skill_state_drift": [...], "skill_state_consistent": bool}``.
    Only installed records with non-empty ``skill_states`` participate; clients
    without a skills dir (or uninstalled ones) are excluded from drift.
    """
    records = result.get("records") or []
    per_skill: Dict[str, Dict[str, str]] = {}
    for record in records:
        if not record.get("installed"):
            continue
        states = record.get("skill_states") or {}
        if not states:
            continue
        for skill, state in states.items():
            per_skill.setdefault(skill, {})[record.get("name", "")] = state

    drift: List[Dict[str, Any]] = []
    for skill in sorted(per_skill):
        states = per_skill[skill]
        if len(set(states.values())) <= 1:
            continue  # every reporting client agrees -> no drift
        mode = Counter(states.values()).most_common(1)[0][0]
        drift.append({
            "skill": skill,
            "states": dict(states),
            "consistent": False,
            "drift_clients": sorted(
                client for client, state in states.items() if state != mode
            ),
        })

    return {"skill_state_drift": drift, "skill_state_consistent": not drift}


def verify_disable_effective(client_dir: str, unified_dir: str, skill: str) -> bool:
    """Return True when a ``disabled`` state is truly reflected in the config.

    Config-layer check (§6.2 step 3): a disabled skill must leave no symlink
    entry in the client skills dir — neither a valid link nor a dangling one.
    Enabled / not-in-repo skills have nothing to verify (vacuously effective).
    """
    state = classify_skill_state(client_dir, unified_dir, skill)
    if state != "disabled":
        return True
    link = os.path.join(os.path.expanduser(client_dir), skill)
    return not os.path.lexists(link)


def verify_rollback_idempotent(tool: Dict[str, Any], skill: str, unified_dir: str) -> Dict[str, Any]:
    """Non-destructive gate: enable/disable/enable/disable is reversible + idempotent.

    The sequence runs on a sandbox copy of the client skills dir (only the
    target skill's link is mirrored), so the real client dir is never mutated.
    ``ok`` requires: every toggle reaches its expected state, repeated identical
    toggles are no-ops, and the real dir's state is unchanged afterwards.
    """
    paths = tool.get("skills_paths") or []
    if not paths:
        return {"ok": False, "message": "tool has no skills_paths; cannot run gate"}

    skills_dir = os.path.expanduser(paths[0])
    start_state = classify_skill_state(skills_dir, unified_dir, skill)
    if start_state == "not_in_repo":
        return {"ok": False, "message": f"skill {skill!r} not in repo"}

    sandbox_tool = dict(tool)
    with tempfile.TemporaryDirectory() as scratch:
        sandbox_dir = os.path.join(scratch, "skills")
        os.mkdir(sandbox_dir)
        # mirror the target skill's existing link (if any) into the sandbox
        real_link = os.path.join(skills_dir, skill)
        if os.path.islink(real_link):
            try:
                os.symlink(os.readlink(real_link), os.path.join(sandbox_dir, skill))
            except OSError:
                pass
        sandbox_tool["skills_paths"] = [sandbox_dir]

        def state() -> str:
            return classify_skill_state(sandbox_dir, unified_dir, skill)

        steps: List[str] = []
        r = enable_skill(sandbox_tool, skill, unified_dir)
        if r["status"] not in ("updated", "unchanged") or state() != "enabled":
            return {"ok": False, "message": f"enable failed: {r['message']}"}
        steps.append("enable")

        r = enable_skill(sandbox_tool, skill, unified_dir)  # idempotent repeat
        if r["status"] != "unchanged":
            return {"ok": False, "message": "enable is not idempotent"}

        r = disable_skill(sandbox_tool, skill, unified_dir)
        if r["status"] not in ("updated", "unchanged") or state() != "disabled":
            return {"ok": False, "message": f"disable failed: {r['message']}"}
        steps.append("disable")

        r = disable_skill(sandbox_tool, skill, unified_dir)  # idempotent repeat
        if r["status"] != "unchanged":
            return {"ok": False, "message": "disable is not idempotent"}

        # reversibility: the second full cycle must land back on disabled too
        r = enable_skill(sandbox_tool, skill, unified_dir)
        if state() != "enabled":
            return {"ok": False, "message": "second enable did not reach enabled"}
        r = disable_skill(sandbox_tool, skill, unified_dir)
        if state() != "disabled":
            return {"ok": False, "message": "second disable did not restore disabled"}

    end_state = classify_skill_state(skills_dir, unified_dir, skill)
    if end_state != start_state:
        return {
            "ok": False,
            "message": f"real client dir changed during gate: {start_state} -> {end_state}",
        }
    return {"ok": True, "message": "enable/disable is reversible and idempotent"}
