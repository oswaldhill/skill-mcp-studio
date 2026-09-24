"""界面规范（docs/DESIGN.md）契约测试。

这些断言把"统一规范"钉死，防止后续改动重新引入字面值、幽灵样式或重复渲染。
规范本身是约定；没有测试的约定会在下一次改动里失效。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
SPEC = ROOT / "docs" / "DESIGN.md"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
