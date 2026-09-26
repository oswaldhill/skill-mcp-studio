"""GUI/CLI consistency verifier tests."""

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from gui_consistency import verify_snapshot, verify_snapshot_json  # noqa: E402
from multi_profile_reporter import report_all_profiles  # noqa: E402


def _result():
    return {
        "profile": "p",
        "ok": True,
        "endpoint": "https://example.internal/mcp",
        "probe": {"error": ""},
        "capability_groups": ["memory"],
        "records": [
            {
                "name": "Codex",
                "installed": True,
                "install_evidence": ["cli"],
                "skills_compliant": True,
                "mcp_configured": True,
                "configured_url": "https://example.internal/mcp",
                "mcp_initialize_ok": True,
                "mcp_tools_list_ok": True,
                "capabilities": {"memory": True},
                "hooks_configured": True,
                "hooks_required": True,
                "hook_events": ["on_session_end"],
                "legacy_channels": [],
                "skill_states": {"memory-basic": "enabled", "tdai": "enabled"},
                "skills_enabled_count": 2,
                "skills_total": 2,
                "skill_link_form": "per_skill",
                "native_disabled_skills": [],
            }
        ],
        "unmanaged": [],
        "summary": {"skill_state_consistent": True},
        "skill_state_drift": [],
    }


class VerifySnapshotTest(unittest.TestCase):
    def test_cli_json_is_consistent(self):
        # Round-trip through the real reporter so state/ok annotations are applied.
        snapshot = json.loads(report_all_profiles([_result()], "json", "p"))
        self.assertEqual(verify_snapshot(snapshot), [])

    def test_detects_state_annotation_drift(self):
        snapshot = json.loads(report_all_profiles([_result()], "json", "p"))
        snapshot["results"][0]["records"][0]["state"] = "red"  # wrong (should be green)
        violations = verify_snapshot(snapshot)
        self.assertTrue(any("state=" in v for v in violations), violations)

    def test_detects_ok_drift(self):
        snapshot = json.loads(report_all_profiles([_result()], "json", "p"))
        snapshot["results"][0]["ok"] = False  # wrong (should be True)
        violations = verify_snapshot(snapshot)
        self.assertTrue(any("ok=" in v for v in violations), violations)

    def test_detects_missing_contract_field(self):
        snapshot = json.loads(report_all_profiles([_result()], "json", "p"))
        del snapshot["results"][0]["records"][0]["installed"]
        violations = verify_snapshot(snapshot)
        self.assertTrue(any("installed" in v for v in violations), violations)

    def test_l5_fields_are_part_of_record_contract(self):
        # Stage-4: the GUI renders L5 (enabled/total, form, drift), so the
        # snapshot contract must guarantee those fields reach every record.
        snapshot = json.loads(report_all_profiles([_result()], "json", "p"))
        record = snapshot["results"][0]["records"][0]
        del record["skill_link_form"]
        violations = verify_snapshot(snapshot)
        self.assertTrue(any("skill_link_form" in v for v in violations), violations)

    def test_invalid_json_reports_parse_error(self):
        self.assertTrue(verify_snapshot_json("{not json"))


if __name__ == "__main__":
    unittest.main()
