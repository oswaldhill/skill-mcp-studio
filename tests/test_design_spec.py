"""界面规范（docs/DESIGN.md）契约测试。

这些断言把"统一规范"钉死，防止后续改动重新引入字面值、幽灵样式或重复渲染。
规范本身是约定；没有测试的约定会在下一次改动里失效。
"""
import re
import unittest
from pathlib import Path
from tests._gui_source import page_source

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
SPEC = ROOT / "docs" / "DESIGN.md"


def _src() -> str:
    # S10 前置：取源统一到 tests/_gui_source.page_source()，
    # 使断言不再依赖「脚本内联在 HTML 里」这一布局细节。
    return page_source()


def _css() -> str:
    s = _src()
    body = s[s.index("<style>"):]
    return body[: body.index("</style>")]


def _css_without_tokens() -> str:
    """去掉 :root / html.dark 两个 token 定义块后的 CSS。"""
    c = _css()
    c = re.sub(r":root\s*\{.*?\n  \}", "", c, flags=re.S)
    c = re.sub(r"html\.dark\s*\{.*?\n  \}", "", c, flags=re.S)
    return c


class SpecDocumentTest(unittest.TestCase):
    """规范必须是一份可查的实体，而不是口头约定。"""

    def test_spec_document_exists(self):
        self.assertTrue(SPEC.exists(), "缺少 docs/DESIGN.md")
        text = SPEC.read_text(encoding="utf-8")
        for section in ("Token 体系", "组件规约", "状态覆盖", "检查清单"):
            self.assertIn(section, text, f"规范缺少「{section}」")

    def test_spec_declares_scope_boundary(self):
        """本项目是管理台，规范里必须写明不套用落地页配方。"""
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("管理台", text)
        self.assertIn("不适用于本项目", text)


class NoLiteralValuesTest(unittest.TestCase):
    """规范 1：颜色/字号/圆角/阴影必须取自 token，不得写字面值。"""

    def test_no_hardcoded_font_size(self):
        left = re.findall(r"font-size:\s*[0-9.]+px", _css_without_tokens())
        self.assertEqual(left, [], f"仍有硬编码字号 {left}，应改用 var(--fs-*)")

    def test_no_hardcoded_border_radius(self):
        """圆角只允许四档 token。.modal 弹窗容器是唯一保留的字面值（规范中单列）。"""
        c = _css_without_tokens()
        offenders = []
        for block in re.finditer(r"([^{}]+)\{([^}]*)\}", c):
            selector, body = block.group(1).strip(), block.group(2)
            if ".modal" in selector:          # 弹窗容器专用档
                continue
            for v in re.findall(r"border-radius:\s*([0-9]+px)", body):
                offenders.append(f"{selector} -> {v}")
        self.assertEqual(offenders, [],
                         f"仍有硬编码圆角 {offenders}，应改用 var(--r-*)")

    def test_no_hardcoded_color(self):
        left = re.findall(r"#[0-9A-Fa-f]{3,8}\b", _css_without_tokens())
        self.assertEqual(left, [], f"仍有硬编码颜色 {left}，应改用颜色 token")

    def test_radius_tier_tokens_exist(self):
        c = _css()
        for t in ("--r-hair", "--r-control", "--r-card", "--r-pill"):
            self.assertIn(t + ":", c, f"缺少圆角档位 {t}")

    def test_single_accent_color(self):
        """颜色一致性锁：强调色只有一个来源。"""
        c = _css()
        root = re.search(r":root\s*\{(.*?)\n  \}", c, re.S).group(1)
        self.assertIn("--accent:", root)
        self.assertIn("--on-solid:", root, "实体白色需要独立 token，不能散落 #fff")


class ListRowComponentTest(unittest.TestCase):
    """规范 2.2：同类条目用列表行，不是一长串卡片或裸文本。"""

    def test_list_row_styles_defined(self):
        c = _css()
        for cls in (".list-rows", ".list-row", ".list-main", ".list-title", ".list-meta"):
            self.assertIn(cls + " ", c + " ", f"缺少列表行组件样式 {cls}")

    def test_market_uses_list_row(self):
        """市场结果必须用列表行渲染，且不得再有未定义样式的旧类。"""
        src = _src()
        self.assertNotIn('className = "market-result"', src,
                         "market-result 是无样式定义的幽灵类，应改用 list-row")
        self.assertIn('"list-row"', src)

    def test_market_row_builder_exists(self):
        self.assertIn("function marketRow(", _src())
        self.assertIn("function marketEmpty(", _src())


