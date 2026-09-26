"""FEAT-11 界面与出口护栏：整理建议面板、CLI 契约、旧按钮改名回归。

沿用 tests/test_dashboard_usage_ui.py 的探测方式（面板 JS 函数缩进两空格，
故提取正则必须是 `\\n  \\}`，用 `\\n\\}` 会一路吞到脚本尾部、断言形同虚设）。
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
RS = ROOT / "src-tauri" / "src" / "lib.rs"
SCAN = ROOT / "scan.py"
ADVISOR = ROOT / "core" / "skill_merge_advisor.py"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _section(page_id: str) -> str:
    m = re.search(r'<section id="' + page_id + r'".*?</section>', _src(), re.S)
    if not m:
        raise AssertionError(f"未找到页面区块 {page_id}")
    return m.group(0)


def _js() -> str:
    m = re.search(r"<script>(.*)</script>", _src(), re.S)
    if not m:
        raise AssertionError("未找到 <script> 区块")
    return m.group(1)


def _fn(name: str) -> str:
    m = re.search(r"(?:async\s+)?function " + name + r"\(.*?\n  \}", _js(), re.S)
    if not m:
        raise AssertionError(f"未找到函数 {name}")
    return m.group(0)


class AdviceUiTest(unittest.TestCase):
    def test_skills_page_has_advice_entry(self):
        self.assertIn('data-action="open-insight"', _section("page-skills"))

    def test_panel_containers_exist(self):
        sect = _section("page-skills")
        for el in ("insight-panel", "insight-status", "advice-results"):
            self.assertIn(f'id="{el}"', sect, f"缺少容器 {el}")

    def test_actions_are_wired(self):
        src = _src()
        for action in ("open-insight", "insight-close", "insight-force", "insight-window", "insight-tab"):
            self.assertIn(f'a === "{action}"', src, f"{action} 未接线")

    def test_window_buttons_present(self):
        sect = _section("page-skills")
        self.assertIn('data-action="insight-window"', sect)
        for win in ('data-win="30"', 'data-win="90"', 'data-win="0"'):
            self.assertIn(win, sect, f"缺少窗口按钮 {win}")

    def test_uses_read_only_cli_flag(self):
        body = _fn("runSkillInsight")
        self.assertIn('"--skill-insight"', body)
        self.assertIn('"--usage-since"', body)

    def test_reuses_usage_window_helper(self):
        """DRY：窗口计算只该有一处实现。"""
        self.assertIn("usageSince(USAGE_DAYS)", _fn("runSkillInsight"))

    def test_long_task_gives_progress_hint(self):
        """内含全量会话扫描（约 35 秒），必须提示，不能让界面看似卡死。"""
        self.assertIn("统计中", _fn("runSkillInsight"))

    def test_renders_all_three_sections(self):
        """三段都要有渲染路径：可执行、上游标注、已否决。"""
        body = _fn("renderAdvice")
        for key in ("actionable", "upstream_only", "rejected"):
            self.assertIn(key, body, f"清单 {key} 未渲染")

    def test_empty_result_explains_why(self):
        """空清单要说清是"没重复"而不是"没跑成功"，否则用户会反复重跑。"""
        self.assertIn("有意变体", _fn("renderAdvice"))

    def test_shows_evidence_and_gates(self):
        body = _fn("renderAdvice")
        self.assertIn("依据", body, "合并建议必须附证据，否则无法人工核验")
        self.assertIn("blocked_by", body, "否决项必须说明被哪个关卡拦下")
        self.assertIn("留痕", body)

    def test_states_consequence_of_actions(self):
        """界面必须讲清操作的后果与可恢复性。

        原意图是"避免用户以为点了就会动库"。FEAT-12 之后面板确实能执行合并了，
        所以约束随之改为：既然能动手，就必须说明白动的是什么、能不能恢复。
        """
        body = _fn("renderAdvice")
        self.assertIn("_trash", body, "要说明归并方去了哪里")
        self.assertIn("_backup", body, "要说明留有备份")
        self.assertIn("复核", body, "要说明执行前会重新复核判据")
        self.assertIn("保留方不动", body, "要说明保留方不被改动")

    def test_advisor_module_stays_read_only(self):
        """判据模块本身必须只读：执行能力只存在于 skill_merge_exec。"""
        advisor = (ROOT / "core" / "skill_merge_advisor.py").read_text(encoding="utf-8")
        for writer in ("shutil.move", "shutil.rmtree", "os.remove", "os.rename",
                       "copytree", "unlink("):
            self.assertNotIn(writer, advisor,
                             f"判据模块出现写操作 {writer}，只读约束被破坏")

    def test_member_row_surfaces_provenance_marks(self):
        body = _fn("memberRow")
        for token in ("has_scripts", "has_license", "零触达", "last_used", "sessions"):
            self.assertIn(token, body, f"成员行缺少证据 {token}")

    def test_no_judgement_leaked_into_frontend(self):
        """判据必须留在 Python 侧，前端不得复刻分词/相似度或读会话日志。"""
        body = _fn("renderAdvice") + _fn("runSkillInsight") + _fn("memberRow")
        for token in ("archived_sessions", ".jsonl", "host_skills", "jaccard >=",
                      "function_call"):
            self.assertNotIn(token, body, f"前端越界实现判据片段 {token}")

    def test_no_forbidden_glyphs(self):
        for name in ("setInsightStatus", "toggleInsightPanel", "runSkillInsight",
                     "memberRow", "renderAdvice"):
            body = _fn(name)
            for glyph in ("—", "⚠", "✓"):
                self.assertNotIn(glyph, body, f"{name} 含禁用字形 {glyph}")

    def test_advice_state_declared_and_used(self):
        js = _js()
        body = (_fn("toggleInsightPanel") + _fn("runSkillInsight")
                + _fn("memberRow") + _fn("renderAdvice"))
        # ADVICE_DATA 仍是建议视图的状态；窗口口径已合并到 USAGE_DAYS
        # （统计与建议共用同一次扫描），不再保留第二个窗口变量。
        self.assertRegex(js, r"(const|let|var)\s+ADVICE_DATA\b",
                         "ADVICE_DATA 未声明：点击整理建议会抛 ReferenceError")
        # ADVICE_DATA 由 applyInsight 统一落位（合并后没有独立的取数函数）
        self.assertIn("ADVICE_DATA", _fn("applyInsight"),
                      "ADVICE_DATA 声明了但没有任何落位路径")
        self.assertIn("usageSince(USAGE_DAYS)", body, "取数必须用唯一的窗口口径")
        self.assertNotIn("ADVICE_DAYS", body, "窗口口径应唯一，不应残留第二个变量")


class LegacyButtonRenameTest(unittest.TestCase):
    """旧「一键合并技能」实为 --fix-skills 路径重挂，与去重无关，必须改名。"""

    def test_old_label_gone(self):
        self.assertNotIn("一键合并技能", _src(),
                         "旧文案仍在：与新增的「整理建议」并列必然误导用户")

    def test_new_label_wired_to_same_action(self):
        sect = _section("page-skills")
        self.assertIn('data-action="merge"', sect, "merge 动作被删掉了")
        self.assertIn("修复链接", sect, "按钮未改成准确文案")

    def test_tooltip_states_what_it_actually_does(self):
        m = re.search(r'data-action="merge"[^>]*title="([^"]+)"', _src())
        self.assertIsNotNone(m, "缺少说明其真实作用的 title")
        self.assertIn("链接", m.group(1))

    def test_cli_semantics_untouched(self):
        """只改文案：action 与 CLI 参数不得跟着改名。"""
        src = _src()
        self.assertIn("openMergePreview", src)
        self.assertIn("--fix-skills", src)


class AdviceCliContractTest(unittest.TestCase):
    def test_argparse_declares_flag(self):
        self.assertIn('"--skill-insight"', SCAN.read_text(encoding="utf-8"))

    def test_dispatched_before_generic_snapshot(self):
        src = SCAN.read_text(encoding="utf-8")
        route = src.index('args, "merge_advice"')
        snapshot = src.index("return _run_single_profile_snapshot(")
        self.assertLess(route, snapshot,
                        "整理建议必须排在通用快照之前，否则 stdout 被截走")

    def test_rust_allowlist_admits_flag(self):
        src = RS.read_text(encoding="utf-8")
        m = re.search(r"const ALLOWED: &\[&str\] = &\[(.*?)\];", src, re.S)
        self.assertIsNotNone(m, "未找到 ALLOWED 白名单")
        self.assertIn("--merge-advice", re.findall(r'"([^"]+)"', m.group(1)),
                      "--merge-advice 不在白名单，GUI 调用会被安全边界拒绝")

    def test_cli_export_is_read_only(self):
        src = SCAN.read_text(encoding="utf-8")
        m = re.search(r"def _run_merge_advice\(args\) -> int:.*?\n\ndef ", src, re.S)
        self.assertIsNotNone(m, "未找到 _run_merge_advice")
        body = m.group(0)
        for token in ("write_text", "shutil", "os.remove", "--yes", "market-install"):
            self.assertNotIn(token, body, f"只读出口出现写操作片段 {token}")


class AdvisorReadOnlyAstTest(unittest.TestCase):
    """用 AST 审计代码（剔除文档字符串与注释），比子串匹配更准。"""

    def _code_only(self):
        tree = ast.parse(ADVISOR.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(getattr(body[0], "value", None), ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    body[0].value.value = ""       # 抹掉文档字符串
        return ast.dump(tree)

    def test_no_filesystem_mutation_calls(self):
        code = self._code_only()
        called = {n.func.attr for n in ast.walk(ast.parse(
            ADVISOR.read_text(encoding="utf-8")))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for bad in ("write_text", "mkdir", "remove", "rename", "unlink",
                    "rmtree", "copy", "symlink_to", "truncate"):
            self.assertNotIn(bad, called, f"判据模块出现写操作 {bad}()")

    def test_no_subprocess(self):
        """只读判据不需要任何外部命令（FEAT-9 的 npx skills check 教训）。"""
        self.assertNotIn("subprocess", self._code_only())
        self.assertNotIn("npx", ADVISOR.read_text(encoding="utf-8"))

    def test_does_not_import_write_channel(self):
        imports = {a.name for n in ast.walk(ast.parse(ADVISOR.read_text(encoding="utf-8")))
                   if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module for n in ast.walk(
            ast.parse(ADVISOR.read_text(encoding="utf-8")))
            if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("skill_market_ops", imports)
        self.assertTrue(imports & {"skill_usage", "skill_market"},
                        "判据应复用 FEAT-10 统计与 lock 登记，而非自己重扫")


if __name__ == "__main__":
    unittest.main()
