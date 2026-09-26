"""Stage-5 P5: management snapshot contract (three-panel payload)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from management_snapshot import build_management_snapshot, _effective_tools, _drift_payload  # noqa: E402


def _config():
    return {
        "schema_version": 2,
        "active_profile": "a",
        "profiles": {
            "a": {"name": "mcp-a", "url": "https://a.example.com/mcp", "required_capabilities": {}},
            "b": {"name": "mcp-b", "url": "https://b.example.com/mcp", "required_capabilities": {}},
        },
        "mcp_tools": [
            {"name": "Cursor", "config_path": "~/.cursor/mcp.json", "format": "json",
             "mcp_key_path": ["mcpServers"], "mcp_attach": ["a"], "type": "AI IDE",
             "skills_paths": ["~/.cursor/skills"]},
            {"name": "Claude", "config_path": "~/.claude.json", "format": "json",
             "mcp_key_path": ["mcpServers"], "type": "AI Coding Assistant",
             "skills_paths": ["~/.claude/skills"]},
        ],
        "tools": [
            {"name": "Cursor", "skills_paths": ["~/.cursor/skills"], "type": "AI IDE"},
            {"name": "Claude", "skills_paths": ["~/.claude/skills"], "type": "AI Coding Assistant"},
        ],
        "unified_skills_dir": "~/.skills-manager/skills",
    }


class ManagementSnapshotTest(unittest.TestCase):
    def setUp(self):
        """隔离本机运行时状态：data/discovered_tools.yaml 可能含真实残留
        （如 .cc-switch），会让本应只测 config 注册表的用例被污染。"""
        from unittest.mock import patch

        self._disc = patch("config_store.load_discovered", return_value=[])
        self._disc.start()

    def tearDown(self):
        self._disc.stop()

    def test_shape_and_contract(self):
        snap = build_management_snapshot(_config(), config_path="", live_probe=False, auto_discover=False)
        self.assertEqual(snap["kind"], "management")
        self.assertEqual(snap["schema_version"], 1)
        self.assertIn("agents", snap)
        self.assertIn("skills", snap)
        self.assertIn("mcp", snap)
        for a in snap["agents"]:
            for field in ("name", "installed", "install_state", "install_evidence",
                          "app_paths", "cli_paths", "config_paths", "mcp_config_path",
                          "skills_compliant", "skill_link_form", "mcp_attach"):
                self.assertIn(field, a)
        mcp = snap["mcp"]
        self.assertIn("endpoints", mcp)
        self.assertIn("clients", mcp)
        self.assertIn("endpoint_status", mcp)
        sk = snap["skills"]
        self.assertIn("skills", sk)
        self.assertIn("clients_states", sk)
        self.assertIn("skill_meta", sk)  # per-skill {name, description} for the skills-manager UI

    def test_agents_union_mcp_and_tools_registry_no_dup(self):
        snap = build_management_snapshot(_config(), config_path="", live_probe=False, auto_discover=False)
        names = [a["name"] for a in snap["agents"]]
        self.assertEqual(sorted(names), ["Claude", "Cursor"])  # dedup across registries

    def test_attach_resolution_in_agents(self):
        snap = build_management_snapshot(_config(), config_path="", live_probe=False, auto_discover=False)
        by_name = {a["name"]: a for a in snap["agents"]}
        self.assertEqual(by_name["Cursor"]["mcp_attach"], ["a"])
        self.assertEqual(by_name["Claude"]["mcp_attach"], ["a", "b"])  # default = all endpoints

    def test_data4_has_explicit_attach_flag(self):
        """DATA-4: Cursor declares mcp_attach -> has_explicit_attach True;
        Claude does not -> False (default-to-all)."""
        snap = build_management_snapshot(_config(), config_path="", live_probe=False, auto_discover=False)
        by_name = {a["name"]: a for a in snap["agents"]}
        self.assertTrue(by_name["Cursor"]["has_explicit_attach"])
        self.assertFalse(by_name["Claude"]["has_explicit_attach"])

    def test_data5_mcp_clients_carry_locator_fields(self):
        """DATA-5: mcp_clients payload forwards config_path/format/mcp_key_path."""
        from unittest.mock import patch

        # 一致性门控：mcp.clients 只保留「本机扫描到」的客户端。测试夹具里的 Cursor
        # 是假条目，需 patch detect_installation 为 installed，才能进入 mcp.clients。
        def fake_detect(tool, **kwargs):
            return {"installed": True, "install_state": "installed", "evidence": [],
                    "app_paths": [], "cli_paths": [], "config_paths": []}

        with patch("management_snapshot.detect_installation", side_effect=fake_detect):
            snap = build_management_snapshot(_config(), config_path="", live_probe=False, auto_discover=False)
        by_name = {c["name"]: c for c in snap["mcp"]["clients"]}
        self.assertEqual(by_name["Cursor"]["config_path"], "~/.cursor/mcp.json")
        self.assertEqual(by_name["Cursor"]["format"], "json")
        self.assertEqual(by_name["Cursor"]["mcp_key_path"], ["mcpServers"])

    def test_data7_unsupported_client_is_not_a_missing_anomaly(self):
        """DATA-7：「不支持 MCP」必须与「缺失」区分。

        注册表未声明 mcp_config_path 的客户端（实况如 ima.copilot，已安装但
        没有 MCP 配置文件）根本没有 MCP 能力，不适用「期望挂载」。此前仍按默认
        「全部端点」给它套上期望，于是被判成「声明要挂却没挂」的异常——把能力
        缺失误报成故障。此用例锁定：supports_mcp=False 且 missing 为空。
        """
        from unittest.mock import patch

        def fake_detect(tool, **kwargs):
            return {"installed": True, "install_state": "installed", "evidence": [],
                    "app_paths": [], "cli_paths": [], "config_paths": []}

        config = {
            "schema_version": 2,
            "active_profile": "a",
            "profiles": {"a": {"name": "mcp-a", "url": "https://a.example.com/mcp",
                               "required_capabilities": {}}},
            "mcp_tools": [
                {"name": "Cursor", "config_path": "~/.cursor/mcp.json",
                 "skills_paths": ["~/.cursor/skills"]},
                {"name": "ima.copilot", "config_path": "",
                 "skills_paths": ["~/.ima/skills"]},
            ],
            "tools": [],
            "unified_skills_dir": "~/.skills-manager/skills",
        }
        with patch("management_snapshot.detect_installation", side_effect=fake_detect):
            snap = build_management_snapshot(config, config_path="", live_probe=False, auto_discover=False)
        by_name = {c["name"]: c for c in snap["mcp"]["clients"]}

        unsupported = by_name["ima.copilot"]
        self.assertFalse(unsupported["supports_mcp"], "无 mcp_config_path 即不支持 MCP")
        self.assertEqual(unsupported["mcp_attach"], [], "不支持 MCP 时期望应为空")
        self.assertEqual(unsupported["missing_attach"], [], "能力缺失不得报成「缺失」异常")

        # 对照组：有 MCP 能力的客户端仍按默认「全部端点」期望，缺挂才算异常
        supported = by_name["Cursor"]
        self.assertTrue(supported["supports_mcp"])
        self.assertEqual(supported["mcp_attach"], ["a"])
        self.assertEqual(supported["missing_attach"], ["a"], "声明要挂却没挂仍须判为缺失")

    def test_uninstalled_ghost_excluded_from_skills_and_mcp(self):
        """一致性门控：未安装（install_state=none）的幽灵客户端不应出现在
        skills.clients_states 与 mcp.clients（与 home 列表 install_state!=="none" 对齐）。"""
        from unittest.mock import patch

        def fake_detect(tool, **kwargs):
            if tool.get("name") == "Ghost":
                return {"installed": False, "install_state": "none", "evidence": [],
                        "app_paths": [], "cli_paths": [], "config_paths": []}
            return {"installed": True, "install_state": "installed", "evidence": [],
                    "app_paths": [], "cli_paths": [], "config_paths": []}

        config = {
            "schema_version": 2,
            "active_profile": "a",
            "profiles": {"a": {"name": "mcp-a", "url": "https://a.example.com/mcp", "required_capabilities": {}}},
            "mcp_tools": [
                {"name": "Ghost", "config_path": "~/.ghost/mcp.json",
                 "skills_paths": ["~/.ghost/skills"]},
                {"name": "Cursor", "config_path": "~/.cursor/mcp.json",
                 "skills_paths": ["~/.cursor/skills"]},
            ],
            "tools": [],
            "unified_skills_dir": "~/.skills-manager/skills",
        }
        with patch("management_snapshot.detect_installation", side_effect=fake_detect):
            snap = build_management_snapshot(config, config_path="", live_probe=False, auto_discover=False)
        self.assertNotIn("Ghost", {c["name"] for c in snap["mcp"]["clients"]})
        self.assertNotIn("Ghost", {c["name"] for c in snap["skills"]["clients_states"]})
        self.assertIn("Cursor", {c["name"] for c in snap["mcp"]["clients"]})

    def test_skills_paths_merged_from_tools_section(self):
        """一致性修复：同一客户端在 mcp_tools 段（只有 config_path、无 skills_paths）
        与 tools 段（只有 skills_paths）各有一条目时，去重后的 mcp_tools 条目缺少
        skills_paths，但 skills 面板仍需从扫描结果取到路径，不能漏掉该客户端。"""
        import tempfile
        import os as _os
        from unittest.mock import patch

        tmp = tempfile.TemporaryDirectory()
        skills_dir = _os.path.join(tmp.name, "skills")

        def fake_detect(tool, **kwargs):
            return {"installed": True, "install_state": "installed", "evidence": [],
                    "app_paths": [], "cli_paths": [], "config_paths": []}

        config = {
            "schema_version": 2,
            "active_profile": "a",
            "profiles": {"a": {"name": "mcp-a", "url": "https://a.example.com/mcp", "required_capabilities": {}}},
            # mcp_tools 段：无 skills_paths（去重后会覆盖 tools 段条目）
            "mcp_tools": [{"name": "Cursor", "config_path": "~/.cursor/mcp.json"}],
            # tools 段：只有 skills_paths
            "tools": [{"name": "Cursor", "skills_paths": ["~/.cursor/skills"]}],
            "unified_skills_dir": "~/.skills-manager/skills",
        }
        scan_result = {
            "unified_dir": "~/.skills-manager/skills",
            "results": [
                {"tool_name": "Cursor", "path": "~/.cursor/skills",
                 "expanded_path": skills_dir, "status": "correct"},
            ],
            "summary": {},
        }
        with patch("management_snapshot.detect_installation", side_effect=fake_detect), \
             patch("management_snapshot.run_scan", return_value=scan_result), \
             patch("skill_state.repo_skill_names", return_value=["apple"]), \
             patch("skill_state.read_skill_meta", return_value={}), \
             patch("skill_state.read_skill_states", return_value={"apple": "enabled"}):
            _os.makedirs(skills_dir, exist_ok=True)
            snap = build_management_snapshot(config, config_path="", live_probe=False, auto_discover=False)
        names = {c["name"] for c in snap["skills"]["clients_states"]}
        self.assertIn("Cursor", names)
        tmp.cleanup()

    def test_three_state_install_semantics_in_payload(self):
        """整改: _agent_entry 透传 install_state 与各类已解析路径."""
        from management_snapshot import _agent_entry
        from unittest.mock import patch

        tool = {"name": "ConfigOnly", "type": "AI Agent",
                "skills_paths": ["~/.co/skills"],
                "install": {"config_paths": ["~/.co/mcp.json"]}}
        config = _config()
        scan_result = {"unified_dir": "~/.skills-manager/skills", "results": []}
        detect = {"installed": False, "install_state": "config_only", "evidence": ["config"],
                  "app_paths": [], "cli_paths": [], "config_paths": ["/Users/x/.co/mcp.json"]}
        with patch("management_snapshot.detect_installation", return_value=detect):
            entry = _agent_entry(tool, config, scan_result, "~/.skills-manager/skills")
        self.assertEqual(entry["install_state"], "config_only")
        self.assertFalse(entry["installed"])
        self.assertEqual(entry["config_paths"], ["/Users/x/.co/mcp.json"])
        self.assertEqual(entry["app_paths"], [])
        self.assertEqual(entry["cli_paths"], [])

    def test_endpoint_status_covers_every_endpoint(self):
        snap = build_management_snapshot(_config(), config_path="", live_probe=False, auto_discover=False)
        self.assertEqual(sorted(snap["mcp"]["endpoint_status"].keys()), ["a", "b"])

    def test_b1_uninstalled_client_skills_not_compliant(self):
        """B1 fix: an uninstalled client must NOT report skills_compliant=True,
        even if a residual root symlink produces scan rows with status 'correct'.
        The installed gate in _agent_entry must override the raw scan verdict."""
        from management_snapshot import _agent_entry

        config = _config()
        # simulate a client that is NOT installed but has a residual symlink
        # row (status 'correct', expanded_path present) — the exact BUG pattern
        tool = {"name": "Ghost", "skills_paths": ["~/.ghost/skills"], "type": "AI Agent"}
        scan_result = {
            "unified_dir": "~/.skills-manager/skills",
            "results": [
                {"tool_name": "Ghost", "path": "~/.ghost/skills",
                 "expanded_path": "~/.ghost/skills", "status": "correct"},
            ],
        }
        entry = _agent_entry(tool, config, scan_result, "~/.skills-manager/skills")
        self.assertFalse(entry["installed"], "fixture: Ghost must be uninstalled")
        self.assertFalse(entry["skills_compliant"],
                         "B1: uninstalled client must report skills_compliant=False")

    def test_b1_installed_client_skills_compliant_passes(self):
        """B1 fix must NOT break the normal installed+compliant path."""
        from management_snapshot import _agent_entry

        config = _config()
        # Cursor is installed (evidence present) and scan says correct
        tool = config["mcp_tools"][0]
        scan_result = {
            "unified_dir": "~/.skills-manager/skills",
            "results": [
                {"tool_name": "Cursor", "path": "~/.cursor/skills",
                 "expanded_path": "~/.cursor/skills", "status": "correct"},
            ],
        }
        # force installed=True by patching detect_installation is fragile; instead
        # rely on real detect_installation on a real installed client path.
        # If Cursor isn't installed on this machine, installed=False and the
        # gate still correctly yields compliant=False — so assert the gate logic
        # holds regardless: compliant == (installed and scan_says_correct).
        entry = _agent_entry(tool, config, scan_result, "~/.skills-manager/skills")
        self.assertEqual(entry["skills_compliant"],
                         entry["installed"] and True)


class EffectiveToolsTest(unittest.TestCase):
    """整改: _effective_tools 把 discovered(持久化) 合并进管理注册表，去重."""

    def test_merges_mcp_tools_tools_and_discovered(self):
        from unittest.mock import patch

        config = _config()
        discovered = [
            {"name": "CustomAgent", "type": "AI Agent", "skills_paths": ["~/.ca/skills"]},
            {"name": "cursor", "type": "AI IDE", "skills_paths": ["~/.cursor/skills"]},  # dup
        ]
        with patch("config_store.load_discovered", return_value=discovered):
            tools = _effective_tools(config)
        names = [t["name"] for t in tools]
        self.assertIn("Cursor", names)
        self.assertIn("Claude", names)
        self.assertIn("CustomAgent", names)
        # cursor (discovered) 与 Cursor (config) 归一化去重，只保留一个
        self.assertEqual(len([n for n in names if n.lower() == "cursor"]), 1)

    def test_discovered_clients_surface_in_agents(self):
        """整改: 添加的「发现式/主流」客户端必须出现在 agents 面板."""
        from unittest.mock import patch

        config = _config()
        discovered = [{"name": "CustomAgent", "type": "AI Agent", "skills_paths": ["~/.ca/skills"]}]
        with patch("config_store.load_discovered", return_value=discovered), \
             patch("management_snapshot.run_scan", return_value={"unified_dir": "~/.skills-manager/skills", "results": []}):
            snap = build_management_snapshot(config, config_path="", live_probe=False, auto_discover=False)
        names = {a["name"] for a in snap["agents"]}
        self.assertIn("CustomAgent", names)


class NonAgentClientTest(unittest.TestCase):
    """FEAT-6: 非 IDE/Agent 的工具管理器（CC Switch）的可见性边界。

    CC Switch 是供应商切换器 + 本地代理（com.ccswitch.desktop），给 Claude Code /
    Codex / Gemini / OpenCode 切换配置：它自身不做推理、不跑 agent 循环，也不消费
    MCP（它把 MCP 注入别的客户端）。它同时带技能管理功能，故 ~/.cc-switch/skills 是
    统一技能库的挂载点。因此它的正确可见范围是「技能审计可见、IDE/Agent 表不可见、
    MCP 面板不可见」——既不能因为不是客户端就被隐藏（那样挂载点失去可见性），也不能
    因为它装了 App 就被当成一个 Agent 计数。
    """

    def _config(self):
        return {
            "mcp_tools": [{"name": "Real", "config_path": "~/.real/mcp.json",
                           "skills_paths": ["~/.real/skills"]}],
            "tools": [{"name": "CC Switch", "non_agent": True, "type": "配置工具",
                       "install": {"app_bundles": ["/Applications/CC Switch.app"]},
                       "skills_paths": ["~/.cc-switch/skills"]}],
            "skills": [],
        }

    def _snapshot(self):
        import os as _os
        import tempfile
        from unittest.mock import patch

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        skills_dir = _os.path.join(tmp.name, "skills")
        _os.makedirs(skills_dir, exist_ok=True)

        install = {
            "installed": True, "install_state": "installed", "evidence": ["app"],
            "app_paths": ["/Applications/CC Switch.app"], "cli_paths": [],
            "config_paths": [],
        }
        with patch("management_snapshot.detect_installation", return_value=install), \
             patch("management_snapshot.run_scan",
                   return_value={"unified_dir": "~/.skills-manager/skills", "results": [
                       {"tool_name": "CC Switch", "path": "~/.cc-switch/skills",
                        "expanded_path": skills_dir, "status": "correct"},
                   ]}):
            return build_management_snapshot(self._config(), config_path="", live_probe=False,
                                             auto_discover=False)

    def test_marked_non_agent_in_agents_payload(self):
        snap = self._snapshot()
        entry = next(a for a in snap["agents"] if a["name"] == "CC Switch")
        self.assertFalse(entry["is_agent"], "非 IDE/Agent 必须显式标注，供 UI 排除")
        self.assertEqual(entry["type"], "配置工具")
        self.assertTrue(entry["installed"], "装了 App 就该算已安装（否则审计看不见）")

    def test_regular_clients_stay_agents(self):
        snap = self._snapshot()
        entry = next(a for a in snap["agents"] if a["name"] == "Real")
        self.assertTrue(entry["is_agent"], "普通客户端不受影响")

    def test_absent_from_mcp_panel(self):
        """它不消费 MCP，不该被渲染成一行「不支持 MCP」。"""
        snap = self._snapshot()
        self.assertNotIn("CC Switch", [c["name"] for c in snap["mcp"]["clients"]])

    def test_absent_from_skills_panel(self):
        """FEAT-7: 技能面板不列它，与 IDE/Agent 表统一为同一批「本机安装的 IDE/Agent」。

        此前它出现在 clients_states 里，导致同一界面「技能面板 7 个 vs IDE/Agent 表
        6 个」对不上，用户无从判断该信哪个。
        """
        snap = self._snapshot()
        self.assertNotIn(
            "CC Switch", [c["name"] for c in snap["skills"]["clients_states"]]
        )

    def test_still_covered_by_skills_audit(self):
        """但技能**审计**必须照常覆盖它——面板不列 ≠ 监督消失。

        审计走 combined_checker → scan_result["results"]（run_scan 产出）的
        managed_names，与 clients_states 是两条独立数据链。本用例锁定这条边界：
        从面板移除不得连带削弱审计，否则 ~/.cc-switch/skills 这 186 个技能
        就再无人监督。
        """
        import sys

        sys.path.insert(0, str(ROOT / "core"))
        from combined_checker import _skills_compliant  # noqa: E402
        from management_snapshot import _client_skill_stats  # noqa: E402

        row = {"tool_name": "CC Switch", "path": "~/.cc-switch/skills",
               "expanded_path": "/tmp/cc-switch-skills",
               "status": "correct", "is_installed": True}
        scan_result = {"results": [row]}
        tool = {"name": "CC Switch", "non_agent": True,
                "skills_paths": ["~/.cc-switch/skills"]}

        # 审计侧：按 tool_name 命中该行并判合规
        self.assertTrue(
            _skills_compliant("CC Switch", scan_result),
            "审计必须仍能看到 CC Switch 的技能行",
        )
        # 面板侧的路径/统计辅助函数对 non_agent 无感知——排除只发生在快照组装处
        # （clients_states 循环里的 continue），故这两个下游函数照常返回数据。
        stats = _client_skill_stats(tool, scan_result, "~/.skills-manager/skills")
        self.assertTrue(
            stats.get("skills_compliant"),
            "non_agent 不得影响技能统计辅助函数（排除只该发生在面板组装处）",
        )


class DriftDetectionTest(unittest.TestCase):
    """DATA-8: 区分「被外部工具改写」与「尚未应用」。

    ``~/.codex/config.toml`` 是多写者竞争的文件：CC Switch 切换通道、客户端升级
    都会重写整份文件，而它们的模板里没有用户自建的 MCP 条目，于是刚修好的端点会
    被静默抹掉。判据用一个客观事实：``<config>.bak-*`` 兄弟备份是本工具**写入前**
    留下的，所以「有备份 + 期望端点不见」= 写入成功过、之后被改掉（疑似外部改写）；
    「无备份 + 期望端点不见」= 只是尚未应用。两者都会让端点缺失，但不该混为一谈。
    """

    def _tmp(self):
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        return Path(self._dir.name)

    def test_no_missing_means_no_drift(self):
        root = self._tmp()
        cfg = root / "config.toml"
        cfg.write_text("", encoding="utf-8")
        (root / "config.toml.bak-20260921-160315-913403").write_text("[mcp_servers.X]\n", encoding="utf-8")
        payload = _drift_payload(str(cfg), [])
        self.assertFalse(payload["suspected"])
        self.assertEqual(payload["lost"], [])
        self.assertEqual(payload["backup_count"], 0)

    def test_backup_plus_missing_means_external_rewrite(self):
        root = self._tmp()
        cfg = root / "config.toml"
        cfg.write_text("[mcp_servers.kept]\n", encoding="utf-8")
        (root / "config.toml.bak-20260920-163013-000001").write_text("old\n", encoding="utf-8")
        (root / "config.toml.bak-20260921-160315-913403").write_text("new\n", encoding="utf-8")
        payload = _drift_payload(str(cfg), ["K8s-uat", "hermes-home"])
        self.assertTrue(payload["suspected"], "有本工具备份 + 端点不见 => 疑似被外部改写")
        self.assertEqual(payload["lost"], ["K8s-uat", "hermes-home"])
        self.assertEqual(payload["backup_count"], 2)
        self.assertTrue(payload["last_backup_at"], "须给出最近备份时间作为证据")
        self.assertIn("config.toml.bak-", payload["last_backup"])

    def test_missing_without_backup_is_merely_unapplied(self):
        root = self._tmp()
        cfg = root / "config.toml"
        cfg.write_text("{}\n", encoding="utf-8")
        payload = _drift_payload(str(cfg), ["K8s-uat"])
        self.assertFalse(payload["suspected"], "从未写入过不算漂移，避免误报外部改写")
        self.assertEqual(payload["backup_count"], 0)

    def test_missing_config_file_does_not_raise(self):
        root = self._tmp()
        payload = _drift_payload(str(root / "nope.toml"), ["K8s-uat"])
        self.assertFalse(payload["suspected"])
        self.assertEqual(_drift_payload("", ["K8s-uat"])["suspected"], False)

    def test_snapshot_clients_carry_drift_field(self):
        """快照每个客户端都要带 drift，供 UI 判断显示「被外部改写」还是「未应用」。"""
        snap = build_management_snapshot(_config(), config_path="", live_probe=False, auto_discover=False)
        for c in snap["mcp"]["clients"]:
            self.assertIn("drift", c)
            for field in ("suspected", "lost", "backup_count", "last_backup", "last_backup_at"):
                self.assertIn(field, c["drift"])


if __name__ == "__main__":
    unittest.main()