class NoDuplicateRenderTest(unittest.TestCase):
    """规范 5：同一信息不得在同一屏出现两次。"""

    def test_search_results_not_duplicated_into_progress(self):
        m = re.search(r"function renderMarketResults\(.*?\n  \}", _src(), re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertNotIn("appendMarketProgress", body,
                         "搜索结果不应再往进度区重复输出一遍")


class InstallsLocalizationTest(unittest.TestCase):
    """规范 2.4：数量单位中文化，不直接透出上游英文原文。"""

    def test_fmt_installs_exists_and_localizes(self):
        src = _src()
        self.assertIn("function fmtInstalls(", src)
        self.assertIn("万次安装", src)
        self.assertIn("亿次安装", src)

    def test_market_row_uses_fmt_installs(self):
        m = re.search(r"function renderMarketResults\(.*?\n  \}", _src(), re.S)
        self.assertIn("fmtInstalls(", m.group(0))


class EmptyStateTest(unittest.TestCase):
    """规范 2.5：空状态要说清原因与出路，且空容器不占位。"""

    def test_empty_containers_collapse(self):
        self.assertIn(".market-lines:empty", _css())

    def test_market_empty_gives_reason_and_hint(self):
        m = re.search(r"function renderMarketResults\(.*?\n  \}", _src(), re.S)
        self.assertIn("marketEmpty(", m.group(0))


class ButtonSystemTest(unittest.TestCase):
    """规范 2.1：按钮变体必须登记在册；分段控件不被当作按钮要求。"""

    def test_spec_registers_button_variants(self):
        text = SPEC.read_text(encoding="utf-8")
        for v in ("btn-soft", "primary", "ghost", "danger",
                  "btn-save", "cfm-btn-danger", "ad-clean-btn"):
            self.assertIn(v, text, f"规范未登记按钮变体 {v}")

    def test_spec_excludes_segmented_controls(self):
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("不是按钮的控件", text)
        for v in ("seg-btn", "view-btn", "settings-tab", "nav-item", "pm-item"):
            self.assertIn(v, text)


class ContrastTokenTest(unittest.TestCase):
    """规范 1 / 2.1：强调色上的文字必须用 --on-accent，不得写 #fff 字面值。"""

    def test_no_literal_white_in_style(self):
        c = _css_without_tokens()
        self.assertNotIn("#fff", c.lower(), "正文样式里仍有 #fff，应改用 --on-accent/--on-solid")

    def test_on_accent_and_on_solid_tokens_exist(self):
        c = _css()
        self.assertIn("--on-accent:", c)
        self.assertIn("--on-solid:", c)


SPEC_HTML = ROOT / "docs" / "DESIGN.html"


class HtmlMirrorTest(unittest.TestCase):
    """规范的 HTML 可读版必须与 Markdown 正文保持同步。

    为什么要这条：`docs/DESIGN.html` 是给人读的规范，`docs/DESIGN.md` 是
    唯一设计依据。两份一旦分叉，读 HTML 的人会照着过期规则写代码。此前
    没有任何测试检查 HTML，属于典型的「会静默失效」的缺口。

    判据刻意取**粗粒度**（章节标题与关键 token 名），理由是：
    HTML 是重新排版的呈现层，逐字比对 Markdown 会因排版差异产生海量误报，
    最终被绕过。这里只保证「MD 里的每个小节在 HTML 里都能找到」。
    """

    def test_html_mirror_exists(self):
        self.assertTrue(SPEC_HTML.is_file(), "缺少 docs/DESIGN.html（规范的 HTML 可读版）")

    def test_every_md_section_appears_in_html(self):
        md = SPEC.read_text(encoding="utf-8")
        html = SPEC_HTML.read_text(encoding="utf-8")
        heads = [h.strip() for h in re.findall(r"^#{2,3}\s+(.+)$", md, re.M)]
        self.assertTrue(heads, "DESIGN.md 里没有解析到任何小节标题")
        missing = []
        for h in heads:
            # 去掉 markdown 记号与编号前缀后取核心词
            core = re.sub(r"[`*]", "", h)
            core = core.split("（")[0].strip()
            core = re.sub(r"^[0-9a-z.]+\s*", "", core).strip()
            if core and core not in html:
                missing.append(h)
        self.assertEqual(
            missing,
            [],
            "以下小节只存在于 DESIGN.md，HTML 可读版未同步：%r" % (missing,),
        )

    def test_html_declares_both_themes(self):
        """规范要求「深浅两套 token 同步维护」，可读版自己也必须做到。

        判据必须是**真正的 CSS 规则块**，而不是「页面里出现过 html.dark
        这个字符串」：实测该串在样式注释里也有一处，只查子串会让断言在
        删掉整个深色块后依然通过（反向验证当场抓到）。
        这里改为要求规则块存在、且块内确实重新定义了深色取值。
        """
        html = SPEC_HTML.read_text(encoding="utf-8")
        blocks = re.findall(r"html\.dark\s*\{(.*?)\}", html, re.S)
        self.assertTrue(blocks, "HTML 可读版缺少 html.dark 规则块（深色主题）")
        dark = blocks[0]
        # 深色块必须真的覆盖表面与文字色，而不是空壳
        for token in ("--bg:", "--panel:", "--text:", "--accent:"):
            with self.subTest(token=token):
                self.assertIn(
                    token, dark,
                    f"html.dark 块内未重定义 {token}，深色主题不完整",
                )

    def test_html_uses_project_tokens_not_literal_colors(self):
        """可读版必须用项目 token，否则它自己就成了反例。"""
        html = SPEC_HTML.read_text(encoding="utf-8")
        for token in ("--accent", "--line", "--text", "--r-control", "--r-card"):
            with self.subTest(token=token):
                self.assertIn(token, html, f"HTML 可读版未使用项目 token {token}")

    def test_html_respects_reduced_motion(self):
        html = SPEC_HTML.read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", html, "HTML 可读版没有减少动效兜底")


if __name__ == "__main__":
    unittest.main()
