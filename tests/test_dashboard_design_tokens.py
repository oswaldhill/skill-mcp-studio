"""锁定 gui/dashboard.html 的设计 token 纪律。

这三条约束来自 taste-skill 的可迁移规则，都是"肉眼可见"的退化点：
1. Section 9.G：em-dash / en-dash 分隔符在任何可见位置都完全禁止。
   空值占位符必须用连字符，不能用 em-dash。
2. Shape Consistency Lock：圆角只能来自 --r-control / --r-card / --r-pill / --r-hair，
   不允许出现脱离 token 的一次性数值。
3. focus 可见性：任何 outline: none 必须同时提供等价的替代焦点反馈，
   否则键盘用户看不到焦点位置。
"""

import re
import unittest
from pathlib import Path
from tests._gui_source import page_html as _gui_source_page_html

ROOT = Path(__file__).resolve().parent.parent
HTML = _gui_source_page_html()


class TestNoVisibleDashPlaceholders(unittest.TestCase):
    """taste-skill 9.G：可见区域零 em-dash。"""

    def test_no_em_dash_empty_value_placeholder(self):
        # `|| "—"` 这类空值占位符会直接把 em-dash 渲染到界面上。
        self.assertNotIn(
            '|| "—"',
            HTML,
            "表格/详情里的空值占位符使用了 em-dash，会直接渲染到界面",
        )

    def test_placeholder_uses_hyphen(self):
        # 占位符统一用连字符（U+002D）。
        matches = re.findall(r'\|\|\s*"([^"]*)"', HTML)
        dashes = [m for m in matches if "\u2014" in m or "\u2013" in m]
        self.assertEqual(
            dashes,
            [],
            "存在把 em-dash/en-dash 当作兜底文本的表达式：%r" % (dashes,),
        )


class TestShapeConsistencyLock(unittest.TestCase):
    """Shape Consistency Lock：圆角只能取自既有 token。"""

    # 允许的圆角写法：token 变量、50%（正圆/胶囊）、0、以及 token 组合。
    ALLOWED_TOKEN = re.compile(r"var\(--r-(control|card|pill|hair)\)")

    def _radius_declarations(self):
        # 限定在单条 CSS 声明内，避免跨到 JS 模板字符串里。
        return re.findall(r'border-radius:\s*([^;<>"\n]+);', HTML)

    def test_no_off_scale_radius_values(self):
        offenders = []
        for value in self._radius_declarations():
            v = value.strip()
            # 允许：0、50%、纯 token、token 的多值组合（如 0 token token 0）
            parts = [p.strip() for p in v.split()]
            if all(
                p == "0"
                or p == "50%"
                or p == "var(--r-hair)"
                or self.ALLOWED_TOKEN.fullmatch(p)
                for p in parts
            ):
                continue
            offenders.append(v)
        self.assertEqual(
            offenders,
            [],
            "存在脱离 token 圆角刻度的 border-radius 声明：%r" % (offenders,),
        )

    def test_no_raw_px_radius(self):
        raw = re.findall(r'border-radius:\s*[^;<>"\n]*\d+px[^;<>"\n]*;', HTML)
        self.assertEqual(raw, [], "圆角出现硬编码 px 值：%r" % (raw,))

    def test_inline_style_radius_uses_token(self):
        # 内联 style 里的圆角也必须走 token。
        inline = re.findall(r'style="[^"]*border-radius:([^";]+)', HTML)
        bad = [v for v in inline if "var(--r-" not in v]
        self.assertEqual(bad, [], "内联 style 里出现非 token 圆角：%r" % (bad,))


class TestFocusFallback(unittest.TestCase):
    """键盘可达性：抑制 outline 就必须给出替代焦点反馈。"""

    def test_outline_none_always_has_box_shadow(self):
        offenders = []
        for line in HTML.splitlines():
            if re.search(r"outline:\s*(none|0)\b", line):
                # 同一条规则里必须给出替代反馈（焦点环或等效视觉）。
                if "box-shadow" not in line and "outline-offset" not in line:
                    offenders.append(line.strip())
        self.assertEqual(
            offenders,
            [],
            "以下规则抑制了 outline 却没有替代焦点反馈：%r" % (offenders,),
        )


POPOVER = ROOT / "gui" / "popover.html"


class TestAccessibilityContract(unittest.TestCase):
    """docs/DESIGN.md 第 3b 节的可访问性硬要求。

    规范里承诺了「键盘焦点可见」与「尊重减少动效」，但这两条此前没有门禁。
    规范自己的话说得很清楚：「没有测试的约定会在下一次改动里失效」。
    这里把它们钉死，新增动画或焦点样式时不会再悄悄漏掉。
    """

    def _pages(self):
        # dashboard 走 _gui_source（S10 后脚本已外置），popover 是独立页面
        return (("dashboard", HTML), ("popover", POPOVER.read_text(encoding="utf-8")))

    def test_every_page_respects_reduced_motion(self):
        for name, css in self._pages():
            with self.subTest(page=name):
                self.assertIn(
                    "prefers-reduced-motion",
                    css,
                    f"{name} 有动画/过渡却没有 prefers-reduced-motion 兜底",
                )

    def test_interactive_pages_declare_focus_visible(self):
        for name, css in self._pages():
            with self.subTest(page=name):
                self.assertIn(
                    "focus-visible",
                    css,
                    f"{name} 缺少 :focus-visible 焦点反馈",
                )

    def test_reduced_motion_actually_disables_animation(self):
        """光有 media query 不够，里面必须真的关掉动画。"""
        for name, css in self._pages():
            with self.subTest(page=name):
                idx = css.find("prefers-reduced-motion")
                block = css[idx: idx + 400] if idx >= 0 else ""
                self.assertTrue(
                    "animation: none" in block or "animation:none" in block
                    or "transition: none" in block or "transition:none" in block,
                    f"{name} 的 prefers-reduced-motion 块没有实际关闭动画/过渡",
                )


if __name__ == "__main__":
    unittest.main()
