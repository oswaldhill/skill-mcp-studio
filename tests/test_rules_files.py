"""各客户端约束文件（AGENTS.md / CLAUDE.md 等）的发现与读写门禁断言。

背景（2026-11-09 用户需求）：「根据每个应用不同的主要约束文件，对每个 Agent
的约束进行管理」。不同客户端的规则文件不同——Claude Code 用 ``CLAUDE.md``、
Codex 用 ``AGENTS.md``、Cursor 用 ``.cursor/rules/`` 目录……

这批断言守 5 类事实：

1. 只认注册表里显式声明的 ``rules_paths``，不猜路径；
2. 发现口径：文件看行数/大小/mtime，目录看文件数，缺失标 ``exists=False``；
3. 读取有上限（``MAX_PREVIEW_BYTES``），超出标 ``truncated``；
4. 写入：先备份 → 原子写 → 回读校验；目录拒绝；新建时 backup 为空；
5. CLI 端到端（``--list-rules`` / ``--read-rules``）与 GUI 契约
   （面板、按钮、命令、Rust 白名单、DESIGN.md 登记）。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import rules_files as rf  # noqa: E402


def _tool(name, *paths, aliases=None):
    return {"name": name, "type": "AI Agent", "rules_paths": list(paths),
            "aliases": aliases or []}


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_file_and_missing_and_dir(self):
        f = self.root / "AGENTS.md"
        f.write_text("# rules\nline2\n", encoding="utf-8")
        d = self.root / "rules"
        d.mkdir()
        (d / "a.mdc").write_text("x", encoding="utf-8")
        (d / "b.mdc").write_text("y", encoding="utf-8")

        registry = [
            _tool("Codex", str(f)),
            _tool("Claude Code", str(self.root / "nope.md")),
            _tool("Cursor", str(d)),
            {"name": "NoRules", "type": "AI IDE"},  # 未声明 → 不出现
        ]
        out = rf.discover(registry)

        self.assertEqual(len(out["rows"]), 3, "未声明 rules_paths 的客户端不出现")
        by = {r["name"]: r["paths"][0] for r in out["rows"]}
        self.assertEqual(by["Codex"]["kind"], "file")
        self.assertEqual(by["Codex"]["lines"], 2)
        self.assertGreater(by["Codex"]["size"], 0)
        self.assertTrue(by["Codex"]["mtime"])
        self.assertFalse(by["Claude Code"]["exists"])
        self.assertEqual(by["Cursor"]["kind"], "dir")
        self.assertEqual(by["Cursor"]["files"], 2)
        self.assertEqual(out["summary"]["declared"], 3)
        self.assertEqual(out["summary"]["configured"], 2)

    def test_registry_paths_are_authoritative(self):
        """注册表里没声明就不猜：discover 只遍历声明的客户端。"""
        out = rf.discover([{"name": "X", "type": "AI IDE"}])
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["summary"]["configured"], 0)


class ReadWriteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.file = self.root / "AGENTS.md"
        self.registry = [_tool("Codex", str(self.file), aliases=["codex"])]

    def test_read_missing_is_ok_with_flag(self):
        res = rf.read_rules("Codex", registry=self.registry)
        self.assertTrue(res["ok"])
        self.assertEqual(res["kind"], "missing")
        self.assertEqual(res["content"], "")

    def test_read_truncates_oversize(self):
        self.file.write_text("a" * (rf.MAX_PREVIEW_BYTES + 10), encoding="utf-8")
        res = rf.read_rules("Codex", registry=self.registry)
        self.assertTrue(res["truncated"])
        self.assertEqual(len(res["content"]), rf.MAX_PREVIEW_BYTES)

    def test_read_dir_lists_files(self):
        d = self.root / "rules"
        d.mkdir()
        (d / "a.mdc").write_text("x", encoding="utf-8")
        res = rf.read_rules("Cursor", registry=[_tool("Cursor", str(d))])
        self.assertEqual(res["kind"], "dir")
        self.assertEqual(res["files"], ["a.mdc"])

    def test_write_creates_and_backs_up(self):
        res = rf.write_rules("codex", "# v1\n", registry=self.registry)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "# v1\n")
        self.assertEqual(res["backup"], "", "新建时没有旧文件可备份")

        res2 = rf.write_rules("Codex", "# v2\n", registry=self.registry)
        self.assertTrue(res2["ok"])
        self.assertTrue(Path(res2["backup"]).is_file(), "覆盖前必须备份")
        self.assertEqual(Path(res2["backup"]).read_text(encoding="utf-8"), "# v1\n")
        self.assertEqual(self.file.read_text(encoding="utf-8"), "# v2\n")

    def test_write_rejects_dir(self):
        d = self.root / "rules"
        d.mkdir()
        res = rf.write_rules("Cursor", "x", registry=[_tool("Cursor", str(d))])
        self.assertFalse(res["ok"])
        self.assertIn("目录", res["reason"])

    def test_write_unknown_client(self):
        res = rf.write_rules("Nope", "x", registry=self.registry)
        self.assertFalse(res["ok"])
        self.assertIn("未知客户端", res["reason"])

    def test_read_unknown_client(self):
        res = rf.read_rules("Nope", registry=self.registry)
        self.assertFalse(res["ok"])


class RulesCliTest(unittest.TestCase):
    """端到端：GUI 直接 JSON.parse 这两条命令的 stdout。"""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )

    def test_list_rules_json(self):
        proc = self._run("--list-rules", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("rows", payload)
        self.assertIn("summary", payload)
        names = {r["name"] for r in payload["rows"]}
        # 注册表里至少这几家声明了约束文件
        for expected in ("Codex", "Claude Code", "DeepSeek Harness"):
            self.assertIn(expected, names)

    def test_read_rules_json(self):
        proc = self._run("--read-rules", "codex", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["client"], "Codex")


class RulesGuiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")
        cls.lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        cls.design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")

    def test_column_and_settings_rows(self):
        """v0.37.9：约束状态合并进客户端主表，逐 Agent 配置行收进设置页。

        用户原话：「这个约束文件应该合并到上面的列表中，而不是单独展示。
        然后下面每个 Agent 的具体配置，应该在设置里单独有一行。」
        """
        self.assertIn("约束<span class=\"th-help\"", self.dashboard,
                      "IDE/Agent 主表缺「约束」列")
        self.assertIn("rulesCell", self.dashboard, "缺约束列渲染逻辑")
        self.assertNotIn('id="rules-panel"', self.dashboard,
                         "独立约束面板应已移除（改为合并进主表）")
        # v0.38.0：约束摘要合并进 Agent 卡片 / 列表行，不再单独开卡。
        # 断言要精确到「函数定义 + 两处调用」：只查子串的话，
        # 把函数改名成 _agentRulesSummaryXxx 仍会命中（反向验证实测过）。
        self.assertIn("function _agentRulesSummary(t) {", self.dashboard,
                      "缺 Agent 卡片/列表的约束摘要函数")
        self.assertGreaterEqual(self.dashboard.count("${_agentRulesSummary(t)}"), 2,
                                "约束摘要必须同时出现在卡片与列表视图里")
        self.assertNotIn('id="settings-rules-card"', self.dashboard,
                         "独立「约束文件」卡片应已移除（合并进 Agent 卡片/列表）")
        self.assertNotIn("renderSettingsRules", self.dashboard,
                         "独立卡片的渲染函数应已移除")
        self.assertIn('data-action="view-rules"', self.dashboard, "缺「查看」入口")
        # v0.38.2 用户定案：「上面好像没有按钮，那么这个『查看』也不应该有按钮，
        # 应该点击文字就可以展示」——约束行用可点路径文字，不再有按钮。
        self.assertIn("rules-path-btn", self.dashboard,
                      "约束行应使用可点路径文字（.rules-path-btn）")
        # v0.38.3：约束行并入路径区（RULES 行），不再挂在能力摘要区
        self.assertIn('data-k="rules"', self.dashboard,
                      "约束行应并入 .ac-paths（RULES 行），与 APP/CLI/CONFIG 同构")
        # 只读预览：不再有编辑器 textarea
        self.assertIn("rules-preview", self.dashboard, "应有只读预览区（.rules-preview）")
        # v0.39.2 用户要求：路径字段要能「浏览」选文件，不能只手输
        self.assertIn("async function pickPath(kind, current)", self.dashboard,
                      "应有系统文件/目录选择器封装")
        self.assertIn("__TAURI__.dialog", self.dashboard,
                      "浏览必须走 Tauri dialog 插件（不是浏览器 input[type=file]）")
        self.assertIn("pf-browse", self.dashboard, "多值路径行应有「浏览」按钮")
        # v0.39.4 用户：选择器应定位到当前值所在目录，而不是每次都落 Documents
        self.assertIn("async function _pickerStartDir(kind, current)", self.dashboard,
                      "应按当前值推断选择器的起始目录")
        self.assertIn("defaultPath", self.dashboard,
                      "必须把推断出的目录传给 dialog.open 的 defaultPath")
        self.assertIn("core.invoke(\"home_dir\")", self.dashboard,
                      "~ 前缀要用 Rust 的 home_dir 展开，前端拿不到 HOME")
        self.assertIn("as-skills-pick", self.dashboard, "单值字段（Skills 目录）应有「浏览」")
        # v0.39.3 用户：「CLI 的命令也是需要的」+ 整页优化
        self.assertIn('renderPathFields("cli", commands, "command-name", "exec")', self.dashboard,
                      "CLI 命令行也要有「浏览」（选可执行文件后取文件名）")
        self.assertIn("agent-settings-hint", self.dashboard,
                      "每个路径组应有说明文字（placeholder 一输入就消失）")
        self.assertIn("path-field-add", self.dashboard,
                      "「+ 添加路径」应为轻量文字按钮")
        self.assertIn('const rows = arr.length ? arr : [""]', self.dashboard,
                      "空数组也要渲染一行空输入，否则整块像漏了字段")
        # v0.38.9 用户反馈「显示不全」：长路径缩写固定前缀，完整路径留在 title
        self.assertIn("function _shortPath", self.dashboard, "应有路径缩写函数")
        self.assertIn('"~/Library/…/"', self.dashboard,
                      "应把 ~/Library/Application Support/ 缩写为 ~/Library/…/")
        self.assertIn("escapeHtml(_shortPath(p))", self.dashboard,
                      "路径胶囊必须经过 _shortPath")
        self.assertIn("escapeHtml(_shortPath(p.path))", self.dashboard,
                      "RULES 行路径必须经过 _shortPath")
        self.assertNotIn("rules-editor", self.dashboard,
                         "不应再有编辑器 textarea（只读预览）")
        self.assertNotIn("rules-view-btn", self.dashboard,
                         "约束行不应再有独立的「查看」按钮")
        self.assertIn("function loadRules", self.dashboard)
        self.assertIn("function openRulesModal", self.dashboard)

    def test_commands_are_wired(self):
        self.assertIn('"--list-rules"', self.dashboard)
        self.assertIn('"--read-rules"', self.dashboard)
        # v0.38.3：展示只读，GUI 不再调用 --write-rules（用户定案
        # 「展示部分只需要只读就好了，在这里不需要提供直接修改文件的功能」）
        self.assertNotIn('"--write-rules"', self.dashboard,
                         "GUI 不应再调用写接口（只读预览）")

    def test_rust_whitelist(self):
        for flag in ("--list-rules", "--read-rules", "--write-rules",
                     "--rules-file", "--rules-content", "--rules-index"):
            self.assertIn(f'"{flag}"', self.lib_rs,
                          f"Rust run_cli 白名单缺少 {flag}")

    def test_design_spec_registers_panel(self):
        self.assertIn("约束文件", self.design,
                      "docs/DESIGN.md 未登记约束文件面板")


if __name__ == "__main__":
    unittest.main()
