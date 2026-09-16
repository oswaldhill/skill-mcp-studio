import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from multi_profile_reporter import report_all_profiles  # noqa: E402


def _result(profile, groups, ok=True):
    return {
        "profile": profile,
        "ok": ok,
        "endpoint": "https://example.internal/mcp",
        "capability_groups": groups,
        "probe": {"error": ""},
        "records": [
            {
                "name": "Claude",
                "installed": True,
                "skills_compliant": True,
                "mcp_configured": True,
                "mcp_initialize_ok": True,
                "mcp_tools_list_ok": True,
                "capabilities": {g: True for g in groups},
                "hooks_configured": True,
                "legacy_channels": [],
            }
        ],
        "unmanaged": [],
        "summary": {},
    }


class MultiProfileReporterTest(unittest.TestCase):
    def test_csv_union_groups_with_empty_cells(self):
        results = [
            _result("a", ["hermes_memory", "ai_memory"]),
            _result("b", []),
        ]
        output = report_all_profiles(results, "csv")
        self.assertIn("hermes_memory,ai_memory,", output.splitlines()[0])
        # profile b has empty cells for the union groups
        row_b = output.splitlines()[2]
        self.assertIn("b,Claude,True,True,True,True,True,,,True,", row_b)

    def test_json_wraps_results(self):
        results = [_result("a", ["hermes_memory"])]
        payload = json.loads(report_all_profiles(results, "json", "a"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["profiles"], ["a"])
        self.assertEqual(payload["results"][0]["profile"], "a")

    def test_json_annotates_record_state(self):
        results = [_result("a", ["hermes_memory"])]
        payload = json.loads(report_all_profiles(results, "json", "a"))
        record = payload["results"][0]["records"][0]
        # Fully compliant -> green, injected by the single Python rule set.
        self.assertEqual(record["state"], "green")

    def test_json_annotates_state_for_unprobed_profile(self):
        result = _result("a", ["hermes_memory"])
        result["probe"] = {"error": "not probed"}
        result["records"][0]["mcp_initialize_ok"] = False
        result["records"][0]["mcp_tools_list_ok"] = False
        result["records"][0]["capabilities"] = {"hermes_memory": False}
        payload = json.loads(report_all_profiles([result], "json", "a"))
        self.assertEqual(payload["results"][0]["records"][0]["state"], "yellow")

    def test_table_and_markdown_render(self):
        results = [_result("a", ["hermes_memory"])]
        self.assertIn("跨 profile 汇总报告", report_all_profiles(results, "table"))
        self.assertIn("## 跨 profile 汇总", report_all_profiles(results, "md"))


if __name__ == "__main__":
    unittest.main()