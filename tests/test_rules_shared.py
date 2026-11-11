"""共享约束块测试（v0.40.0）。

用户需求：「配置一个需要在所有 Agent 中增加的约束内容，通过同步管理检查每一个
Agent 是否都拥有它；如果没有，可以强制更新进去」。
"""

import os
import sys
import tempfile
import re
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
        # absent：文件存在但没有块，且内容确实缺失
        self.file.write_text("# mine\n- 完全无关的一条\n", encoding="utf-8")
        r = rs.audit("# shared\n", registry=self.registry)
        self.assertEqual(r["rows"][0]["state"], "absent")
        rs.apply_client("T", "# shared\n", registry=self.registry)
        r = rs.audit("# shared\n", registry=self.registry)
        self.assertEqual(r["rows"][0]["state"], "current")
        # 内容不同但语义无关 → stale（块在，但内容已不是当前配置）
        r = rs.audit("# 完全不相干的一条\n", registry=self.registry)
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


class AgentMenuRulesEntryTest(unittest.TestCase):
    """「⋯」菜单里必须有写入共享约束的入口（v0.44.1 用户要求）。

    用户截图：菜单里只有「查看详情 / 重新扫描 / 移出管理」，问「操作里面没有修复的
    按钮，然后前面黄色的约束我怎么进行修复？」。约束此前只能靠命令行。
    """

    def setUp(self):
        self.gui = (Path(__file__).resolve().parents[1] / "gui/dashboard.html").read_text(encoding="utf-8")

    def test_menu_has_fix_rules_item(self):
        self.assertIn('data-pm="fix-rules"', self.gui, "菜单缺「写入共享约束」项")
        self.assertIn("写入共享约束", self.gui, "菜单文案缺失")

    def test_menu_item_conditional_on_need(self):
        """只在「有约束文件、内容非空、且未达标」时出现，避免菜单自相矛盾。"""
        self.assertIn("function needFixRulesFor(a)", self.gui)
        start = self.gui.index("function needFixRulesFor(a)")
        body = self.gui[start: start + 1400]
        self.assertIn("RULES_DATA", body, "必须复用列表列的同一份约束数据")
        self.assertIn("current", body)
        self.assertIn("covered", body)

    def test_audit_loaded_at_boot(self):
        """启动时必须加载共享约束审计（v0.44.3 根因）。

        `SHARED_AUDIT` 此前只由「检查同步状态」按钮填充，而「写入共享约束」的判定
        依赖它 → 菜单里永远没有这一项。用户连报两次「菜单和你描述的不一致」。
        """
        start = self.gui.index("async function loadManagement()")
        body = self.gui[start: start + 2000]
        self.assertIn("auditSharedRules()", body,
                      "loadManagement 成功后必须拉一次共享约束审计")

    def test_ghost_node_writes_are_guarded(self):
        """JS 里写的每个 #id 都必须在 HTML 静态或动态注入中存在（v0.44.4）。

        事故：v0.40.7 删掉了 `#shared-rules-status` 节点，但 `auditSharedRules()`
        最后一行仍无条件 `host.innerHTML = ...`。以前只在用户点按钮时跑，没暴露；
        v0.44.3 改成启动即跑后立刻抛 TypeError，被全局兜底渲染成「操作失败」弹框。

        门禁：任何 `$("x")` / `host` 式的条件写入必须在**存在性判断内**。
        这里用更稳的可机检方式：静态 HTML 与动态模板里都不存在的 id，不得出现在
        `$(...).innerHTML/className` 这类无条件写法里。
        """
        root = Path(__file__).resolve().parents[1]
        src = (root / "gui/dashboard.html").read_text(encoding="utf-8")
        html_part = src[: src.index("<script>")]
        js = src[src.index("<script>"): src.index("</script>")]
        static_ids = set(re.findall(r'id="([a-z0-9-]+)"', html_part))
        dynamic_ids = set(re.findall(r"id=[`\"']([a-z0-9-]+)[`\"']", js))
        known = static_ids | dynamic_ids
        ghosts = []
        for line in js.splitlines():
            m = re.search(r'\$\("([a-z0-9-]+)"\)\.(innerHTML|textContent|className)', line)
            if m and m.group(1) not in known:
                ghosts.append(m.group(1))
        self.assertEqual(ghosts, [], f"无条件写入不存在的节点：{ghosts}")

    def test_audit_host_write_is_guarded(self):
        """auditSharedRules 写状态区必须判空。"""
        start = self.gui.index("async function auditSharedRules()")
        rest = self.gui[start:]
        nxt = rest.find("\nasync function ", 10)
        body = rest[: nxt if nxt > 0 else 4000]
        self.assertIn("if (host) {", body, "host 可能为 null，写入必须判空")
        self.assertNotRegex(body, r"\n  host\.innerHTML = ", "不得无条件写 host.innerHTML")

    def test_missing_audit_means_needs_fix(self):
        """审计缺失时，菜单判定必须与约束格同口径（视为未达标）。

        此前 `if (!shared) return false;` —— 格子在这种情况下是**黄色**（走「有内容
        但未达标」分支），菜单却说不用修，两处自相矛盾。
        """
        start = self.gui.index("function needFixRulesFor(a)")
        rest = self.gui[start:]
        nxt = rest.find("\nfunction ", 10)
        body = rest[: nxt if nxt > 0 else 2000]
        self.assertIn("if (!shared) return true;", body,
                      "缺审计数据时必须返回 true（与黄色格子一致）")

    def test_menu_logs_decision_basis(self):
        """菜单打开时必须把判定依据打到控制台（v0.44.2）。

        用户反馈「菜单和你描述的不一致」时，若没有这份日志，只能靠猜是哪一项判定
        不成立。日志包含 needSkills / needMcp / needRules 三个布尔值、约束路径、
        共享状态、共享内容字节数与实际渲染出的菜单项。
        """
        self.assertIn('console.info("[agent-menu]"', self.gui, "菜单缺判定依据日志")
        start = self.gui.index('console.info("[agent-menu]"')
        block = self.gui[start: start + 700]
        for key in ("needRules", "rulesPaths", "sharedState", "sharedBytes", "items"):
            self.assertIn(key, block, f"日志缺 {key}")

    def test_dispatch_and_writer_exist(self):
        self.assertIn('pm === "fix-rules"', self.gui, "菜单动作未分发")
        self.assertIn("async function fixRulesFor(name)", self.gui, "缺写入实现")
        start = self.gui.index("async function fixRulesFor(name)")
        # 截到函数结尾：只往前找下一个顶层 `async function` 之前的部分
        rest = self.gui[start:]
        nxt = rest.find("\nasync function ", 10)
        body = rest[: nxt if nxt > 0 else 4000]
        self.assertIn('"--shared-rules-apply"', body, "必须调用共享约束写入命令")
        # 精确到「独立一行调用 loadRules()」：只查 `loadRules(` 会被
        # `loadSharedRules()` 里的同名子串满足，反向验证写不出会失败的用例（实测踩到）。
        self.assertRegex(body, r"\n\s+await loadRules\(\);",
                         "写完必须重拉约束数据，否则格子颜色不变")


