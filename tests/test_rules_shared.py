"""共享约束块测试（v0.40.0）。

用户需求：「配置一个需要在所有 Agent 中增加的约束内容，通过同步管理检查每一个
Agent 是否都拥有它；如果没有，可以强制更新进去」。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import rules_shared as rs  # noqa: E402


class MarkBlockTest(unittest.TestCase):
    def test_block_wraps_content(self):
        block = rs.block_for("hello")
        self.assertIn(rs.BEGIN, block)
        self.assertIn(rs.END, block)
        self.assertIn("hello", block)

    def test_extract_roundtrip(self):
        self.assertEqual(rs.extract(rs.block_for("abc")), "abc")
        self.assertIsNone(rs.extract("no block here"))

    def test_extract_unterminated_returns_none(self):
        self.assertIsNone(rs.extract(rs.BEGIN + "\nbroken"))

    def test_apply_appends_when_absent(self):
        out = rs.apply("# mine\n", rs.block_for("x"))
        self.assertTrue(out.startswith("# mine"))
        self.assertIn(rs.BEGIN, out)
        self.assertEqual(rs.extract(out), "x")

    def test_apply_is_idempotent(self):
        block = rs.block_for("x")
        once = rs.apply("# mine\n", block)
        twice = rs.apply(once, block)
        self.assertEqual(once, twice)

    def test_apply_replaces_only_block(self):
        block = rs.block_for("x")
        doc = "# 前\n\n" + block + "\n# 后\n"
        out = rs.apply(doc, rs.block_for("y"))
        self.assertIn("# 前", out)
        self.assertIn("# 后", out)
        self.assertEqual(rs.extract(out), "y")

    def test_apply_keeps_content_after_block(self):
        """块后面还有用户内容时，替换不能把它吃掉（回归：lstrip 剪掉后要补回换行）。"""
        block = rs.block_for("x")
        doc = block + "\n- 块后的规则\n"
        out = rs.apply(doc, rs.block_for("y"))
        self.assertIn("- 块后的规则", out)
        self.assertEqual(rs.extract(out), "y")


class PathStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = Path(self.tmp) / "AGENTS.md"

    def test_missing_file(self):
        self.assertEqual(rs._path_state(str(self.file), "x")["state"], "missing")

    def test_absent_block(self):
        self.file.write_text("# mine\n", encoding="utf-8")
        self.assertEqual(rs._path_state(str(self.file), "x")["state"], "absent")

    def test_stale_vs_current(self):
        self.file.write_text(rs.block_for("old"), encoding="utf-8")
        self.assertEqual(rs._path_state(str(self.file), "new")["state"], "stale")
        self.assertEqual(rs._path_state(str(self.file), "old")["state"], "current")

    def test_dir_is_skipped(self):
        d = Path(self.tmp) / "rules"
        d.mkdir()
        self.assertEqual(rs._path_state(str(d), "x")["state"], "dir")


class ApplyClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = Path(self.tmp) / "AGENTS.md"
        self.registry = [{"name": "T", "type": "AI Agent", "rules_paths": [str(self.file)]}]

    def test_creates_missing_file(self):
        res = rs.apply_client("T", "# 共享\n", registry=self.registry)
        self.assertTrue(res["ok"])
        self.assertTrue(self.file.is_file())
        self.assertEqual(rs.extract(self.file.read_text(encoding="utf-8")), "# 共享")

    def test_preserves_user_content(self):
        self.file.write_text("# 我的规则\n\n- 不要删文件\n", encoding="utf-8")
        rs.apply_client("T", "# 共享\n", registry=self.registry)
        after = self.file.read_text(encoding="utf-8")
        self.assertIn("不要删文件", after)
        self.assertIn("# 共享", after)

    def test_idempotent_no_change(self):
        rs.apply_client("T", "# 共享\n", registry=self.registry)
        res = rs.apply_client("T", "# 共享\n", registry=self.registry)
        self.assertEqual(res["changed"], 0)

    def test_dry_run_does_not_write(self):
        res = rs.apply_client("T", "# 共享\n", registry=self.registry, dry_run=True)
        self.assertTrue(res["ok"])
        self.assertFalse(self.file.exists())

    def test_empty_content_rejected(self):
        self.assertFalse(rs.apply_client("T", "  ", registry=self.registry)["ok"])

    def test_unknown_client(self):
        self.assertFalse(rs.apply_client("Nope", "x", registry=self.registry)["ok"])

    def test_audit_reports_states(self):
        self.file.write_text("# mine\n", encoding="utf-8")
        r = rs.audit("# shared\n", registry=self.registry)
        self.assertEqual(r["rows"][0]["state"], "absent")
        rs.apply_client("T", "# shared\n", registry=self.registry)
        r = rs.audit("# shared\n", registry=self.registry)
        self.assertEqual(r["rows"][0]["state"], "current")
        r = rs.audit("# changed\n", registry=self.registry)
        self.assertEqual(r["rows"][0]["state"], "stale")


class ClientToggleTest(unittest.TestCase):
    """逐 Agent 参与开关（v0.40.2 用户要求）。

    用户：「这里只是设置是否检查同步以及是否需要同步进入各个 Agent」——
    卡片职责收敛成两个开关位：参不参与检查、允不允许写进去。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings = Path(self.tmp) / "shared_rules_settings.json"
        self.file = Path(self.tmp) / "AGENTS.md"
        self.file.write_text("# mine\n", encoding="utf-8")
        self.registry = [{"name": "T", "type": "AI Agent", "rules_paths": [str(self.file)]},
                         {"name": "U", "type": "AI Agent", "rules_paths": [str(self.file)]}]
        self._patch = __import__("unittest.mock", fromlist=["patch"]).patch.object(
            rs, "settings_path", lambda: str(self.settings))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_default_is_enabled(self):
        self.assertTrue(rs.audit("#x", registry=self.registry)["rows"][0]["enabled"])

    def test_toggle_off_reflected_in_audit(self):
        rs.set_client_enabled("T", False)
        rows = {r["name"]: r for r in rs.audit("#x", registry=self.registry)["rows"]}
        self.assertFalse(rows["T"]["enabled"])
        self.assertTrue(rows["U"]["enabled"], "只关一个，另一个不受影响")

    def test_disabled_client_refuses_write(self):
        rs.set_client_enabled("T", False)
        res = rs.apply_client("T", "# shared\n", registry=self.registry)
        self.assertFalse(res["ok"])
        self.assertIn("已关闭", res["reason"])
        self.assertNotIn("shared-rules", self.file.read_text(encoding="utf-8"),
                         "关闭的 Agent 不允许被写入")

    def test_enabled_client_still_writes(self):
        rs.set_client_enabled("T", False)
        res = rs.apply_client("U", "# shared\n", registry=[self.registry[1]])
        self.assertTrue(res["ok"])

    def test_settings_file_persists(self):
        rs.set_client_enabled("T", False)
        self.assertEqual(rs.load_settings(), {"T": False})


