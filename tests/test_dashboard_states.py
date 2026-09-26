"""Tri-state classification tests + the result_ok consistency invariant."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from combined_checker import result_ok  # noqa: E402
from dashboard_states import (  # noqa: E402
    STATE_GRAY,
    STATE_GREEN,
    STATE_RED,
    STATE_YELLOW,
    all_installed_compliant,
    classify_record,
    probe_state,
)


def rec(**overrides):
    base = {
        "name": "Codex",
        "installed": True,
        "skills_compliant": True,
        "mcp_configured": True,
        "mcp_initialize_ok": True,
        "mcp_tools_list_ok": True,
        "hooks_configured": True,
        "capabilities": {"memory": True},
        "legacy_channels": [],
    }
    base.update(overrides)
    return base


def probe(error=""):
    return {"error": error}


class TriStateTest(unittest.TestCase):
    def test_green(self):
        self.assertEqual(classify_record(rec(), probe("")), STATE_GREEN)

    def test_gray_when_not_installed(self):
        self.assertEqual(classify_record(rec(installed=False), probe("")), STATE_GRAY)

    def test_red_when_skills_non_compliant(self):
        self.assertEqual(classify_record(rec(skills_compliant=False), probe("")), STATE_RED)

    def test_red_when_mcp_not_configured(self):
        self.assertEqual(classify_record(rec(mcp_configured=False), probe("")), STATE_RED)

    def test_red_when_probe_failed(self):
        self.assertEqual(classify_record(rec(), probe("connect fail")), STATE_RED)

    def test_red_when_capability_unmet(self):
        self.assertEqual(classify_record(rec(capabilities={"memory": False}), probe("")), STATE_RED)

    def test_yellow_when_not_probed(self):
        # Everything ready except the L4 probe never ran -> not a hard failure.
        r = rec(mcp_initialize_ok=False, mcp_tools_list_ok=False, capabilities={"memory": False})
        self.assertEqual(classify_record(r, probe("not probed")), STATE_YELLOW)

    def test_yellow_when_legacy_channels_present(self):
        self.assertEqual(classify_record(rec(legacy_channels=["hermes-nas"]), probe("")), STATE_YELLOW)

    def test_yellow_when_hooks_missing(self):
        self.assertEqual(classify_record(rec(hooks_configured=False), probe("")), STATE_YELLOW)

    def test_green_when_hooks_not_required(self):
        # 纯工具端点 hooks_required=False：未配 hooks 不阻断 GREEN。
        r = rec(hooks_configured=False, hooks_required=False, capabilities={})
        self.assertEqual(classify_record(r, probe("")), STATE_GREEN)


class ConsistencyInvariantTest(unittest.TestCase):
    def test_result_ok_equals_all_installed_compliant(self):
        """The DoD invariant: CLI result_ok must agree with the GUI tri-state."""
        cases = [
            # (records, unmanaged, probe_error)
            ([rec()], [], ""),
            ([rec(skills_compliant=False)], [], ""),
            ([rec(mcp_configured=False)], [], ""),
            ([rec()], [], "connect fail"),
            ([rec(capabilities={"memory": False})], [], ""),
            ([rec(installed=False)], [], ""),  # nothing installed -> vacuously ok
            ([rec(mcp_initialize_ok=False, mcp_tools_list_ok=False, capabilities={"memory": False})], [], "not probed"),
            ([rec(legacy_channels=["h"])], [], ""),
            ([rec(hooks_configured=False)], [], ""),
            ([rec()], [{"name": "Orphan"}], ""),  # unmanaged -> not ok
        ]
        for records, unmanaged, probe_error in cases:
            result = {
                "probe": {"error": probe_error},
                "records": records,
                "unmanaged": unmanaged,
                "summary": {},
            }
            self.assertEqual(
                result_ok(result),
                all_installed_compliant(result),
                msg=f"invariant broken for probe_error={probe_error!r} records={records} unmanaged={unmanaged}",
            )

    def test_a2_config_only_reaches_ok(self):
        """A-2 regression: a not-probed but otherwise compliant run is exit 0."""
        result = {
            "probe": {"error": "not probed"},
            "records": [rec(mcp_initialize_ok=False, mcp_tools_list_ok=False, capabilities={"memory": False})],
            "unmanaged": [],
            "summary": {},
        }
        self.assertTrue(result_ok(result))
        self.assertEqual(probe_state(result["probe"]), "not_probed")


if __name__ == "__main__":
    unittest.main()
