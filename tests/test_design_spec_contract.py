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


class NoLiteralSpacingTest(unittest.TestCase):
    """间距字面值必须为**零**（严格门禁，2026-10-10 清偿后启用）。

    评审发现规范检查清单承诺「间距不散落字面值」，而实测有 265 条间距声明
    含字面 px 且无门禁。清偿分两步：

    1. 先按「冻结基线棘轮」止血（只许减不许增）；
    2. 再为 **:root 缺档**的 6 个值（5/13/22/26/36/64px）补登记扩展档
       （`--sp-1a` / `--sp-5c` / `--sp-8a` / `--sp-9d` / `--sp-9e` / `--sp-9f`）
       与 gap 族的 `--gap-6`，然后把 265 条声明**值等价替换**为同值 token
       （替换前后每条声明解析后的取值逐个相同，渲染结果不变）。

    于是棘轮可以退役、换成零容忍：新增间距必须用 token，字面值一律拦下。
    """

    # 覆盖**全文件**：<style> 块 + 内联 style 属性（后者此前被漏掉，
    # 评审时只查 _css() 会误判为「已清零」——实测内联里还有 18 处）。
    _PAT = re.compile(
        r"(?:padding|margin|gap|row-gap|column-gap)(?:-[a-z]+)?\s*:\s*([^;{}\"\']+)"
    )

    def test_no_literal_px_in_spacing(self):
        offenders = [
            v.strip()
            for v in self._PAT.findall(page_source())
            if re.search(r"[0-9]+px", v)
        ]
        self.assertEqual(
            offenders,
            [],
            "间距声明里仍有字面 px（应改用 `--gap-*` / `--sp-*`；"
            "确需新档位先在规范 §1 登记）：%r" % offenders[:10],
        )

    def test_spacing_tokens_are_all_used(self):
        """新登记的扩展档必须真的被引用，不能是死 token。"""
        root = _root_block()
        c = _css()
        declared = set(re.findall(r"(--sp-[a-z0-9]+|--gap-[a-z0-9]+)\s*:", root))
        unused = sorted(
            t for t in declared
            if t not in ("--gap-0",) and f"var({t})" not in c
        )
        self.assertEqual(
            unused,
            [],
            "以下间距 token 已定义但无人引用（死 token）：%r" % unused,
        )

    def test_gap_family_stays_in_gap_tokens(self):
        """gap / row-gap / column-gap 只许用 `--gap-*`，不跨族用 `--sp-*`。

        规范 §1 把两族分开：gap 管 flex/grid 间距，sp 管 padding/margin 竖向。
        实测 141 处 gap 声明全部在 gap 族内；此断言锁住该不变量 —— 一旦混用，
        「哪档给谁」就无从判断，本次「间距清零」正是靠族约定才做到映射唯一。
        """
        offenders = []
        for m in re.finditer(r"\b(gap|row-gap|column-gap)\s*:\s*([^;]+);", page_source()):
            for t in re.findall(r"var\((--[a-z0-9-]+)\)", m.group(2)):
                if not t.startswith("--gap-"):
                    offenders.append(f"{m.group(1)}: {m.group(2).strip()} -> {t}")
        self.assertEqual(
            offenders[:10],
            [],
            "gap 族声明里出现了非 --gap-* token（应改用 --gap-*）：%r" % offenders[:10],
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


class ComponentRegistrationTest(unittest.TestCase):
    """组件/类名登记门禁（2026-10-11 评审后新增，补齐最大一处盲区）。

    ## 为什么需要它

    规范 §2.1 写着「新增按钮变体时必须回来登记到本表」、§5 清单写着
    「若新增组件或变体，已回写本文件对应章节」—— **这两条承诺此前没有任何门禁**。
    原有的 ``TokenRegistryCompletenessTest`` 只覆盖 ``:root`` 的 **CSS token**，
    完全不覆盖**类名/组件**。

    后果实测（本次评审发现）：上一轮把 emoji 换成 CSS 类时新增了
    ``.dot-ok`` / ``.dot-warn`` / ``.dot-idle`` / ``.th-ico`` 四个类，
    **一个都没回写规范**，而 51 条门禁全绿 —— 规范的核心承诺被静默绕过。

    ## 三条判据

    1. **幽灵引用**：规范里反引号写的 ``\`.foo\``` 必须真的存在于 GUI 代码。
       抓的是 §2.6 那种「整节基于不存在的 ``.toolbar``」的漂移。
    2. **新增语义类必须登记**：与冻结基线（``tests/_component_baseline.txt``）
       相比，**基线之外新增**的语义类必须先登记到规范，否则失败。
    3. **必须登记的组件仍在册**：核心语义组件（下表）必须在规范里出现，
       防止有人把它们从规范里删掉。

    ## 粒度（为什么不拦全部 499 个类）

    规范 §附「粒度」明确：只守有独立语义的顶层组件，不要为每个内部类名建门禁。
    所以判据 2 只针对**语义候选**（类名含 ``card``/``row``/``dot``/``pill`` 等
    组件词），且用**基线冻结**而非全量白名单 —— 存量 147 个语义类不强迫补登记，
    只要求**新增的**先登记。
    """

    BASELINE = ROOT / "tests" / "_component_baseline.txt"

    # 与基线生成脚本保持一致：类名按 "-" 切分后，任一段命中即为语义候选。
    SEMANTIC_TOKENS = frozenset({
        "card", "row", "panel", "modal", "sheet", "dialog", "list", "bar",
        "table", "menu", "tab", "field", "pill", "dot", "badge", "banner",
        "toast", "chip", "tag", "switch", "pagination", "toolbar", "btn",
        "button", "grid", "popover", "alert", "tooltip", "avatar", "legend",
        "ico", "icon", "stepper", "drawer", "nav",
    })

    # 规范必须持续登记的语义组件（评审后补登的核心项）。
    REQUIRED_REGISTERED = (
        "dot-ok", "dot-warn", "dot-idle",   # §2.5 行内状态点三态
        "th-ico",                            # §2.4 表头内联图标
        "mt-toolbar", "agent-toolbar", "market-toolbar", "insight-toolbar",  # §2.6
        "skill-card", "agent-card", "settings-card", "about-card", "adv-card",  # §2.3
        "modal-backdrop", "sheet-backdrop",  # §2.5b 遮罩真实类名
    )

    @staticmethod
    def _defined_classes() -> set[str]:
        return set(re.findall(r"\.([a-z][a-z0-9-]*)", _css()))

    @classmethod
    def _semantic(cls, classes) -> set[str]:
        return {
            c for c in classes
            if any(seg in cls.SEMANTIC_TOKENS for seg in c.split("-"))
        }

    @classmethod
    def _baseline(cls) -> set[str]:
        lines = cls.BASELINE.read_text(encoding="utf-8").splitlines()
        return {line.strip() for line in lines if line.strip() and not line.startswith("#")}

    # ── 判据 1：幽灵引用 ─────────────────────────────────────────────
    def test_spec_referenced_classes_exist_in_code(self):
        """规范里反引号写的类名必须真的存在（否则那节无法照做）。"""
        md = SPEC.read_text(encoding="utf-8")
        referenced = set(re.findall(r"`\.([a-z][a-z0-9-]*)`", md))
        # **否定式提及不算引用**：规范里常有「不存在统一的 `.toolbar`」「没有名为
        # `.backdrop` 的类」这类澄清句，它们的目的是告诉读者「别去找这个类」。
        # 若把它们当引用，门禁会逼着规范不要澄清自己的历史遗留名 —— 适得其反。
        for m in re.finditer(r"`\.([a-z][a-z0-9-]*)`", md):
            window = md[max(0, m.start() - 40): m.start()]
            if re.search(r"(没有|不存在|不是|非)\s*[^。；\n]{0,12}$", window):
                referenced.discard(m.group(1))
        # popover 有自己的页面源码，一并作为存在性来源。
        pop = (ROOT / "gui" / "popover.html").read_text(encoding="utf-8")
        existing = self._defined_classes() | set(
            re.findall(r"\.([a-z][a-z0-9-]*)", pop)
        ) | set(re.findall(r'class="([^"]*)"', pop + _src()))  # 也认内联类名
        flat = set()
        for item in existing:
            flat.update(item.split())
        ghosts = sorted(c for c in referenced if c not in self._defined_classes() and c not in flat)
        self.assertEqual(
            ghosts,
            [],
            "规范引用了代码里不存在的类（照规范写会找不到实现）：%r" % ghosts,
        )

    # ── 判据 2：新增语义类必须先登记 ─────────────────────────────────
    def test_new_semantic_classes_must_be_registered(self):
        """基线之外新增的语义类，必须先在规范里登记。"""
        new = self._semantic(self._defined_classes()) - self._baseline()
        # 已登记到规范的算通过
        md = SPEC.read_text(encoding="utf-8")
        registered = set(re.findall(r"\.([a-z][a-z0-9-]*)", md))
        offenders = sorted(new - registered)
        self.assertEqual(
            offenders,
            [],
            "新增了语义组件类但未回写规范（规范 §2.1 / §5 要求「新增组件或变体必须"
            "回写对应章节」）：%r\n"
            "  修法：① 在 docs/DESIGN.md 对应章节登记（含 §2.9 的硬数字）；"
            "② 重生成基线 tests/_component_baseline.txt。" % offenders,
        )

    # ── 判据 3：核心组件必须持续在册 ─────────────────────────────────
    def test_required_components_stay_registered(self):
        for cls in self.REQUIRED_REGISTERED:
            with self.subTest(component=cls):
                self.assertTrue(
                    (ROOT / "gui" / ("popover.html" if cls == "status-dot" else "dashboard.html"))
                    .read_text(encoding="utf-8").find("." + cls) >= 0,
                    f".{cls} 在代码里不存在 —— REQUIRED_REGISTERED 该更新",
                )
                self.assertIn(
                    "`." + cls + "`",
                    SPEC.read_text(encoding="utf-8"),
                    f".{cls} 已从规范里消失 —— 它是必须登记的语义组件",
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
        ("main", "padding", "var(--sp-9) var(--sp-9a) var(--sp-9f)"),
        (".card", "padding", "var(--sp-7)"),
        (".list-row", "padding", "var(--sp-4) var(--sp-6)"),
        (".pagination button", "padding", "var(--sp-1) var(--sp-3b)"),
        (".path-field-row button", "padding", "var(--sp-1) var(--sp-3)"),
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