class WiringTest(unittest.TestCase):
    def test_cli_and_gui_and_rust(self):
        root = Path(__file__).resolve().parents[1]
        scan = (root / "scan.py").read_text(encoding="utf-8")
        for flag in ("--shared-rules-audit", "--shared-rules-get",
                     "--shared-rules-set", "--shared-rules-apply"):
            self.assertIn(flag, scan, f"CLI 缺 {flag}")
        rs_ = (root / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        for flag in ("--shared-rules-audit", "--shared-rules-set", "--shared-rules-apply"):
            self.assertIn(flag, rs_, f"Rust 白名单缺 {flag}")
        self.assertIn("--shared-rules-toggle", scan, "CLI 缺逐 Agent 开关")
        self.assertIn("--shared-rules-toggle", rs_, "Rust 白名单缺逐 Agent 开关")
        gui = (root / "gui/dashboard.html").read_text(encoding="utf-8")
        self.assertIn('data-action="shared-rules-toggle"', gui, "GUI 缺逐 Agent 开关")
        self.assertIn('role="switch"', gui, "开关必须用既有 .switch 控件")
        self.assertIn("function auditSharedRules()", gui, "GUI 缺检查同步状态")
        self.assertIn("function applySharedRules(client)", gui, "GUI 缺强制写入")
        self.assertIn('data-action="shared-rules-apply"', gui)

    def test_card_follows_settings_card_language(self):
        """共享约束卡片必须复用设置页既有的 row / k / v 语言（v0.40.1 重设计）。

        上一版把 label 放在 textarea 下方、按钮散在两侧，与设置页其它卡片
        「label 左 / 控件右 / hairline 分隔」完全不搭（用户：「这个设计有点丑」）。
        """
        root = Path(__file__).resolve().parents[1]
        gui = (root / "gui/dashboard.html").read_text(encoding="utf-8")
        start = gui.find('id="shared-rules-card"')
        self.assertGreater(start, 0)
        end = gui.find("</div>`;", start)
        card = gui[start:end]
        for token in ('class="rows"', 'class="row row-block"', '<span class="k">约束内容</span>',
                      '<span class="k">同步状态</span>', 'class="shared-actions"'):
            self.assertIn(token, card, f"卡片缺少 {token}（应复用 settings-card 的行语言）")
        # 按钮只用既有三档，不允许新造按钮类
        self.assertIn('button class="primary"', card)
        self.assertIn('button class="ghost"', card)
        self.assertIn('button class="btn-soft"', card)

    def test_textarea_style_is_card_scoped(self):
        root = Path(__file__).resolve().parents[1]
        gui = (root / "gui/dashboard.html").read_text(encoding="utf-8")
        self.assertIn(".settings-card .row .v > textarea {", gui,
                      "卡片内 textarea 必须有作用域样式（不能靠浏览器默认外观）")
        idx = gui.find(".settings-card .row .v > textarea {")
        block = gui[idx: gui.find("}", idx)]
        for prop in ("border-radius: var(--r-control)", "font-family: var(--mono)",
                     "max-width: 44rem", "resize: vertical"):
            self.assertIn(prop, block, f"textarea 样式缺 {prop}")


if __name__ == "__main__":
    unittest.main()
