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
    """taste-skill 9.G：可见区域零 em-dash / en-dash。

    规范措辞是「正文、标题、标签、按钮文案一律禁用」，不止 ``|| "—"`` 一种
    写法。此前门禁只查那一种，把所有别处出现 em-dash 的情况都放过了
    （2026-10-10 评审：实际 38 行含 em-dash，全在代码注释里，靠运气干净）。
    现在覆盖**全量可见文案**：剥离注释后，凡出现在 HTML 标签文本或
    innerHTML/textContent 等字符串字面量里的 em/en-dash 都算违规。
    注释里的（含本测试自己引用的）不算；正则字符类 ``/[—–]/`` 是「把 em-dash
    归一成连字符」的清洗器，保留。
    """

    @staticmethod
    def _strip_comments(text: str) -> str:
        """去掉 // 行注释与 /* */ 块注释，但不碰字符串内部。

        粗暴实现即可：em-dash 不可能出现在选择器/CSS 属性名里，注释剥离后
        剩余的 em-dash 只可能来自可见字符串，这正是要拦的。
        """
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"//[^\n]*", "", text)
        return text

    @staticmethod
    def _strip_regex_classes(text: str) -> str:
        """允许 ``/[—–]/`` 这种归一化正则：把字符类整段抹掉再判。"""
        return re.sub(r"""/\[[^\]]*\]/[gimsuy]*""", "", text)

    def test_no_em_dash_empty_value_placeholder(self):
        self.assertNotIn(
            '|| "—"',
            HTML,
            "表格/详情里的空值占位符使用了 em-dash，会直接渲染到界面",
        )

    def test_placeholder_uses_hyphen(self):
        matches = re.findall(r'\|\|\s*"([^"]*)"', HTML)
        dashes = [m for m in matches if "\u2014" in m or "\u2013" in m]
        self.assertEqual(
            dashes,
            [],
            "存在把 em-dash/en-dash 当作兜底文本的表达式：%r" % (dashes,),
        )

    def test_no_em_dash_in_visible_strings(self):
        """剥离注释与归一化正则后，可见字符串里不许出现 em/en-dash。"""
        cleaned = self._strip_regex_classes(self._strip_comments(HTML))
        offenders = []
        for i, line in enumerate(cleaned.splitlines(), 1):
            if "\u2014" in line or "\u2013" in line:
                # 只记前几处，避免输出过长
                offenders.append(f"line {i}: {line.strip()[:100]}")
        self.assertEqual(
            offenders[:10],
            [],
            "剥离注释后仍有 em/en-dash 落在可见文案里：\n" + "\n".join(offenders[:10]),
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


class TestSemanticModifierTokens(unittest.TestCase):
    """语义修饰类（`.list-meta.is-*`）只许用语义 token 着色。

    v0.31.1 为「登记失效」（missing）新增 `.list-meta.is-err`。这类修饰类的
    全部价值就是「语义，而不是某个具体颜色」，一旦有人写成字面色值，暗色主题
    就会失配。规范 §1 已写死这条（颜色一致性锁），这里把它钉住。
    """

    def test_list_meta_modifiers_use_semantic_tokens(self):
        decls = re.findall(r"\.list-meta\.(is-[a-z]+)\s*\{([^}]*)\}", HTML)
        self.assertTrue(decls, "未找到 .list-meta 的语义修饰类")
        for name, body in decls:
            with self.subTest(modifier=name):
                colors = re.findall(r"color:\s*([^;]+);", body)
                self.assertTrue(colors, f".list-meta.{name} 没有 color 声明")
                for c in colors:
                    self.assertRegex(
                        c.strip(),
                        r"^var\(--(ok|warn|err|faint|muted|accent[a-z-]*)\)$",
                        f".list-meta.{name} 的颜色必须来自语义 token：{c!r}")

    def test_missing_state_modifier_exists(self):
        """missing 态必须有独立的语义着色（不能复用 faint 蒙混过去）。"""
        self.assertIn(".list-meta.is-err", HTML,
                      "missing 态应使用 .list-meta.is-err 着色")

    def test_spec_documents_the_missing_state(self):
        """双轨：代码里的第四态必须在规范里有对应文字（含英文状态名）。"""
        md = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
        html = (ROOT / "docs" / "DESIGN.html").read_text(encoding="utf-8")
        for label, text in (("DESIGN.md", md), ("DESIGN.html", html)):
            with self.subTest(doc=label):
                self.assertIn("missing", text, f"{label} 未记录 missing 状态")
                self.assertIn("登记失效", text, f"{label} 未记录「登记失效」文案")
