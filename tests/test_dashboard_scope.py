"""仪表盘作用域与进度反馈护栏（v0.22.x 事故回归）。

事故回顾：FEAT-9/10/11 的面板块（使用统计/整理建议/技能市场）曾被误插进
`reprobeEndpoints()` 函数体内 —— 函数声明变成嵌套闭包，顶层点击委托找不到
它们，三个按钮上线以来每次点击都静默 ReferenceError。`node --check` 拦不住
（语法合法），切片单测也拦不住（把代码段单独取出来跑，看不见外层嵌套）。
只有**把整个脚本装进 vm 里真实派发点击**才暴露问题。本文件的 HarnessE2ETest
就是那记本该早就存在的哨兵。
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
HARNESS = ROOT / "tools" / "dash_crash_harness.js"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _script() -> str:
    return "\n".join(re.findall(r"<script>(.*?)</script>", _src(), re.S))


def _body(name: str) -> str:
    """按花括号平衡截取顶层具名函数体（含声明行）。"""
    s = _script()
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", s)
    if not m:
        raise AssertionError(f"未找到函数 {name}")
    i = s.index("{", m.end())
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[m.start():j + 1]
        j += 1
    raise AssertionError(f"函数 {name} 花括号不平衡")


class ScopeRegressionTest(unittest.TestCase):
    """reprobeEndpoints 必须在 FEAT-10 面板代码之前收尾。"""

    def test_reprobe_tail_closes_before_panel_blocks(self):
        s = _script()
        tail = s.index('ok ? "探活完成" : "探活失败"')
        marker = s.index("// ---------------- 技能使用统计（FEAT-10）")
        self.assertLess(
            tail, marker,
            "reprobeEndpoints 的收尾在面板代码之后 → FEAT-9/10/11 函数被嵌进"
            "函数体，顶层委托将全部静默失灵（曾发生过，见本文件 docstring）")

    def test_panel_markers_in_order_and_unique(self):
        s = _script()
        marks = ["// ---------------- 技能使用统计（FEAT-10） ----------------",
                 "// ---------------- 技能整理建议（FEAT-11） ----------------",
                 "// ---------------- 技能市场（FEAT-9） ----------------"]
        pos = []
        for mk in marks:
            self.assertEqual(s.count(mk), 1, f"分节标记异常：{mk}")
            pos.append(s.index(mk))
        self.assertEqual(pos, sorted(pos), "面板分节顺序被打乱")

    def test_toggle_functions_top_level(self):
        # 花括号平衡截取能成功本身就要求声明是独立函数；
        # 额外锚定：三个 toggle 与 reprobe 的间距（若被嵌进 reprobe，_body 仍会截到
        # 但定义行前会出现 reprobeEndpoints 头——用源文件层级缩进变化不可靠，
        # 真正的端到端防线在 HarnessE2ETest，这里只保证函数可截取）。
        for fn in ("toggleUsagePanel", "toggleAdvicePanel", "toggleMarketPanel"):
            body = _body(fn)
            self.assertIn("classList.toggle(\"hidden\"", body)


class BusyOverlayTest(unittest.TestCase):
    """长耗时 CLI 调用必须有进度对话框（用户明确要求的反馈）。"""

    def test_overlay_markup_exists(self):
        s = _src()
        self.assertIn('id="busy-root"', s)
        self.assertIn('id="busy-label"', s)
        self.assertIn('id="busy-time"', s)
        self.assertIn('role="status"', s)

    def test_overlay_above_modal_layer(self):
        s = _src()
        modal_z = int(re.search(r"\.modal-backdrop\s*\{[^}]*z-index:\s*(\d+)", s).group(1))
        busy_z = int(re.search(r"\.busy-backdrop\s*\{[^}]*z-index:\s*(\d+)", s).group(1))
        self.assertGreater(busy_z, modal_z, "进度框必须盖在模态层之上")

    def test_runcli_progress_with_finally(self):
        s = _script()
        self.assertRegex(s, r"async function runCli\(args,\s*progress\)")
        body = _body("runCli")
        self.assertIn("if (progress) showBusy(progress);", body)
        # finally 收框：异常路径不得把全屏对话框留在页面上
        self.assertRegex(body, r"finally\s*\{\s*if \(progress\) hideBusy\(\);\s*\}")
        self.assertIn("function showBusy(", s)
        self.assertIn("function hideBusy(", s)
        # hideBusy 必须清计时器，否则每秒 setInterval 泄漏
        self.assertIn("clearInterval(_busyTimer)", _body("hideBusy"))

    def test_slow_callers_pass_labels(self):
        expect = {
            "loadInternal": "更新审计",
            "runSkillUsage": "统计技能使用",
            "runMergeAdvice": "分析整理建议",
            "openMergePreview": "生成链接修复预览",
        }
        for fn, label in expect.items():
            self.assertIn(label, _body(fn), f"{fn} 的 runCli 调用缺进度对话框标签")
        s = _script()
        i = s.index('$("mg-apply").onclick')
        self.assertIn("执行链接修复", s[i:i + 500], "实写按钮缺进度标签")
        for kw in ("检查技能更新", "搜索技能市场", "安装 ${pkg}", "升级 ${name}"):
            self.assertIn(kw, s, f"market 慢调用缺进度标签：{kw}")

    def test_panels_scroll_into_view_when_opened(self):
        for fn in ("toggleUsagePanel", "toggleAdvicePanel", "toggleMarketPanel"):
            self.assertIn("scrollIntoView", _body(fn),
                          f"{fn}: 面板在长页面底部，展开后必须滚入视野，否则像没反应")


@unittest.skipUnless(shutil.which("node"), "需要 node 运行时")
class HarnessE2ETest(unittest.TestCase):
    """整脚本 vm 装载 + 真实派发点击——作用域/委托/进度框的端到端防线。"""

    def test_all_panel_buttons_reachable(self):
        self.assertTrue(HARNESS.exists(), "缺少 tools/dash_crash_harness.js 哨兵脚本")
        out = ROOT / ".pytest_cache" / "_dash_scope_e2e.txt"
        out.parent.mkdir(exist_ok=True)
        r = subprocess.run(
            ["node", str(HARNESS), str(HTML), str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=90)
        report = out.read_text(encoding="utf-8") if out.exists() else (r.stdout + r.stderr)
        self.assertIn("顶层执行未抛错", report, "顶层脚本执行抛错：\n" + report)
        for action in ("open-usage", "open-advice", "open-market"):
            self.assertIn(f"✅ {action}", report, f"{action} 点击链路断裂：\n{report}")
        self.assertIn("全部按钮点击链路端到端通过", report, "e2e 汇总失败：\n" + report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
