"""界面规范的「硬数字 / token / 反向镜像」契约（2026-10-10 评审增设）。

DESIGN.md 的「§2.9 组件硬数字」表声明了各弹窗/开关/间距的不可协商取值，
这些取值此前**没有任何门禁**，于是规范与代码系统性漂移：z-index 写 100/90、
代码用 50/51/60/70；开关写 36px、代码用 34px……照规范写代码会写出与现有
实现不一致的界面。本文件把规范表逐行比对 CSS 实际值，让漂移变成红灯。

另守三条评审发现的缺口：

1. **token 清单完整性**：规范自称「唯一取值来源」，但 :root 里有 22 个在用
   token 未登记（含 11 个 --sp- 扩展档）。一旦漏登，新人会「找不到就补」，
   造出重复 token 或字面值。这里断言 :root 的每个 token 都在规范里出现过。

2. **HTML ↔ MD 双向镜像**：此前只单向断言 MD→HTML，HTML 可单方面塞过期内容
   （实测 HTML 里写着「28 项」，实际 33）。现补反向断言，HTML 的每节也要在
   MD 中找到。

3. **emoji / cursor / 触达 / Esc**：规范 §3b / §5 承诺了「图标用 SVG 不用
   emoji」「可点元素 cursor:pointer」「弹层内 ≥32px」「弹层能 Esc 关」，
   但这些此前都没有门禁。这里补上。

为什么是静态断言：和 ``test_design_spec`` 同一思路 —— 要守的是**结构约束**
（规范表行 ↔ CSS 声明、token 是否登记），静态断言是最直接判据；真跑渲染会
引入浏览器依赖与几秒级延迟，不值得。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._gui_source import page_source

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "DESIGN.md"
SPEC_HTML = ROOT / "docs" / "DESIGN.html"


def _src() -> str:
    return page_source()


def _css() -> str:
    s = _src()
    body = s[s.index("<style>"):]
    return body[: body.index("</style>")]


def _root_block() -> str:
    m = re.search(r":root\s*\{(.*?)\n  \}", _src(), re.S)
    assert m is not None, "dashboard.html 里找不到 :root 块"
    return m.group(1)


def _rule_body(selector: str) -> str:
    """从 CSS 里取某选择器的声明体（粗略：匹配第一个不跨块的花括号区）。"""
    pat = re.escape(selector)
    m = re.search(
        r"(?:^|\n)\s*" + pat + r"\s*\{([^}]*)\}",
        _css(),
    )
    return m.group(1).strip() if m else ""


def _decl(selector: str, prop: str) -> str:
    """取某选择器下某属性的值（去注释后）。"""
    body = _rule_body(selector)
    m = re.search(prop + r"\s*:\s*([^;]+)", body)
    return m.group(1).strip() if m else ""


def _norm_ws(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()


class SpacingLiteralRatchetTest(unittest.TestCase):
    """间距字面值**棘轮**：只许减少，不许增加。

    评审发现：规范检查清单写着「间距走 `--gap-*` / `--sp-*`，不散落字面值」，
    但实测有 265 条间距声明含字面 px，且**没有任何门禁** —— 承诺与事实不符。

    为什么不上「零字面值」硬门禁：这些声明用到的值里有 ``5 / 13 / 22 / 26 /
    36 / 64px``，**:root 里根本没有对应 token**。要清零就得为一个值发明一个
    扩展档（凭空扩表 6 档），或重写 265 行 —— 前者污染唯一的取值来源，后者是
    与本次评审无关的大规模改动，且视觉上无法由我验证。

    因此采用业界处理存量债的标准做法：**冻结基线 + 只许降不许升**。
    新写的间距必须用 token；顺手偿还存量时把基线一起收紧。
    """

    # 基线 = 2026-10-10 评审时的实测值（482 条间距声明中 265 条含字面 px）。
    BASELINE = 265

    _PAT = re.compile(
        r"(?:padding|margin|gap|row-gap|column-gap)(?:-[a-z]+)?\s*:\s*([^;]+);"
    )

    def _literal_spacing_decls(self) -> list[str]:
        return [
            v.strip()
            for v in self._PAT.findall(_css())
            if re.search(r"[0-9]+px", v)
        ]

    def test_literal_spacing_does_not_grow(self):
        found = self._literal_spacing_decls()
        self.assertLessEqual(
            len(found),
            self.BASELINE,
            "间距字面值变多了（%d > 基线 %d）。新增间距请用 "
            "`--gap-*` / `--sp-*`（含扩展档）；确需新档位先在规范 §1 登记。"
            % (len(found), self.BASELINE),
        )

    def test_baseline_is_not_silently_stale(self):
        """基线必须随偿还同步收窄：差距过大说明这条棘轮名存实亡。

        留 29 条余量 —— 允许零散偿还而不必每次改基线，但不允许长期挂着虚高基线。
        """
        found = len(self._literal_spacing_decls())
        self.assertGreater(
            found,
            self.BASELINE - 30,
            "字面值已降到 %d（基线 %d），请把 BASELINE 收紧到实测值附近 —— "
            "否则这条棘轮会失去约束力。" % (found, self.BASELINE),
        )


class MonoUsageContractTest(unittest.TestCase):
    """规范 §1 字体锁 / 2.4：数字、包名、路径、版本号一律 `--mono`。

    此前无门禁。实际做法是 ``.mono`` 工具类 + ``font-family: var(--mono)``；
    这里锁住「工具类真的用 mono 字体」与「路径单元格必须带 mono」，
    避免新写路径/版本展示时漏掉等宽字体。
    """

    def test_mono_utility_class_uses_mono_token(self):
        body = _rule_body(".mono")
        self.assertIn(
            "var(--mono)",
            body,
            ".mono 工具类没有用 --mono 字体 —— 字体锁失效",
        )

    def test_path_cells_always_carry_mono(self):
        src = _src()
        classes = re.findall(r'class="([^"]*path-cell[^"]*)"', src)
        self.assertTrue(classes, "找不到任何 path-cell（路径单元格），断言失去意义")
        offenders = [c for c in classes if "mono" not in c]
        self.assertEqual(
            offenders,
            [],
            "路径单元格缺少 mono 类（规范 2.4：路径用 --mono）：%r" % offenders,
        )


class HardNumbersContractTest(unittest.TestCase):
    """规范 §2.9 表的每一行必须与 CSS 实际值逐字节一致（或 token 等价）。"""

    # (selector, property, spec_value)。这些取自 DESIGN.md §2.9 表，
    # 改代码必须同步改规范 —— 二者由本表交叉锁定。
    CONTRACT = [
        (".modal", "width", "var(--modal-w, min(560px, 92vw))"),
        (".cfm-card", "--modal-w", "min(400px, 94vw)"),
        (".sheet", "width", "min(560px, 94vw)"),
        (".modal-backdrop", "z-index", "50"),
        (".sheet-backdrop", "z-index", "50"),
        (".sheet", "z-index", "51"),
        (".palette", "z-index", "60"),
        ("dialog.busy-backdrop", "z-index", "70"),
        (".switch", "width", "34px"),
        (".switch", "height", "20px"),
        (".switch .sw-knob", "width", "16px"),
        (".switch[aria-checked=\"true\"] .sw-track", "background", "var(--accent-strong)"),
        ("main", "padding", "var(--sp-9) 28px 64px"),
        (".card", "padding", "var(--sp-7)"),
        (".list-row", "padding", "var(--sp-4) 14px"),
        (".pagination button", "padding", "var(--sp-1) 9px"),
        (".path-field-row button", "padding", "var(--sp-1) 8px"),
        (".chg-btn", "min-height", "32px"),
        (".insight-dialog", "width", "min(1040px, 100%)"),
    ]

    def test_contract_rows_appear_in_spec(self):
        """CONTRACT 的每一行必须出现在 DESIGN.md §2.9 表里。

        防的是「只改代码、忘了回写规范表」：本测试的硬编码清单与规范表必须对齐。
        """
        md = SPEC.read_text(encoding="utf-8")
        section = md[md.index("2.9 组件硬数字"):]
        missing = []
        for sel, prop, val in self.CONTRACT:
            if sel not in section or val not in section:
                missing.append(f"{sel} / {prop} / {val}")
        self.assertEqual(
            missing,
            [],
            "§2.9 表缺少这些行（改代码时忘了回写规范）：%r" % missing,
        )

    def test_css_matches_contract(self):
        """CSS 实际值必须与 §2.9 表一致。

        ``--modal-w`` 是 CSS 自定义属性，取的是声明而非普通属性，单独处理。
        """
        offenders = []
        for sel, prop, expected in self.CONTRACT:
            if prop.startswith("--"):
                got = _decl(sel, prop)
            else:
                got = _decl(sel, prop)
            if _norm_ws(got) != _norm_ws(expected):
                offenders.append(
                    f"{sel} {prop}: 规范={expected!r} 代码={got!r}"
                )
        self.assertEqual(
            offenders[:15],
            [],
            "§2.9 表与 CSS 实际值不一致（改代码必须同步改规范，反之亦然）：\n"
            + "\n".join(offenders[:15]),
        )


class TouchTargetContractTest(unittest.TestCase):
    """规范 §2.9 触达目标：弹层内动作按钮必须显式 min-height: 32px。"""

    BUTTONS = (
        ".cfm-card .actions button",
        ".modal-form .form-actions button",
        ".sheet-actions .btn-soft",
        ".chg-btn",
    )

    def test_overlay_action_buttons_declare_32px(self):
        offenders = []
        for sel in self.BUTTONS:
            mh = _decl(sel, "min-height")
            if mh != "32px":
                offenders.append(f"{sel}: min-height={mh!r}（应为 32px）")
        self.assertEqual(
            offenders,
            [],
            "弹层内动作按钮未声明 min-height: 32px：\n" + "\n".join(offenders),
        )


class TokenRegistryCompletenessTest(unittest.TestCase):
    """规范自称「唯一取值来源」—— :root 的每个 token 都必须在规范里登记。"""

    # 规范里用「+ 各自 -bg / -border」一行统一涵盖语义态的 bg/border，
    # 这些按模式豁免（不算漏登）。
    _PATTERN_COVERED = re.compile(
        r"--(?:ok|warn|err)-(?:bg|border)\b"
    )

    def test_every_root_token_appears_in_spec(self):
        root = _root_block()
        tokens = set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", root))
        md = SPEC.read_text(encoding="utf-8")
        md_tokens = set(re.findall(r"`(--[a-zA-Z0-9-]+)`", md))
        # 规范表里也以 ``--token``(取值) 形式出现，一并纳入。
        md_tokens |= set(re.findall(r"`(--[a-zA-Z0-9-]+)\(", md))

        missing = []
        for t in sorted(tokens):
            if t in md_tokens:
                continue
            if self._PATTERN_COVERED.match(t):
                continue
            missing.append(t)
        self.assertEqual(
            missing[:20],
            [],
            "以下 :root token 在 DESIGN.md 里未登记（规范自称唯一取值来源，"
            "漏登会诱发重复 token 或字面值）：%r" % missing[:20],
        )


class EmojiAsIconBanTest(unittest.TestCase):
    """规范 §3b：图标用 SVG，不用 emoji 当 UI 图标。

    判据：剥离注释与「CLI 输出探测正则」后，HTML 标签文本与 JS 字符串字面量里
    不得出现 emoji（U+1F300–U+1FAFF 杂项符号与象形、以及常用符号区 U+2600–U+27BF）。
    注释里的提及（含本测试引用的）不算；``/❌|.../`` 这类正则不算。
    """

    EMOJI = re.compile(
        "[\U0001F300-\U0001FAFF\u2600-\u27BF]"
    )

    @staticmethod
    def _strip(text: str) -> str:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"//[^\n]*", "", text)
        # JS 正则字面量整段抹掉：``/❌|Refused|.../i`` 是 CLI 输出探测，
        # ``/[—–]/g`` 是把 em-dash 归一成连字符的清洗器 —— 二者都不是 UI 图标。
        # 用「内容不含 ``/`` 与换行」限定，避免误吞 URL 里的路径分隔（URL 不含 emoji，
        # 误吞对 emoji 判定也无影响）。
        text = re.sub(r"/[^/\n]+/[gimsuy]*", "", text)
        return text

    def test_dashboard_no_emoji_icon(self):
        cleaned = self._strip(_src())
        offenders = []
        for i, line in enumerate(cleaned.splitlines(), 1):
            if self.EMOJI.search(line):
                offenders.append(f"line {i}: {line.strip()[:90]}")
        self.assertEqual(
            offenders[:10],
            [],
            "dashboard.html 出现 emoji 当 UI 图标（规范 3b 禁止）：\n"
            + "\n".join(offenders[:10]),
        )

    def test_popover_no_emoji_icon(self):
        pop = (ROOT / "gui" / "popover.html").read_text(encoding="utf-8")
        cleaned = self._strip(pop)
        offenders = []
        for i, line in enumerate(cleaned.splitlines(), 1):
            if self.EMOJI.search(line):
                offenders.append(f"line {i}: {line.strip()[:90]}")
        self.assertEqual(
            offenders[:10],
            [],
            "popover.html 出现 emoji 当 UI 图标（规范 3b 禁止）：\n"
            + "\n".join(offenders[:10]),
        )

    def test_svgs_use_unified_viewbox(self):
        """已有的 SVG 图标必须统一 viewBox=0 0 24 24（规范 3b）。"""
        for f in ("gui/dashboard.html", "gui/popover.html"):
            d = (ROOT / f).read_text(encoding="utf-8")
            boxes = set(re.findall(r'<svg[^>]*viewBox="([^"]+)"', d))
            with self.subTest(file=f):
                self.assertTrue(boxes, f"{f} 没有任何带 viewBox 的 <svg>")
                self.assertEqual(
                    {"0 0 24 24"},
                    boxes,
                    f"{f} 的 svg viewBox 不统一：{boxes}",
                )


class CursorPointerContractTest(unittest.TestCase):
    """规范 §3b：可点元素有 cursor: pointer。

    覆盖方式：基础 ``button`` 规则必须含 cursor:pointer（所有按钮元素因此达标）；
    另外一批非 ``<button>`` 的可点组件（开关、导航项、菜单项）各自必须声明。
    """

    BASE = "button"
    NON_BUTTON_INTERACTIVE = (
        ".switch",
        ".nav-item",
        ".pal-item",
    )

    def test_base_button_has_pointer(self):
        self.assertIn(
            "cursor: pointer",
            _rule_body(self.BASE),
            "基础 button 规则缺少 cursor: pointer —— 所有按钮的可达性依赖它",
        )

    def test_non_button_interactive_have_pointer(self):
        offenders = []
        for sel in self.NON_BUTTON_INTERACTIVE:
            if "cursor: pointer" not in _rule_body(sel):
                offenders.append(sel)
        self.assertEqual(
            offenders,
            [],
            "非 button 可点元素缺少 cursor: pointer：%r" % offenders,
        )


class OverlayEscContractTest(unittest.TestCase):
    """规范 §3b/§5：弹层能自然关闭（失焦收起 / Esc）。

    判据：每个弹层根容器要么是原生 ``<dialog>``（浏览器原生 Esc 关闭），
    要么在全局 keydown 的 Escape 分支里被显式关闭。
    """

    def test_overlays_are_esc_closable(self):
        src = _src()
        # 原生 <dialog> 元素：浏览器按 Esc 触发 cancel → 默认关闭。
        dialog_ids = set(re.findall(r'<dialog\s+[^>]*id="([^"]+)"', src))
        # 全局 keydown 里 Escape 分支关闭了哪些（按 closeXxx / .close() 调用名粗抓）。
        esc_block = ""
        m = re.search(r'e\.key === "Escape"\s*\{(.*?)\}', src, re.S)
        if m:
            esc_block = m.group(1)
        # 已知弹层根 id（来自 §2.9 / 2.5b）。
        known_overlays = (
            "modal-root",
            "busy-root",
            "market-panel",
            "insight-panel",
        )
        offenders = []
        for oid in known_overlays:
            if oid in dialog_ids:
                continue
            if oid in esc_block or "closeModal" in esc_block or "closePop" in esc_block:
                # 由 closeModal/closePop 间接关闭也算
                continue
            offenders.append(oid)
        self.assertEqual(
            offenders,
            [],
            "这些弹层根既不是 <dialog> 也不在 Escape 分支里：%r" % offenders,
        )


class PrimaryGranularityTest(unittest.TestCase):
    """规范 §2.1：primary 的「一屏一个」改为「同一操作区一个」。

    防的是评审发现的内部矛盾：§2.1 说一屏一个，§2.7 又让每张变更卡的
    「修复」都用 primary —— N 张卡 = N 个 primary。规范必须把粒度说清。
    """

    def test_spec_states_per_region_granularity(self):
        text = SPEC.read_text(encoding="utf-8")
        # 锚到 §2.1 硬规则段的原文，而不是泛查「操作区」（§5 清单里也有，
        # 只改 §2.1 仍会通过）。同时禁旧的「一屏只允许一个」表述。
        self.assertIn(
            "**同一操作区**只允许一个 `primary`",
            text,
            "规范 §2.1 未用「同一操作区」定义 primary 的粒度 —— "
            "一屏一个 vs 每卡一个的矛盾未解",
        )
        self.assertNotIn(
            "一屏只允许一个 `primary`",
            text,
            "规范仍保留旧的「一屏只允许一个 primary」表述 —— "
            "这与 §2.7「每张变更卡各一个 primary」矛盾",
        )


class HtmlMdReverseMirrorTest(unittest.TestCase):
    """反向镜像：HTML 可读版的每节也必须能在 MD 中找到。

    此前只有 MD→HTML 单向（test_design_spec.HtmlMirrorTest），HTML 可单方面塞
    过期内容（实测 HTML 写着「28 项」而实际 33）。补反向断言。
    """

    @staticmethod
    def _html_section_cores() -> list[str]:
        html = SPEC_HTML.read_text(encoding="utf-8")
        heads = re.findall(r"<h([23])[^>]*>(.*?)</h\1>", html, re.S)
        cores = []
        for level, raw in heads:
            txt = re.sub(r"<[^>]+>", "", raw)
            txt = re.sub(r"\s+", " ", txt).strip()
            # 去掉行首编号前缀（如 "2.9 "）与锚点 "附：" 前缀
            txt = re.sub(r"^[0-9a-z.]+\s*", "", txt).strip()
            txt = txt.split("（")[0].strip()
            txt = txt.lstrip("附：").rstrip("#").strip()
            if txt:
                cores.append(txt)
        return cores

    def test_every_html_section_appears_in_md(self):
        """HTML 的每个章节标题（核心词）必须在 MD 里作为**章节标题**出现。

        只查「核心词在 MD 正文里出现过」太宽 —— 「可视化样例」在 MD 的 §1b
        正文段落里也有，于是把标题删掉仍判通过。改为：核心词必须在 MD 的
        ``#``/``##``/``###`` 标题行里出现。
        """
        md = SPEC.read_text(encoding="utf-8")
        md_headlines = [
            re.sub(r"^[#]+\s*", "", line).split("（")[0].strip()
            for line in md.splitlines()
            if line.startswith("#")
        ]
        missing = []
        for core in self._html_section_cores():
            if core and not any(core in h for h in md_headlines):
                missing.append(core)
        self.assertEqual(
            missing[:20],
            [],
            "以下 HTML 章节在 DESIGN.md 的标题里找不到（HTML 单方面新增/未同步）：%r"
            % missing[:20],
        )


if __name__ == "__main__":
    unittest.main()
