"""Stage-4 data-contract tests (design doc §10).

``check_agents`` / ``report_all_profiles`` output must carry the L5 fields
(``skill_states`` / ``skill_state_drift`` / ``skill_link_form``) with correct
types, additively (old fields untouched), and ``result_ok`` must stay unchanged
by default while ``strict_skill_state`` adds the drift requirement.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from combined_checker import check_agents, result_ok  # noqa: E402
from multi_profile_reporter import report_all_profiles  # noqa: E402


def build_env(tmp, drift=True):
    """Two per-skill clients; when drift=True, client B disables ``tdai``."""
    repo = Path(tmp) / "repo"
    (repo / "memory-basic").mkdir(parents=True)
    (repo / "tdai").mkdir()

    client_a = Path(tmp) / "a" / "skills"
    client_a.mkdir(parents=True)
    os.symlink(repo / "memory-basic", client_a / "memory-basic", target_is_directory=True)
    os.symlink(repo / "tdai", client_a / "tdai", target_is_directory=True)

    client_b = Path(tmp) / "b" / "skills"
    client_b.mkdir(parents=True)
    os.symlink(repo / "memory-basic", client_b / "memory-basic", target_is_directory=True)
    if not drift:
        os.symlink(repo / "tdai", client_b / "tdai", target_is_directory=True)

    config_a = Path(tmp) / "a-config.json"
    config_b = Path(tmp) / "b-config.json"
    config_a.write_text("{}", encoding="utf-8")
    config_b.write_text("{}", encoding="utf-8")

    # 三态语义整改: 仅 config 不再算 installed；给夹具加真实存在的 app bundle
    # 目录作为安装证据，使 ClientA/ClientB 仍作为「已安装」参与 drift 判定。
    app_a = Path(tmp) / "ClientA.app"
    app_b = Path(tmp) / "ClientB.app"
    app_a.mkdir()
    app_b.mkdir()

    config = {
        "unified_mcp": {"name": "hermes", "url": "https://example.internal/mcp"},
        "mcp_tools": [
            {
                "name": "ClientA",
                "config_path": str(Path(tmp) / "a-mcp.json"),
                "format": "json",
                "mcp_key_path": ["mcpServers"],
                "install": {"app_bundles": [str(app_a)], "config_paths": [str(config_a)]},
            },
            {
                "name": "ClientB",
                "config_path": str(Path(tmp) / "b-mcp.json"),
                "format": "json",
                "mcp_key_path": ["mcpServers"],
                "install": {"app_bundles": [str(app_b)], "config_paths": [str(config_b)]},
            },
        ],
    }
    scan_result = {
        "unified_dir": str(repo),
        "results": [
            {
                "tool_name": "ClientA",
                "path": str(client_a),
                "expanded_path": str(client_a),
                "status": "correct",
                "is_installed": True,
            },
            {
                "tool_name": "ClientB",
                "path": str(client_b),
                "expanded_path": str(client_b),
                "status": "correct",
                "is_installed": True,
            },
        ],
    }
    return config, scan_result, repo


class CheckAgentsSkillFieldsTest(unittest.TestCase):
    def test_records_carry_l5_fields_with_correct_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, scan_result, _ = build_env(tmp)
            result = check_agents(config, scan_result, live_probe=False)
            for record in result["records"]:
                self.assertIsInstance(record["skill_states"], dict)
                self.assertIsInstance(record["skills_enabled_count"], int)
                self.assertIsInstance(record["skills_total"], int)
                self.assertIn(record["skill_link_form"], {"per_skill", "root", "mixed"})
                # 阶段四 §4.2（评审 DATA-2 补录）：native_disabled_skills 属契约字段，
                # 必须存在且为技能名列表（无原生禁用时为空列表）。
                self.assertIsInstance(record["native_disabled_skills"], list)
                for name in record["native_disabled_skills"]:
                    self.assertIsInstance(name, str)

    def test_per_skill_states_reflect_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, scan_result, _ = build_env(tmp, drift=True)
            result = check_agents(config, scan_result, live_probe=False)
            by_name = {r["name"]: r for r in result["records"]}
            self.assertEqual(
                by_name["ClientA"]["skill_states"],
                {"memory-basic": "enabled", "tdai": "enabled"},
            )
            self.assertEqual(by_name["ClientA"]["skills_enabled_count"], 2)
            self.assertEqual(by_name["ClientA"]["skills_total"], 2)
            self.assertEqual(by_name["ClientA"]["skill_link_form"], "per_skill")
            self.assertEqual(
                by_name["ClientB"]["skill_states"],
                {"memory-basic": "enabled", "tdai": "disabled"},
            )
            self.assertEqual(by_name["ClientB"]["skills_enabled_count"], 1)

    def test_result_carries_drift_and_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, scan_result, _ = build_env(tmp, drift=True)
            result = check_agents(config, scan_result, live_probe=False)
            self.assertIsInstance(result["skill_state_drift"], list)
            self.assertFalse(result["summary"]["skill_state_consistent"])
            skills = [d["skill"] for d in result["skill_state_drift"]]
            self.assertEqual(skills, ["tdai"])
            self.assertEqual(result["skill_state_drift"][0]["drift_clients"], ["ClientB"])

    def test_no_drift_when_states_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, scan_result, _ = build_env(tmp, drift=False)
            result = check_agents(config, scan_result, live_probe=False)
            self.assertEqual(result["skill_state_drift"], [])
            self.assertTrue(result["summary"]["skill_state_consistent"])

    def test_client_without_skills_registry_entry_gets_empty_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, scan_result, _ = build_env(tmp, drift=False)
            config["mcp_tools"].append({
                "name": "NoSkillsClient",
                "config_path": str(Path(tmp) / "c-mcp.json"),
                "format": "json",
                "mcp_key_path": ["mcpServers"],
                "install": {"config_paths": [str(Path(tmp) / "c-config.json")]},
            })
            (Path(tmp) / "c-config.json").write_text("{}", encoding="utf-8")
            result = check_agents(config, scan_result, live_probe=False)
            record = next(r for r in result["records"] if r["name"] == "NoSkillsClient")
            self.assertEqual(record["skill_states"], {})
            self.assertEqual(record["skills_enabled_count"], 0)
            self.assertEqual(record["skills_total"], 0)
            # drift must not involve the skills-less client
            self.assertTrue(result["summary"]["skill_state_consistent"])


class ResultOkStrictTest(unittest.TestCase):
    def _compliant(self, skill_states_a, skill_states_b):
        rec_base = {
            "installed": True,
            "skills_compliant": True,
            "mcp_configured": True,
            "mcp_initialize_ok": True,
            "mcp_tools_list_ok": True,
            "hooks_configured": True,
            "capabilities": {},
            "legacy_channels": [],
        }
        return {
            "probe": {"error": ""},
            "records": [
                {"name": "A", **rec_base, "skill_states": skill_states_a},
                {"name": "B", **rec_base, "skill_states": skill_states_b},
            ],
            "unmanaged": [],
            "summary": {},
        }

    def test_default_result_ok_ignores_drift(self):
        result = self._compliant({"s": "enabled"}, {"s": "disabled"})
        self.assertTrue(result_ok(result))

    def test_strict_result_ok_fails_on_drift(self):
        result = self._compliant({"s": "enabled"}, {"s": "disabled"})
        self.assertFalse(result_ok(result, strict_skill_state=True))

    def test_strict_result_ok_passes_when_consistent(self):
        result = self._compliant({"s": "enabled"}, {"s": "enabled"})
        self.assertTrue(result_ok(result, strict_skill_state=True))


class MultiProfileJsonContractTest(unittest.TestCase):
    def test_json_snapshot_preserves_l5_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, scan_result, _ = build_env(tmp, drift=True)
            result = check_agents(config, scan_result, live_probe=False)
            payload = report_all_profiles(
                [{"profile": "generic-http", "ok": False, **result}],
                fmt="json",
                active_profile="generic-http",
            )
            snapshot = json.loads(payload)
            first = snapshot["results"][0]
            self.assertIn("skill_state_drift", first)
            self.assertIn("skill_state_consistent", first["summary"])
            for record in first["records"]:
                self.assertIn("skill_states", record)
                self.assertIn("skill_link_form", record)


if __name__ == "__main__":
    unittest.main()
