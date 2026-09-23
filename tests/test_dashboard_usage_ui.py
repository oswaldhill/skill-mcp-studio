"""FEAT-10 GUI 护栏：技能使用统计入口、CLI 白名单，以及一条静态守卫。

静态守卫 UndeclaredStateRefTest 的存在理由：FEAT-9 的市场面板引用了从未声明的
MARKET_DATA，node --check 与全部单测都是绿的，但用户第一次点「技能市场」就会
抛 ReferenceError（面板打开后源状态永不加载）。这类"标识符没声明就用"的缺陷
只有静态扫描引用与声明的差集才能拦住。
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
RS = ROOT / "src-tauri" / "src" / "lib.rs"
SCAN = ROOT / "scan.py"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _section(page_id: str) -> str:
    m = re.search(r'<section id="' + page_id + r'".*?</section>', _src(), re.S)
    if not m:
        raise AssertionError(f"未找到页面区块 {page_id}")
    return m.group(0)


def _fn(name: str) -> str:
    m = re.search(r"(async\s+)?function " + name + r"\(.*?\n  \}", _src(), re.S)
    if not m:
        raise AssertionError(f"未找到函数 {name}")
    return m.group(0)


def _script() -> str:
    m = re.search(r"<script>(.*)</script>", _src(), re.S)
    if not m:
        raise AssertionError("未找到 <script> 区块")
    return m.group(1)


# ---------------------------------------------------------------- 静态守卫


def _strip_strings_and_comments(code: str) -> str:
    """抹掉字符串/模板串/注释，但保留 ${...} 里的真实代码。

    不先剥字符串就会被 SVG path（"M10.5 4"）、文案里的 "SKILL.md" 之类
    制造大量假阳性，守卫就会失去意义。
    """
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        # 行注释
        if c == "/" and nxt == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        # 块注释
        if c == "/" and nxt == "*":
            i += 2
            while i < n - 1 and not (code[i] == "*" and code[i + 1] == "/"):
                i += 1
            i += 2
            continue
        # 普通字符串
        if c in ("'", '"'):
            quote = c
            i += 1
            while i < n:
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == quote:
                    i += 1
                    break
                if code[i] == "\n":       # 未闭合，按行截断，避免吞掉整份文件
                    break
                i += 1
            out.append(" ")
            continue
        # 模板串：${} 内部是真实代码，要递归保留
        if c == "`":
            i += 1
            while i < n:
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == "`":
                    i += 1
                    break
                if code[i] == "$" and i + 1 < n and code[i + 1] == "{":
                    depth, start = 1, i + 2
                    j = start
                    while j < n and depth:
                        if code[j] == "{":
                            depth += 1
                        elif code[j] == "}":
                            depth -= 1
                        j += 1
                    out.append(_strip_strings_and_comments(code[start:j - 1]))
                    i = j
                    continue
                i += 1
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


# 浏览器/ECMAScript 全局，不是本文件的状态对象。
_GLOBALS = {
    "JSON", "MATH", "NUMBER", "STRING", "BOOLEAN", "ARRAY", "OBJECT",
    "PROMISE", "SYMBOL", "BIGINT", "REFLECT", "PROXY", "CSS", "URL",
    "NaN", "Infinity", "REGEXP", "MAP", "SET", "WEAKMAP", "WEAKSET",
    "INTL", "ERROR", "TYPEERROR", "RANGEERROR", "DATE", "CONSOLE",
    "WINDOW", "DOCUMENT", "GLOBALTHIS", "PROCESS", "MCP", "CLI", "API",
    "HTTP", "HTTPS", "SQL", "ID", "UI", "OK", "TODO", "NOTE", "ERR",
}


class UndeclaredStateRefTest(unittest.TestCase):
    """引用了从未声明的全大写状态对象 => 运行时 ReferenceError。"""

    def _undeclared(self) -> list[str]:
        js = _strip_strings_and_comments(_script())
        declared = set(re.findall(
            r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)\b", js))
        # 解构声明里的名字也要算已声明
        for grp in re.findall(r"\b(?:const|let|var)\s*\{([^}]*)\}", js):
            for part in grp.split(","):
                name = part.split(":")[-1].split("=")[0].strip()
                if name:
                    declared.add(name)
        refs = set(re.findall(
            # NAME.member 才算属性访问；NAME.md / NAME.json 这类是文案里的文件名
            # （HTML 文案会残留进剥离结果），不是引用。
            r"\b([A-Z][A-Z0-9_]{2,})\.(?!"
            r"md|json|js|ts|tsx|jsx|py|txt|html|css|ya?ml|csv|lock|sh|rs|go|bak\b)", js))
        return sorted(r for r in refs if r not in declared and r not in _GLOBALS)

    def test_no_undeclared_all_caps_state_refs(self):
        bad = self._undeclared()
        self.assertEqual(
            bad, [],
            f"这些全大写对象被引用却从未声明，运行时必然 ReferenceError: {bad}")

    def test_guardrail_actually_detects_planted_bug(self):
        """守卫自检：植入一个「引用未声明」的样本必须被抓出，否则守卫是空转。"""
        planted = """
          const FOO_STATE = { a: 1 };
          function open() { return !FOO_STATE.a && BAR_STATE.b && "SKILL.md" === 0; }
        """
        js = _strip_strings_and_comments(planted)
        declared = set(re.findall(
            r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)\b", js))
        refs = set(re.findall(
            r"\b([A-Z][A-Z0-9_]{2,})\.(?!"
            r"md|json|js|ts|tsx|jsx|py|txt|html|css|ya?ml|csv|lock|sh|rs|go|bak\b)", js))
        bad = sorted(r for r in refs if r not in declared and r not in _GLOBALS)
        self.assertEqual(bad, ["BAR_STATE"], "守卫未能识别植入缺陷，或把文件名当引用")

    def test_market_data_is_declared_regression(self):
        """FEAT-9 的真实缺陷回归：MARKET_DATA 曾有引用无声明。"""
        js = _script()
        self.assertIn("MARKET_DATA", js, "市场状态对象引用已消失，接线可能被误删")
        self.assertRegex(js, r"(const|let|var)\s+MARKET_DATA\b",
                         "MARKET_DATA 未声明：点击技能市场会抛 ReferenceError")


class UsageUiTest(unittest.TestCase):
    def test_skills_page_has_usage_entry(self):
        self.assertIn('data-action="open-usage"', _section("page-skills"))

    def test_panel_containers_exist(self):
        sect = _section("page-skills")
        for el in ("usage-panel", "usage-status", "usage-results"):
            self.assertIn(f'id="{el}"', sect, f"缺少容器 {el}")

    def test_actions_are_wired(self):
        src = _src()
        for action in ("open-usage", "usage-close", "usage-refresh", "usage-window"):
            self.assertIn(f'a === "{action}"', src, f"{action} 未接线")

    def test_window_buttons_present(self):
        sect = _section("page-skills")
        self.assertIn('data-action="usage-window"', sect)
        for win in ('data-win="30"', 'data-win="90"', 'data-win="0"'):
            self.assertIn(win, sect, f"缺少统计窗口按钮 {win}")

    def test_uses_read_only_cli_flag(self):
        src = _src()
        self.assertIn('"--skill-usage"', src)
        self.assertIn('"--usage-since"', src)

    def test_judgement_stays_in_backend(self):
        """前端不得自己解析会话日志或复刻判据（口径必须唯一）。"""
        body = _fn("renderUsage") + _fn("runSkillUsage")
        for token in ("archived_sessions", ".jsonl", "host_skills", "SKILL.md"):
            self.assertNotIn(token, body, f"前端越界实现了判据片段 {token}")

    def test_long_task_gives_progress_hint(self):
        """全量扫描约 30 秒，必须先给出「统计中」提示，不能让界面看似卡死。"""
        body = _fn("runSkillUsage")
        self.assertIn("统计中", body)

    def test_zero_touch_list_rendered(self):
        """零触达清单是本功能的主要产出（清理/合并依据），必须有渲染路径。"""
        body = _fn("renderUsage")
        self.assertIn("never_used", body)
        self.assertIn("零触达", body)

    def test_no_forbidden_glyphs(self):
        """与既有 taste 护栏一致：不用 em-dash / ⚠ / ✓。"""
        for name in ("usageSince", "toggleUsagePanel", "usageLine",
                     "runSkillUsage", "renderUsage"):
            body = _fn(name)
            self.assertNotIn("—", body, f"{name} 含 em-dash")
            self.assertNotIn("⚠", body, f"{name} 含 ⚠")
            self.assertNotIn("✓", body, f"{name} 含 ✓")


class UsageCliContractTest(unittest.TestCase):
    """GUI 调用的参数必须真的存在于 argparse，且被 main 早返回路由。"""

    def test_argparse_declares_flags(self):
        src = SCAN.read_text(encoding="utf-8")
        self.assertIn('"--skill-usage"', src)
        self.assertIn('"--usage-since"', src)

    def test_dispatched_before_generic_snapshot(self):
        src = SCAN.read_text(encoding="utf-8")
        route = src.index('args, "skill_usage"')
        # 必须锚定「调用处」；直接搜函数名会先命中函数定义，比较结果没有意义。
        snapshot = src.index("return _run_single_profile_snapshot(")
        self.assertLess(route, snapshot,
                        "使用统计必须排在通用快照路由之前，否则 stdout 会被截走")

    def test_rust_allowlist_admits_flag(self):
        src = RS.read_text(encoding="utf-8")
        m = re.search(r"const ALLOWED: &\[&str\] = &\[(.*?)\];", src, re.S)
        self.assertIsNotNone(m, "未找到 ALLOWED 白名单")
        allowed = re.findall(r'"([^"]+)"', m.group(1))
        self.assertIn("--skill-usage", allowed,
                      "--skill-usage 不在 run_cli 白名单内，GUI 会被安全边界拒绝")

    def test_export_is_read_only(self):
        """只读出口：函数体内不得出现写盘调用。"""
        src = SCAN.read_text(encoding="utf-8")
        m = re.search(r"def _run_skill_usage\(args\) -> int:.*?\n\ndef ", src, re.S)
        self.assertIsNotNone(m, "未找到 _run_skill_usage")
        body = m.group(0)
        for token in ("write_text", "open(", "shutil", "os.remove", "--yes"):
            self.assertNotIn(token, body, f"只读出口出现写操作片段 {token}")


if __name__ == "__main__":
    unittest.main()