class SemanticMatchTest(unittest.TestCase):
    """「意思一样即算达标」+「把文件里类似内容替换掉」（v0.43.0 用户要求）。

    用户：(b) 检查不是内容一模一样，而是表达的意思一样即可；
          (c) 不但要写进去，还要把原来文件中类似的内容给替换掉。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = Path(self.tmp) / "AGENTS.md"
        self.registry = [{"name": "T", "type": "AI Agent", "rules_paths": [str(self.file)]}]

    def test_paraphrase_counts_as_covered(self):
        self.file.write_text("# mine\n- 所有回答都必须使用中文\n", encoding="utf-8")
        state = rs._path_state(str(self.file), "- 所有回答包括思考过程，都必须使用中文\n")
        self.assertEqual(state["state"], "covered", "同义改写应判为已覆盖")

    def test_unrelated_is_not_covered(self):
        self.file.write_text("# mine\n- 提交前必须跑全量测试\n", encoding="utf-8")
        state = rs._path_state(str(self.file), "- 所有回答都必须使用中文\n")
        self.assertEqual(state["state"], "absent", "不同主题不得判为已覆盖")

    def test_similar_line_is_replaced(self):
        """写入时把文件里意思相同的旧条目删掉，避免同一句出现两遍。"""
        self.file.write_text(
            "# 我的规则\n\n- 所有回答都必须使用中文\n- 不要删文件\n", encoding="utf-8")
        rs.apply_client("T", "- 所有回答包括思考过程，都必须使用中文\n", registry=self.registry)
        text = self.file.read_text(encoding="utf-8")
        self.assertEqual(text.count("中文"), 1, "旧条目应被替换掉，不能出现两遍")
        self.assertIn("不要删文件", text, "无关条目必须保留")
        self.assertIn(rs.BEGIN, text, "仍要写入标记块")

    def test_threshold_documented(self):
        self.assertTrue(0.3 <= rs.SIMILARITY_THRESHOLD <= 0.6,
                        "阈值必须在实测区间内（同义 0.52~0.79 / 无关 < 0.3）")


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
        self.assertNotIn('data-action="shared-rules-toggle"', gui,
                         "逐 Agent 开关不应再出现在界面（v0.40.5 用户要求）")
        self.assertIn("function auditSharedRules()", gui, "GUI 缺检查同步状态")
        self.assertIn("function applySharedRules(client)", gui, "GUI 缺强制写入")

    def test_shared_state_surfaces_in_rules_cells(self):
        """共享块状态必须出现在**约束对应的格子**里（v0.40.3 用户要求）。

        用户：「在外面正式功能的上方，没法从约束对应的框中展示出，到底有没有
        增加进我要求的这部分约束」。卡片与主表的「约束」列此前只看路径是否存在，
        不看共享块在不在。
        """

        root = Path(__file__).resolve().parents[1]
        gui = (root / "gui/dashboard.html").read_text(encoding="utf-8")
        self.assertIn("SHARED_AUDIT", gui, "需要缓存共享审计结果供卡片使用")

        # 断言的是**渲染分支**，不是「文件里出现过这几个字」——
        # 后者会被自己的注释满足（第一次写这条断言时就是这么自欺的：把映射表
        # 换成空串，测试照样绿）。这里抽出两个渲染函数，逐段校验。
        def _fn(name):
            start = gui.index(f"function {name}(")
            depth = 0
            for i in range(start, len(gui)):
                if gui[i] == "{":
                    depth += 1
                elif gui[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return gui[start:i + 1]
            raise AssertionError(f"{name} 未闭合")

        card = _fn("_agentRulesSummary")
        self.assertRegex(card, r'current:\s*"共享已含"', "卡片摘要必须按共享状态输出「共享已含」")
        self.assertRegex(card, r'stale:\s*"共享过期"', "卡片摘要必须输出「共享过期」")
        self.assertIn("SHARED_AUDIT", card, "卡片摘要必须读共享审计结果")

        lst = _fn("renderHomeListView")
        # 只校验**渲染进单元格的那一步**：整行文本里出现 `>${sharedSpan}<`
        # 才算「显示出来了」。只查变量名会被「定义了但没渲染」骗过去
        # （第一次写这条断言时就踩了：把变量改名，测试照样绿）。
        self.assertRegex(lst, r'\$\{sharedSpan\}', "主表列表必须把共享状态渲染进单元格")
        self.assertIn("共享已含", lst, "列表列必须区分「共享已含」")
        self.assertIn("共享过期", lst, "列表列必须区分「共享过期」")
        self.assertIn('"covered"', lst, "语义一致（covered）也必须算已含（v0.43.0）")

    def test_shared_card_is_content_only_in_settings(self):
        """共享约束只保留「内容输入框」，位置在设置页 IDE / Agent tab（v0.40.7 定稿）。

        用户最终定案：红框里的（标题 + 约束内容输入框）保留，其余删除，并挪回
        设置页 IDE / Agent tab。
        """
        root = Path(__file__).resolve().parents[1]
        gui = (root / "gui/dashboard.html").read_text(encoding="utf-8")
        self.assertIn("function sharedRulesCard()", gui)
        self.assertIn('id="shared-rules-text"', gui, "必须有内容输入框")
        # 同步行 / 状态一览 / 逐 Agent 开关都不再出现在卡片里
        self.assertNotIn('id="shared-rules-status"', gui, "状态一览已删除")
        self.assertNotIn('id="shared-rules-summary"', gui, "同步行已删除")
        self.assertNotIn('data-action="shared-rules-toggle"', gui, "逐 Agent 开关已删除")
        # 位置：设置页 agents tab，且不再出现在概览
        self.assertIn('data-panel="agents">${sharedRulesCard()}', gui,
                      "卡片必须挂在设置页 IDE / Agent tab")
        # v0.40.8：「设置里应该只保存，不需要同步」——卡片里不得出现同步动作
        card = gui[gui.index("function sharedRulesCard()"):]
        card = card[: card.index("\n}")]
        self.assertIn('data-action="shared-rules-save"', card, "卡片必须有「保存」")
        self.assertNotIn('shared-rules-apply', card, "卡片里不应有同步按钮")
        self.assertNotIn('shared-rules-audit', card, "卡片里不应有检查按钮")
        ov = gui[gui.index("function renderOverview()"):]
        ov = ov[: ov.index("\nfunction ")]
        self.assertNotIn("sharedRulesCard()", ov, "概览页不应再渲染该卡片")

    def test_rules_cell_uses_three_color_states(self):
        """约束列按「有无文件 × 有无共享内容」上色（v0.40.5）。

        无色 = 没有约束文件；黄 = 有文件但没有共享内容；绿 = 有文件且已含共享内容。
        """
        root = Path(__file__).resolve().parents[1]
        gui = (root / "gui/dashboard.html").read_text(encoding="utf-8")
        lst = gui[gui.index("function renderHomeListView("):]
        lst = lst[: lst.index("\nfunction ")]
        self.assertIn("hasSharedContent", lst, "约束列必须知道共享内容是否存在")
        self.assertRegex(lst, r'ruleCls = "warn"', "有文件但缺共享内容时应为 warn")
        self.assertRegex(lst, r'ruleCls = "ok"', "已含共享内容时应为 ok")
        self.assertRegex(lst, r'ruleCls = "";', "没有约束文件时应为中性")
        # 卡片侧同样按共享状态给徽标
        card = gui[gui.index("function _agentRulesSummary("):]
        card = card[: card.index("\nfunction ")]
        self.assertIn("SHARED_AUDIT", card, "卡片摘要必须读共享状态")
        self.assertIn("共享已含", card, "卡片摘要必须输出「共享已含」")
        self.assertIn("covered", card, "语义一致（covered）也必须算已含（v0.43.0）")
