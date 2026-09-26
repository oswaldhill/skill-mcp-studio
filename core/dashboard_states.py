"""Read-only dashboard tri-state classification (phase 3).

The GUI renders each installed client as green / yellow / red / gray. The rule
set deliberately reuses the same record fields as ``combined_checker.result_ok``
so a CLI run and a GUI run can never disagree.

GREEN == fully compliant, YELLOW == not-probed / legacy-to-migrate / hooks missing,
RED == a hard failure, GRAY == not installed.

A-2 (probe tri-state): "not probed" is NOT a failure — a config-only run never
ran the live L4 probe, so its probe-derived fields cannot gate the exit code.
The probe state is made explicit below and consumed by ``result_ok`` so that

    result_ok(result) is True  <=>  no installed record is a hard failure and
                                   unmanaged == []  (probe "not probed" is a pass)
"""

from __future__ import annotations

from typing import Any, Dict


STATE_GREEN = "green"
STATE_YELLOW = "yellow"
STATE_RED = "red"
STATE_GRAY = "gray"

# A-2: explicit probe tri-state (probed-ok / probed-failed / not-probed).
PROBE_STATE_OK = "probed_ok"
PROBE_STATE_FAILED = "probed_failed"
PROBE_STATE_NOT_PROBED = "not_probed"


def probe_state(probe: Dict[str, Any]) -> str:
    """Classify the endpoint probe into the A-2 tri-state.

    ``probe`` is the ``check_agents`` result's ``probe`` dict.  Its ``error``
    field carries the full signal:
    - ``"not probed"`` → the live L4 probe never ran (config-only run),
    - any other non-empty error → the probe ran and failed,
    - empty → the probe ran and succeeded.
    """
    error = (probe or {}).get("error", "")
    if error == "not probed":
        return PROBE_STATE_NOT_PROBED
    return PROBE_STATE_FAILED if error else PROBE_STATE_OK


def _probe_phase(probe_error: str) -> str:
    """Map probe.error to the probe phase used for classification."""
    if probe_error == "not probed":
        return "not_probed"
    return "failed" if probe_error else "probed"


def classify_record(record: Dict[str, Any], probe: Dict[str, Any]) -> str:
    """Return green/yellow/red/gray for one ``check_agents`` record.

    ``record`` must include ``name``, ``installed``, ``skills_compliant``,
    ``mcp_configured``, ``mcp_initialize_ok``, ``mcp_tools_list_ok``,
    ``hooks_configured``, ``capabilities``, ``legacy_channels``.
    """
    if not record.get("installed"):
        return STATE_GRAY

    probe_error = (probe or {}).get("error", "")
    phase = _probe_phase(probe_error)

    # Hard failures -> RED.
    if not record.get("skills_compliant"):
        return STATE_RED
    if not record.get("mcp_configured"):
        return STATE_RED
    if phase == "failed":
        return STATE_RED
    if phase == "probed":
        if not record.get("mcp_initialize_ok") or not record.get("mcp_tools_list_ok"):
            return STATE_RED
        capabilities = record.get("capabilities", {}) or {}
        if not all(capabilities.values()):
            return STATE_RED

    # Fully compliant -> GREEN. hooks 只在端点适用时才是硬性要求
    # （纯工具端点 record.hooks_required=False，未配 hooks 不阻断 green）。
    capabilities = record.get("capabilities", {}) or {}
    if (
        record.get("skills_compliant")
        and record.get("mcp_configured")
        and record.get("mcp_initialize_ok")
        and record.get("mcp_tools_list_ok")
        and (record.get("hooks_configured") or not record.get("hooks_required", True))
        and not record.get("legacy_channels")
        and all(capabilities.values())
        and phase == "probed"
    ):
        return STATE_GREEN

    # Everything else: not-probed, legacy_to_migrate, or hooks missing -> YELLOW.
    return STATE_YELLOW


def classify_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Classify every record in a ``check_agents`` result, plus unmanaged split."""
    probe = result.get("probe", {})
    records: Dict[str, str] = {}
    for record in result.get("records", []) or []:
        records[record.get("name", "")] = classify_record(record, probe)
    unmanaged = [item.get("name", "") for item in result.get("unmanaged", []) or []]
    return {
        "records": records,
        "unmanaged": unmanaged,
    }


def all_installed_compliant(result: Dict[str, Any]) -> bool:
    """Independent re-derivation of ``result_ok`` from the GUI tri-state.

    A-2: a not-probed (YELLOW) record with no legacy/hooks gap is compliant —
    the live probe being absent is a measurement gap, not a failure.  RED and
    YELLOW-for-legacy/hooks are failures.  This is the GUI-side twin of
    ``combined_checker.result_ok``, so the two implementations are compared in
    ``test_dashboard_states`` to catch drift.
    """
    probe = result.get("probe", {})
    if result.get("unmanaged"):
        return False
    for record in result.get("records", []) or []:
        if not record.get("installed"):
            continue
        color = classify_record(record, probe)
        if color == STATE_RED:
            return False
        if color == STATE_GREEN:
            continue
        # YELLOW is compliant only when the sole reason is "not probed"; a legacy
        # channel or a missing (required) hook is still a failure.
        if record.get("legacy_channels"):
            return False
        if not (record.get("hooks_configured") or not record.get("hooks_required", True)):
            return False
    return True
