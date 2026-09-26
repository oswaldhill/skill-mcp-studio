"""GUI/CLI consistency verifier (phase 3 DoD guard).

Given one JSON snapshot (the ``--all-profiles --format json`` output the GUI
consumes), re-derive every classification from the engine and assert the snapshot
and the engine agree. Because the GUI renders the snapshot verbatim, this proves
"GUI conclusion == CLI conclusion" without a second implementation.

Checks:
  1. aggregate envelope: schema_version == 1, profiles/results present;
  2. per result: ``ok`` equals ``combined_checker.result_ok`` re-run on the same
     records/probe/unmanaged;
  3. per record: injected ``state`` equals ``dashboard_states.classify_record``
     re-run on the same fields (catches any annotation drift);
  4. record contract: every required §2.2 field present.
"""

from __future__ import annotations

from typing import Any, Dict, List

from combined_checker import result_ok
from dashboard_states import classify_record

REQUIRED_RECORD_FIELDS = [
    "name",
    "installed",
    "install_evidence",
    "skills_compliant",
    "mcp_configured",
    "configured_url",
    "mcp_initialize_ok",
    "mcp_tools_list_ok",
    "capabilities",
    "hooks_configured",
    "hooks_required",
    "hook_events",
    "legacy_channels",
    # Stage-4 (L5): the dashboard renders per-skill enable/disable state, so
    # the snapshot contract guarantees these fields on every record.
    "skill_states",
    "skills_enabled_count",
    "skills_total",
    "skill_link_form",
    "native_disabled_skills",
]


def verify_snapshot(snapshot: Dict[str, Any]) -> List[str]:
    """Return a list of violation strings; empty means GUI/CLI are consistent."""
    violations: List[str] = []

    if not isinstance(snapshot, dict):
        return ["snapshot is not a mapping"]

    if snapshot.get("schema_version") != 1:
        violations.append(f"schema_version {snapshot.get('schema_version')!r} != 1")
    if not isinstance(snapshot.get("profiles"), list):
        violations.append("missing 'profiles' list")
    if not isinstance(snapshot.get("results"), list):
        violations.append("missing 'results' list")
        return violations

    for idx, result in enumerate(snapshot["results"]):
        where = f"results[{idx}] (profile={result.get('profile','')!r})"
        if not isinstance(result, dict):
            violations.append(f"{where}: not a mapping")
            continue

        probe = result.get("probe", {})
        records = result.get("records", []) or []
        unmanaged = result.get("unmanaged", []) or []

        # ok must equal re-running result_ok over the same content.
        expected_ok = result_ok({"probe": probe, "records": records, "unmanaged": unmanaged})
        if bool(result.get("ok")) != bool(expected_ok):
            violations.append(f"{where}: ok={result.get('ok')!r} but result_ok={expected_ok!r}")

        for ridx, record in enumerate(records):
            rwhere = f"{where}.records[{ridx}] ({record.get('name','')!r})"
            for field in REQUIRED_RECORD_FIELDS:
                if field not in record:
                    violations.append(f"{rwhere}: missing contract field {field!r}")
            if "state" in record:
                expected_state = classify_record(record, probe)
                if record["state"] != expected_state:
                    violations.append(
                        f"{rwhere}: state={record['state']!r} but classify={expected_state!r}"
                    )
            else:
                violations.append(f"{rwhere}: missing 'state' annotation")

    return violations


def verify_snapshot_json(text: str) -> List[str]:
    """Parse JSON text then ``verify_snapshot`` (empty list when valid+consistent)."""
    import json

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    return verify_snapshot(data)
