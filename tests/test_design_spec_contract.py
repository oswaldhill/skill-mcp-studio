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
        # §2.5 行内状态点：既有写法是 .dot.ok / .dot.warn / .dot.err / .dot.faint
        # （2026-10-11 曾误加一套 .dot-ok/-warn/-idle 弱化重复实现，已删除）。
        # 组合类无法用「单个类名」表达，故这三个在下面的专用断言里检查。

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

    # ── 判据 2b：HTML/JS 用到的类必须在 CSS 里有规则（幽灵类）────────────
    # 这是 2026-10-11 实测的缺口：我在 Hook 设置里连写了 `.table-wrap` 与 `.faint`
    # 两个**只在 HTML 用、CSS 里根本没有规则**的类 —— 页面不报错、门禁全绿，
    # 但布局实际是坏的（`.table-wrap` 没有 overflow 容器 → 表格宽到撑破卡片，
    # 用户截图反馈才发现）。此类「幽灵类」是最隐蔽的一类 UI 缺陷。
    #
    # 判据口径（避免误报）：
    #   - 只查**设置页等静态模板**常用的 `class="a b c"` 形式；JS 模板串里的动态类
    #     （含 ${}）跳过。
    #   - 允许一批**语义性豁免**：纯状态/工具类由别的选择器组合生效，或由外部
    #     样式（popover 内联）提供。
    GHOST_EXEMPT = frozenset({
        # 由 JS 动态添加/移除、或作为状态钩子使用（选择器里以 .a.b 组合出现）
        "hidden", "active", "open", "dark", "show", "loading", "ok", "err",
        "warn", "hot", "disabled", "selected", "nesting-open", "grow",
        # 外部页面（popover.html）自有样式
        "pressed",
    })

    # 存量幽灵类基线（2026-10-11 实测）。只许减少：清掉一个就从这里删一个。
    # 2026-10-14：`mcp-badge-legend` 已随 IDE/Agent 页图例撤销而不再使用，按规则收紧。
    GHOST_BASELINE = frozenset({
        "al-group-name", "btn-agent-detail", "btn-mt-settings", "ff-label",
        "input", "kv", "panel", "pf-add", "pf-rm", "ts-label",
    })

    def test_no_ghost_classes_used_in_markup(self):
        """markup 里 class="..." 写的类必须能在本页 CSS 找到规则。"""
        c = _css()
        defined = set(re.findall(r"\.([a-z][a-z0-9-]*)", c))
        src = _src()
        used = set()
        # 只接受**合法类名 token**（字母/数字/连字符，且不以数字开头）。
        # 为什么不能直接 split()：字符串拼接形态
        #   '<button class="pal-item\' + (idx === PALETTE.active ? " active" : "") + '"'
        # 会被 `class="([^"]*)"` 整段捕获，split 出来就是 `pal-item'`、`(idx`、
        # `===`、`?` 这类残片（实测产生 5 个假阳性）。
        TOKEN = re.compile(r"^[a-z][a-z0-9-]*$")
        for m in re.finditer(r'class="([^"]*)"', src):
            raw = m.group(1)
            if "${" in raw:          # JS 模板动态拼接，跳过
                continue
            used.update(t for t in raw.split() if TOKEN.match(t))
        # 注意：`data-class="attached"` 这类**属性值**不是 class。上面只匹配
        # `class="…"`（前有空格或引号边界），不会命中 data-class —— 但
        # `data-class="x"` 里的 `class="x"` **会**被子串命中，故再排一次：
        used -= set(re.findall(r'data-class="([a-z][a-z0-9-]*)"', src))
        ghosts = sorted(
            t for t in used
            if t not in defined and t not in self.GHOST_EXEMPT
        )
        # 棘轮：存量 11 个幽灵类冻结在 GHOST_BASELINE，**禁止新增**。
        #
        # 为什么不直接清零：这 11 个是既有债务（`kv`/`panel`/`pf-add`… 都是写了
        # class 却没写样式）。逐个补样式或删标记属于独立的清理工作，会与本次改动
        # 混在一起、难以评审；而**放着不管**会让后来者继续照抄这种写法。
        # 所以采用与「间距字面值」相同的处置：冻结基线 + 只许减少。
        # 合法性说明：它们大多只是无样式的语义标记（浏览器忽略未知 class，
        # 不报错），危害是「以为有样式」—— 本次 .table-wrap 就是这样把卡片撑破的。
        new_ghosts = [t for t in ghosts if t not in self.GHOST_BASELINE]
        self.assertEqual(
            new_ghosts,
            [],
            "markup 里新增了本页 CSS 未定义的类（幽灵类）—— 页面不报错但布局会坏"
            "（实测 .table-wrap 缺 overflow 容器把卡片撑破）：%r\n"
            "  修法：① 在 CSS 里补规则；② 或改用已有类。"
            "（存量 %d 个已冻结在 GHOST_BASELINE，只许减少）"
            % (new_ghosts, len(self.GHOST_BASELINE)),
        )
        # 伴随断言：存量必须真在减少的方向维护，不允许基线长期虚高
        stale = [t for t in self.GHOST_BASELINE if t not in used]
        self.assertEqual(
            stale,
            [],
            "GHOST_BASELINE 里有已不再使用的类，请收紧基线：%r" % stale,
        )

    # ── 判据 2c：行内状态点必须用既有的组合类（不得另造平行实现）──────
    def test_dot_states_use_existing_compound_classes(self):
        """`.dot` 的语义态必须用既有的 `.dot.ok/.warn/.err/.faint` 组合类。

        2026-10-11 实测：替换 emoji 时新增了一套 `.dot-ok/-warn/-idle`
        （样式更弱、无 box-shadow 环），与既有组合类并存成两套 —— 违反规范
        「先找现成组件，找不到再补」。此断言防止再次分叉。
        """
        c = _css()
        for state in ("ok", "warn", "err", "faint"):
            with self.subTest(state=state):
                self.assertIn(
                    f".dot.{state}",
                    c,
                    f"缺少既有状态点组合类 .dot.{state}",
                )
        md = SPEC.read_text(encoding="utf-8")
        for state in ("ok", "warn", "err", "faint"):
            with self.subTest(spec=state):
                self.assertIn(f".dot.{state}", md, f"规范未登记 .dot.{state}")
        # 平行实现不得回归
        for legacy in ("dot-ok", "dot-warn", "dot-idle"):
            with self.subTest(legacy=legacy):
                self.assertNotIn(
                    f".{legacy} {{",
                    c,
                    f"出现了平行实现 .{legacy} —— 应复用 .dot.{legacy.split('-')[1]}",
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
        (".ad-modal", "width", "min(880px, 94vw)"),
        (".agent-card .ac-path-row", "grid-template-columns", "58px minmax(0, 1fr)"),
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


class HookSettingsPlacementTest(unittest.TestCase):
    """Hook 设置的归属与能力域（2026-10-12，用户反馈后新增）。

    用户反馈两点：① Hook 事件太少；② 客户端设置要与 IDE/Agent 一致（含分层作用域），
    或干脆并进 IDE/Agent。落地后由本类守住，防止回退：

    - 「客户端事件命名规范」表**必须只在** IDE/Agent 详情，不得再加回 Hook tab
      （两处维护必然漂移：Hook tab 只有单条 config_path，而 IDE/Agent 已有多档作用域）；
    - 详情必须真的**消费**能力域字段（scopes / supported / event_format），
      否则「合并过去」只是把表删了、信息反而丢了。
    """

    def test_hook_tab_has_no_client_naming_table(self):
        src = _src()
        # 判据取「渲染出的标题 + 该表的行构造变量」，不取任意字符串 ——
        # 代码注释里说明「该表已移入详情」也会命中纯字符串断言（实测被自己绊倒）。
        self.assertNotIn("<h4>客户端事件命名规范</h4>", src,
                         "该表应只在 IDE/Agent 详情；不要加回 Hook 设置 tab")
        self.assertNotIn("hookClientRows", src, "该表的行构造器应已删除，不得残留")
        # Hook tab 仍必须保留事件勾选入口（不能连职责一起删掉）
        self.assertIn('data-action="save-hook-events"', src)
        self.assertIn("data-hook-event=", src)

    def test_hook_tab_groups_catalog_rows(self):
        """47 项词表要分组渲染（分组表头 .hook-group-row 已登记在规范 §2.10）。"""
        src = _src()
        self.assertIn("hook-group-row", src)
        self.assertIn("catalogGroups", src)

    def test_agent_detail_consumes_hook_capability_fields(self):
        src = _src()
        self.assertIn("Hook 配置", src, "IDE/Agent 详情缺少「Hook 配置」区块")
        for field in ("hooks_scopes", "hooks_supported_events", "hooks_event_format"):
            self.assertIn(field, src, f"详情未消费 {field}（合并后信息反而丢了）")

    def test_configured_events_marked_without_relying_on_color(self):
        """已**配置**的事件用 .tag.ok 标注；颜色只是辅助，事件名必须可读（§3b）。

        口径已于 2026-10-13 改为「只看有没有配置，不看配置内容」，故标签文案同步。
        """
        src = _src()
        self.assertIn('class="tag ok" title="该事件已配置 hook"', src)

    def test_canonical_to_client_matches_python_rule(self):
        """GUI 的规范名→客户端名规则必须与 Python 侧同源（camel 只改首字母）。"""
        src = _src()
        self.assertIn("const canonicalToClient", src)
        self.assertIn('eventFormat === "camel_case"', src)


class HookSelectAllTest(unittest.TestCase):
    """Hook 事件「默认全选 + 全选/清空」（2026-10-12 用户要求）。

    用户要求两点：① 默认应当全选；② 要有全选的能力（按钮）。
    此前 `settings.hook_events: []` 意味着**默认一个都不勾**，且 `--fix-hooks`
    直接判「已选择不写入任何 hook 事件」—— 开箱即停用，与预期相反。
    """

    def test_config_defaults_to_all_events_selected(self):
        """出厂即全选：settings.hook_events 必须列出词表里的每一个规范事件。"""
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        catalog = [e["name"] for e in cfg["hooks"]["events"]]
        selected = list(cfg["settings"]["hook_events"])
        self.assertEqual(len(catalog), len(selected),
                         "settings.hook_events 应与词表等长（默认全选）")
        self.assertEqual(selected, catalog, "默认勾选顺序应与词表一致")

    def test_hook_card_has_select_all_and_none(self):
        src = _src()
        self.assertIn('data-action="hook-select-all"', src)
        self.assertIn('data-action="hook-select-none"', src)
        # 计数要能就地更新（不整页重渲染）
        self.assertIn('id="hook-selected-count"', src)

    def test_select_all_only_changes_local_state(self):
        """全选/清空不得直接写盘：仍须走「保存」→ --set-setting。"""
        src = _src()
        m = re.search(r'\[\["hook-select-all".*?\}\);', src, re.S)
        self.assertIsNotNone(m, "未找到全选/清空 处理器")
        self.assertNotIn("--set-setting", m.group(0), "全选不应直接落盘")

    def test_scope_paths_display_in_full(self):
        """详情里的分层作用域路径必须完整显示（不省略号截断）。"""
        src = _src()
        self.assertIn("ad-e-loc-full", src)
        self.assertIn(".ad-entry .ad-e-loc-full", _css())


class HookSaveSemanticsAndCardSummaryTest(unittest.TestCase):
    """保存语义 + 错误展示 + 卡片能力摘要（2026-10-12 用户三项反馈）。

    用户反馈：
    ① 错误不该在页面上直接铺一大段（应是弹框）；
    ② 设置页的「保存」只保存**选择**，写 IDE 是 Hook 业务页的事；
    ③ 详情里的内容要在**卡片/列表**上直接可见，不必点进去。
    """

    def test_save_uses_task_modal_not_page_banner(self):
        """保存 Hook 选择的结果必须走弹框（runTaskModal），不得用页面级 banner。

        反例（实测用户截图）：失败时 `showBanner("err", … + cliErrDetail(res))`
        把 CLI 整段 stdout（技能扫描报告，1600 字符）铺在页面顶部。
        判据取**精确锚点**而不是切片：切片范围会被后续相邻代码带偏（实测踩过）。
        """
        src = _src()
        self.assertIn('runTaskModal("保存 Hook 事件选择"', src,
                      "保存结果应走 runTaskModal 弹框")
        self.assertNotIn('showBanner("err", "保存 Hook 事件失败', src,
                         "保存失败不得再用页面级 banner 展示 CLI 输出")
        self.assertNotIn('showBanner("ok", `已保存 ${picked.length} 个事件', src,
                         "保存成功也应走弹框，而不是页面横幅")
        # 错误详情要收敛（挑失败行/去 ANSI 截断），不抛原始 stdout
        self.assertIn("cliFailLines(res) || cliErrDetail(res)", src,
                      "失败详情应先过 cliFailLines / cliErrDetail")

    def test_save_copy_states_selection_only(self):
        """文案必须说清「只保存选择」，写入客户端在 Hook 页 —— 不能说成保存即写入。"""
        src = _src()
        self.assertIn("这里只保存", src, "缺少「只保存选择」的说明")
        self.assertIn("「写入 Hook」", src, "应指向 Hook 页的写入动作")

    def test_cards_and_list_show_capability_summary(self):
        """设置页卡片与列表都要有 Skills / MCP / Hook 能力摘要。"""
        src = _src()
        for fn in ("_agentSkillsSummary", "_agentMcpSummary", "_agentHookSummary"):
            self.assertIn(f"function {fn}(", src, f"缺少摘要构造器 {fn}")
        # 卡片视图：三条 ac-meta-row 必须出现（设置页卡片，非主页 home-card）
        # 注意：设置页卡片视图在 renderAgentsTable 内（主页另有一套 cardFor/home-card，
        # 早就有 ac-meta-row）。必须把范围限定在 renderAgentsTable 里，否则断言会
        # 被主页那套“碰巧满足”（实测踩过：index 取到了主页的 sections）。
        i = src.index("function renderAgentsTable(")
        j = src.index("// ---------------- Agent 设置子页面", i)
        view = src[i:j]
        for k in ("Skills", "MCP", "Hook"):
            self.assertIn(f'<span class="k">{k}</span>', view,
                          f"设置页卡片缺少 {k} 摘要行")
        for fn in ("_agentSkillsSummary(t)", "_agentMcpSummary(t)", "_agentHookSummary(t)"):
            self.assertIn(fn, view, f"设置页卡片未调用 {fn}")
        for k in ("Skills", "MCP", "Hook"):
            self.assertIn(f'<span class="k">{k}</span>', view,
                          f"设置页卡片缺少 {k} 摘要行")
        # 列表视图：表头要有能力摘要列
        self.assertIn("能力摘要（Skills / MCP / Hook）", src)


class CardLabelColumnAlignmentTest(unittest.TestCase):
    """卡片里「路径区」与「能力摘要区」的标签列必须逐项同构（2026-10-12 用户反馈）。

    用户截图指出设置页卡片「最好保持对齐」。实测错位来自两套几何：
    `.ac-path-row` 是 `grid` + 58px 标签列 + 无竖线，而 `.ac-meta-row` 是
    `flex` + `.k` 宽 74px + `border-right` 竖线 —— 标签列宽、字体、分隔线全不一致，
    于是 APP/CLI/CONFIG 与 Skills/MCP/Hook 两组的值区起点差 16px，一眼能看出错位。

    本类把「同构」变成机检不变量：两组的列宽/gap/对齐、以及标签的字体族/字号/字重/
    大小写/颜色都必须逐项相等。任何一侧被单独改动都会立刻失败。
    """

    PATH_ROW = ".agent-card .ac-path-row"
    META_ROW = ".agent-card .ac-meta-row"
    PATH_LABEL = ".agent-card .ac-path-label"
    META_LABEL = ".agent-card .ac-meta-row .k"

    def test_row_geometry_identical(self):
        for prop in ("grid-template-columns", "gap", "align-items"):
            with self.subTest(prop=prop):
                a, b = _decl(self.PATH_ROW, prop), _decl(self.META_ROW, prop)
                self.assertTrue(a, f"{self.PATH_ROW} 未声明 {prop}")
                self.assertEqual(a, b, f"两组行几何不一致：{prop} 路径区={a!r} 摘要区={b!r}")

    def test_label_typography_identical(self):
        for prop in ("font-family", "font-size", "font-weight",
                     "text-transform", "color", "line-height"):
            with self.subTest(prop=prop):
                a, b = _decl(self.PATH_LABEL, prop), _decl(self.META_LABEL, prop)
                self.assertTrue(a, f"{self.PATH_LABEL} 未声明 {prop}")
                self.assertEqual(a, b, f"两组标签样式不一致：{prop} 路径区={a!r} 摘要区={b!r}")

    def test_meta_label_has_no_divider(self):
        """摘要区标签不得再单独加竖线（路径区没有；单边竖线是错位感来源之一）。"""
        self.assertNotIn("border-right", _rule_body(self.META_LABEL),
                         "摘要区标签不应有 border-right（与路径区不一致）")

    def test_uninstalled_client_dims_skills_dir(self):
        """未安装客户端的 skills 目录必须用淡化变体 `.is-dim`（方案 A）。

        为什么：未安装时该路径只是内置注册表的「默认位置」，不代表本机状态；
        与同行右侧的「不适用」标签并列却不加区分，读起来自相矛盾（Cursor 卡片实测）。
        已安装时**不得**淡化（那是本机真实目录）。
        """
        src = _src()
        i = src.index("function _agentSkillsSummary(")
        j = src.index("function _agentMcpSummary(", i)
        body = src[i:j]
        # 判据必须绑到**那一行赋值**上：只查 "is-dim"/"t.installed" 会被注释与
        # 下一行的 `if (!t.installed)` 同时满足，反向验证照样通过（实测踩过）。
        m = re.search(r'const\s+dimCls\s*=\s*([^;]+);', body)
        self.assertIsNotNone(m, "未找到目录淡化条件（dimCls 赋值）")
        expr = m.group(1)
        self.assertIn("t.installed", expr, "淡化条件必须依据「是否安装」")
        self.assertIn("is-dim", expr, "未安装时应给出淡化变体 is-dim")
        self.assertRegex(expr, r'\?\s*""\s*:\s*"\s*is-dim"',
                         "淡化必须写成「已安装→无类；未安装→is-dim」")
        self.assertIn("${dimCls}", body, "胶囊 class 必须真的拼上 dimCls")
        # 淡化变体必须真有**声明**（否则是幽灵类：页面不报错但样式不生效）。
        # 判据取「声明」而不是「选择器子串」—— 后者会被 `:hover` 那条规则满足，
        # 删掉基础规则也照样通过；且 _decl 取不到时会返回空串，一并被这条挡住。
        self.assertEqual(
            _norm_ws(_decl(".agent-card .ac-path-val.is-dim", "color")),
            "var(--faint)",
            "缺少/改坏了淡化变体的 color 声明（应为 --faint；基础规则被删也在此暴露）",
        )
        self.assertEqual(
            _norm_ws(_decl(".agent-card .ac-path-val.is-dim", "background")),
            "transparent",
            "淡化变体背景应为 transparent（与实心胶囊区分）",
        )

    def test_value_column_never_wraps(self):
        """值区必须 nowrap + 首元素自适应：否则长路径会把状态标签挤到第二行。

        实测场景（TRAE 卡片）：路径长到换行后，状态标签从值区起点缩进，看起来像
        「标签列被撑开」。判据取容器声明，而不是「有没有 flex」这种空壳。
        """
        sel = ".agent-card:not(.home-card) .ac-meta-row .v"
        self.assertEqual(_norm_ws(_decl(sel, "flex-wrap")), "nowrap",
                         "值区必须 nowrap（否则长值把标签挤到第二行）")
        self.assertIn(":not(.home-card)", sel + _css() and sel,
                      "值区规则应限定作用域，避免影响主页卡片")
        self.assertEqual(_norm_ws(_decl(".agent-card:not(.home-card) .ac-meta-row .v > :first-child",
                                       "flex")), "1 1 auto",
                         "首个值需自适应")

    def test_no_decorative_dots_on_card_labels(self):
        """卡片标签不得再有装饰性圆点（taste：装饰状态点默认零）。

        反向验证要点：删掉 ::before 只是「少了个装饰」，但如果规范仍写着有圆点，
        就会code/规范漂移 —— 这里同时守住代码侧不存在该伪元素。
        """
        c = _css()
        self.assertNotIn(".agent-card .ac-path-label::before", c,
                         "路径标签不应有装饰性 ::before 圆点")
        self.assertNotIn(".agent-card .ac-meta-row .k::before", c,
                         "能力区标签不应有装饰性 ::before 圆点")
        # 但 is-empty 状态必须仍有**有意义**的表现（否则是死类）
        self.assertIn(".agent-card .ac-path-row.is-empty .ac-path-label", c,
                      "is-empty 应有实际样式，不能成为死类")

    def test_path_pills_have_no_persistent_fill(self):
        """设置页路径默认无底色（消除满屏灰块的表单感），悬停才浮出。"""
        self.assertEqual(
            _norm_ws(_decl(".agent-card:not(.home-card) .ac-path-val", "background")),
            "transparent",
            "设置页路径默认应为透明底",
        )

    def test_partial_write_is_not_green(self):
        """`已写入 N/M` 仅当 N>=M 才用 ok 色；部分写入不得报绿。"""
        src = _src()
        i = src.index("function _agentHookSummary(")
        j = src.index("function renderAgentsTable(", i)
        body = src[i:j]
        self.assertIn("allWritten", body, "缺少「是否全部写入」的判定")
        self.assertIn('tag${allWritten ? " ok" : ""}', body,
                      "部分写入必须落到中性标签（而非硬编码 ok）")

    def test_dividers_align_across_cards(self):
        """两条分隔线都必须跨卡片对齐（用户三次反馈后定案）。

        对齐机制：**锚定底部**。`.ac-meta` 用 `margin-top: auto` 把自己与底栏一起推到
        卡片底部，于是它的上沿 = 卡片底 − (meta 高 + foot 高)。两段高度都恒定
        （3 行 nowrap + 固定内边），故所有卡片的这条线 y 相同；底栏上沿同理。

        为什么不用「路径区 flex:1 吸收差异」：那会在内容超出时收缩路径区，把末行裁进线里
        （实测可见），且线上沿依旧随条数漂移。为什么 foot 不能也吃 auto 外边距：
        空白会被两处瓜分，meta 上沿就跟着漂。

        实测（headless 渲染 + 逐行像素扫描）：3 条与 4 条路径的两张卡片，
        两条分隔线 y 完全相同 [205, 314]。
        """
        self.assertIn("border-top", _rule_body(".agent-card .ac-meta"),
                      "能力区必须有整宽分隔线（用户明确「分隔线很重要」）")
        self.assertEqual(_norm_ws(_decl(".agent-card:not(.home-card) .ac-meta", "margin-top")),
                         "auto", "meta 必须 margin-top:auto，分隔线位置才锚定卡片底部")
        self.assertEqual(_norm_ws(_decl(".agent-card:not(.home-card) .ac-foot", "margin-top")),
                         "0", "foot 不得吃 auto 外边距，否则空白被瓜分、分隔线漂移")
        self.assertEqual(_norm_ws(_decl(".agent-cards", "align-items")), "stretch",
                         "同组卡片必须等高")
        self.assertEqual(_norm_ws(_decl(".agent-card:not(.home-card) .ac-paths", "flex")),
                         "0 0 auto", "路径区不得伸缩：拉伸会裁切末行")
        self.assertEqual(_norm_ws(_decl(".agent-card:not(.home-card) .ac-foot", "flex")),
                         "0 0 auto", "底栏不得伸缩")

    def test_dim_variant_does_not_change_shape(self):
        """淡化变体**只改颜色不改形状**（用户问「Skill 与 MCP/Hook 样式为何不同」）。

        根因：`.is-dim` 曾设 `border-color: var(--line)`，而默认胶囊是透明无边框，
        于是同一张卡片里 Skills 显示成方框、MCP/Hook 是纯文本。现改为 transparent，
        并让三行（Skills / MCP / Hook）在未安装时统一淡化。
        """
        self.assertEqual(_norm_ws(_decl(".agent-card .ac-path-val.is-dim", "border-color")),
                         "transparent", "淡化变体不得引入可见边框（须与默认胶囊同形）")
        self.assertEqual(_norm_ws(_decl(".agent-card .ac-path-val.is-dim", "background")),
                         "transparent", "淡化变体背景应透明")
        src = _src()
        for fn in ("_agentSkillsSummary", "_agentMcpSummary", "_agentHookSummary"):
            i = src.index(f"function {fn}(")
            j = src.find("\nfunction ", i + 10)
            body = src[i:j if j > 0 else i + 900]
            self.assertIn('const dimCls = t.installed ? "" : " is-dim";', body,
                          f"{fn} 未按安装状态使用淡化变体（三行应一致）")


    def test_value_and_empty_have_identical_metrics(self):
        """值胶囊与「未收录」空态必须**度量完全一致**，否则 meta 带高度会随内容变化。

        这是 2026-10-12 实测抓到的真实缺陷：`.ac-path-none` 比 `.ac-path-val` 少 3px
        （字号少 1px + 缺那条 `border: 1px solid transparent`），于是"HOOK 未收录"的卡片
        meta 带矮 3px，而 meta 带用了 `margin-top:auto` 锚定底部 ⇒ **分隔线整体上移 3px**，
        跨卡片错位。用户三次反馈"没对齐"，肉眼几乎看不出是 3px。

        实测（真实数据 2~6 条路径、8 张卡片）：修好后 meta 高度恒为 109、两条分隔线 Δ=0。

        判据：两者在**决定行高的每一个属性**上都必须相等（字号 / 行高 / 内边 / 边框 / 字体族）。
        """
        val = ".agent-card .ac-path-val"
        non = ".agent-card .ac-path-none"
        # 注意：两处都用 `border: 1px solid transparent` 简写，故比较 `border` 简写值；
        # 拆成 border-width/style 是取不到的（实测报空串）。
        for prop in ("font-size", "line-height", "padding", "border", "font-family"):
            with self.subTest(prop=prop):
                a, b = _decl(val, prop), _decl(non, prop)
                self.assertTrue(a, f"{val} 未声明 {prop}")
                self.assertEqual(a, b, f"空态与值胶囊度量不一致：{prop} {a!r} vs {b!r}")
        # 边框必须存在（透明也行）：它是 hover 不抖动的手段，也是行高的一部分
        self.assertIn("border", _rule_body(non),
                      "空态必须有与值胶囊相同的 border（透明边框也参与行高）")

    def test_agent_list_has_hook_column_with_legend(self):
        """IDE/Agent 列表视图必须有 Hook 列，且与 MCP 同待遇（列 + 图例 + 四态）。

        用户要求：「在 IDE 的 tab 中增加 hook 的配置和 scale（分层作用域），和 MCP 一样」。
        """
        src = _src()
        # 锚点用 `<th>名称</th>` 起头的那一行：列头文本后面可能跟说明气泡的问号图标，
        # 所以不能用「技能目录</th>」这类"文本紧邻闭合标签"的写法（已因加图标而失效）。
        head = [line for line in src.split("\n") if "<th>名称</th>" in line and ">Hook" in line]
        self.assertTrue(head, "未找到列表视图表头")
        h = head[0]
        self.assertIn(">MCP<span", h)
        self.assertIn(">Hook<span", h, "表头缺少 Hook 列")
        self.assertLess(h.index(">MCP<span"), h.index(">Hook<span"),
                        "Hook 列应排在 MCP 之后（与用户截图列序一致）")
        # 图例已按用户要求撤销（2026-10-14，两整行图例太占空间），
        # 状态色/图标的含义改由**列头说明气泡**承载。
        # 注意用 `data-help` 而不是原生 `title`：实测本应用（Tauri/macOS WKWebView）里
        # 原生 title 气泡不弹出（用户反馈「提示没有显示出来」），故改为自绘浮层。
        self.assertRegex(h, r'<th data-help="[^"]*N / M[^"]*">MCP<span',
                         "MCP 列头应带 data-help 说明（图例撤销后含义的承载处）")
        self.assertRegex(h, r'<th data-help="[^"]*N / M[^"]*">Hook<span',
                         "Hook 列头应带 data-help 说明（含 N/M 含义与「N 档」）")
        self.assertIn("function showThTip", src, "说明气泡需有自绘实现（不依赖原生 title）")
        self.assertNotIn(' title="N / M', src, "不得再依赖原生 title 承载说明")
        self.assertNotIn("mcp-badge-legend", src, "IDE/Agent 页图例已撤销，不应再出现")
        # 空行 colspan 必须与列数一致（10 列）
        self.assertIn('colspan="10"', src, "空行 colspan 应与 10 列一致")

    def test_hook_column_distinguishes_unregistered_from_unsupported(self):
        """Hook 列：未登记配置路径显示「—」，**不得**显示「不支持」。

        为什么（真实数据驱动）：22 个已安装客户端里只有 6 个登记了 `hooks.clients`。
        写成「不支持」等于断言"该客户端没有 Hook 能力"，属过度断言；Hook 业务页
        `_hooksEntries` 只列"有 hooks_config_path"的客户端，是同一口径。
        """
        src = _src()
        i = src.index("const hookSupported =")
        body = src[i:i + 1800]
        self.assertIn("尚未收录该客户端的 Hook 配置路径", body,
                      "未登记情形应给出「未收录」措辞")
        self.assertNotIn("不支持 Hook", body,
                         "未登记不得写成「不支持 Hook」（过度断言）")
        # 未登记态不得用 em-dash 占位（本项目禁 em-dash；「未收录」比破折号表意明确）
        self.assertNotIn(">—</span>", body, "未登记态不得用 em-dash 占位")
        # 分层作用域徽标必须在 Hook 单元格内
        self.assertIn("al-scope", body, "Hook 单元格应含分层作用域徽标")
        self.assertIn("hooks_scopes", body, "作用域档数取自 hooks_scopes")

    def test_partial_hook_config_is_not_green(self):
        """Hook 列：部分**配置**用中性标签，只有全部配置才 ok（与卡片口径一致）。

        口径已于 2026-10-13 改为「只看有没有配置」，变量名同步为 hookConfigured。
        """
        src = _src()
        i = src.index("const hookSupported =")
        body = src[i:i + 1800]
        self.assertIn("hookConfigured >= hookSupported", body,
                      "缺少「是否全部配置」的判定")
        # 判据只看有无配置，不得再依赖 is_ai_memory 之类的内容判定
        self.assertNotIn("is_ai_memory", body)

    def test_label_column_is_58px(self):
        """标签列宽是不可协商的对齐基准；改它必须同时改规范 §2.9。"""
        self.assertEqual(_norm_ws(_decl(self.PATH_ROW, "grid-template-columns")),
                         "58px minmax(0, 1fr)")


if __name__ == "__main__":
    unittest.main()


class TrunkSourceGuardTest(unittest.TestCase):
    """主干源码不得出现已剥离工具的命令字符串 / 字段（v0.29.0 剥离后的反向守护）。

    将 §6b 的强 grep 从人工验证升级为 CI 门禁：一旦主干源码回退引入 ai-memory
    命令字符串或 is_ai_memory 字段，本断言立即红灯。
    """

    def test_no_ai_memory_in_trunk_sources(self):
        """主干源码不得出现 ai-memory 命令字符串（v0.29.0 剥离后）。"""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        trunk = (root / "core" / "hooks_fixer.py").read_text(encoding="utf-8")
        self.assertNotIn("ai-memory hook", trunk, "hooks_fixer 不得含 ai-memory 命令")
        self.assertNotIn("is_ai_memory", trunk, "hooks_fixer 不得含 is_ai_memory 字段")


class HookTemplateLayoutGuardTest(unittest.TestCase):
    """§2.10「写入命令模板」卡片的 v0.29.1 布局修复不变量（双轨测试轨）。

    v0.29.1 修了卡片控件 inline ``width:100%`` 把同行兄弟节点裁掉的缺陷
    （HANDOFF §7f；规范 §2.10「组件约束」）。``.row .v`` 必须 8 项属性齐全、
    控件必须 flex 填充——任一缺失会让「应用预设」按钮 / 「（全局兜底…）」提示 /
    旧命令「旧」标回到「有元素、无像素、点不到」。本断言把该修复钉为可失败门禁，
    避免后续改动无声回退缺陷。
    """

    # `#hook-tmpl-body .row .v` 的 8 项属性（dashboard.html:1271）。改代码必须
    # 同步改规范 §2.10 的字面规则（二者由本表交叉锁定）。
    _V8 = [
        "display: flex", "align-items: center", "gap: var(--gap-2)",
        "flex: 1 1 auto", "min-width: 0", "flex-wrap: wrap",
        "overflow: visible", "white-space: normal",
    ]

    def test_row_v_has_all_eight_flex_props(self):
        """``#hook-tmpl-body .row .v`` 必须含 v0.29.1 修复的全部 8 项属性。"""
        body = _norm_ws(_rule_body("#hook-tmpl-body .row .v"))
        missing = [p for p in self._V8 if p not in body]
        self.assertEqual(
            missing, [],
            "#hook-tmpl-body .row .v 缺这些属性（v0.29.1 修复回退，兄弟节点会被 "
            "overflow:hidden 裁掉）：%r" % missing,
        )

    def test_control_uses_flex_fill_not_width_100pct(self):
        """控件（input）用 ``flex:1 1 auto`` 填充，不再回归 inline ``width:100%``（缺陷根因）。"""
        css = _norm_ws(_css())
        self.assertIn(
            "#hook-tmpl-body .row .v > input { flex: 1 1 auto; }", css,
            "hook-tmpl 控件未声明 flex:1 1 auto（v0.29.1 修复回退，控件会撑满 .v "
            "并把同行兄弟节点裁掉）",
        )


class LegendPlacementAndAlignmentTest(unittest.TestCase):
    """图例：统一放在内容最下方 + 标签列定宽对齐（2026-10-13 用户要求）。

    用户反馈三点：① 图例里「部分已配置」那条色点没有颜色；② 两条图例的条目对不齐；
    ③ 建议所有页面的图例都放到最下方。①② 的根因是同一个 ——那条色点漏了语义 class，
    宽度为 0 既让它没颜色、又把它后面的条目整体左移。
    """

    def test_every_legend_has_a_colored_swatch(self):
        """每条 legend-swatch 都必须带语义 class —— 否则没有背景色（不可见）。

        这是本次 ① 的根因：`<span class="legend-swatch"></span>` 命中基类拿到 9px 宽，
        但没有任何 background 规则，于是渲染成一个"看不见的占位"。
        """
        src = _src()
        bare = re.findall(r'<span class="legend-swatch"\s*></span>', src)
        self.assertEqual(bare, [], f"有 {len(bare)} 条色点缺语义 class（会没有颜色）")
        # 基类必须仍是尺寸来源，各变体只负责颜色
        self.assertEqual(_norm_ws(_decl(".skill-legend .legend-swatch", "width")), "9px")
        self.assertEqual(_norm_ws(_decl(".skill-legend .legend-swatch", "height")), "9px")
        for variant in ("ok", "warn", "err", "na", "neutral"):
            with self.subTest(variant=variant):
                self.assertTrue(_decl(f".skill-legend .legend-swatch.{variant}", "background"),
                                f".legend-swatch.{variant} 缺 background（该状态无颜色）")

    def test_legend_label_column_is_fixed_width(self):
        """标签列必须定宽，否则多条图例的第一个色点会错开（实测差 2px）。"""
        self.assertIn("min-width", _rule_body(".skill-legend .legend-label"),
                      "标签列未定宽：MCP / Hook 名字长短不一会让色点列错位")

    def test_legends_come_before_their_content(self):
        """图例必须排在它所说明的内容**之前**（2026-10-14 用户定案：放上面好看）。

        走过一次弯路：曾按要求把 5 处图例全移到最下方，用户看到实际效果后判定
        「还是放在上面好看」，于是回退。本断言把当前选择钉住，避免又被改回去。

        例外：**IDE/Agent 页的两条图例已整块撤销**（用户同日要求："全部有图例的话
        就太多太长了"），含义改由列头 title 承载 —— 故不再参与本断言。
        """
        src = _src()
        pairs = [
            ("Skills 页", 'id="skills-list"', 'id="skill-legend"'),
            ("MCP 页", "'<div class=\"table-scroll\"><table class=\"mcp-table\">", "el.innerHTML = legend"),
        ]
        for name, content, legend in pairs:
            with self.subTest(page=name):
                ci, li = src.find(content), src.find(legend)
                self.assertNotEqual(ci, -1, f"{name}：未找到内容锚点")
                self.assertNotEqual(li, -1, f"{name}：未找到图例锚点")
                self.assertLess(li, ci, f"{name}：图例应排在内容之前")


class RowStatusCellUniformityTest(unittest.TestCase):
    """`.agent-list-table` 行内状态列必须形态统一，且**不使用纯着色文字**。

    演进（三轮，均为用户反馈驱动）：
      ① 原先 安装/技能目录 用 `.ok-true/.ok-false/.ok-na`（纯着色文字，只设 color），
         同行 MCP/Hook 却是 `.tag` 胶囊 → 混形态。
      ② 先统一成 `.tag` 胶囊 → 用户仍嫌「胶囊里的文字显得也比较突兀」：这两列在多数行
         取值相同（"已安装"、"链接统一目录"），同一串中文逐行重复又长又抢眼。
      ③ 最终定为**图标徽标 `.al-ico`**（与 APP/CLI/CONFIG 的数字徽标同尺寸同族），
         语义由 title + .sr-only 承载。

    本类守住最终形态：两列必须用 `.al-ico`，且不得回退到纯着色文字或长文字胶囊。
    """

    # 行内状态列可能出现的纯着色文字类
    PLAIN = ("ok-true", "ok-false", "ok-na")

    def _row_renderer_body(self) -> str:
        """取出主列表行的渲染函数体（renderHomeListView）。"""
        src = _src()
        i = src.index("function renderHomeListView(")
        j = src.index("\nfunction ", i + 10)
        return src[i:j]

    def test_status_and_skills_cells_are_icons(self):
        """安装 / 技能目录 两列必须用 `.al-ico` 图标徽标。"""
        body = self._row_renderer_body()
        for cls in self.PLAIN:
            with self.subTest(cls=cls):
                self.assertNotIn(
                    f'class="{cls}"', body,
                    f"行内状态列不得用 .{cls}（纯着色文字）",
                )
        # 两列的核心实现必须存在（注意：skillsIco 是用 let 与其它两个变量一起声明的，
        # 所以只断言标识符被使用，不绑定声明关键字）
        self.assertIn("statusIco", body, "安装列应构造图标（statusIco）")
        self.assertIn("skillsIco", body, "技能目录列应构造图标（skillsIco）")
        self.assertRegex(body, r'class="al-ico \$\{statusCls\}"', "安装列应用 .al-ico 徽标")
        self.assertRegex(body, r'class="al-ico \$\{skillsCls\}"', "技能目录列应用 .al-ico 徽标")
        # 无障碍：图标必须带 title，并配 sr-only 文本（不以图形单独传达信息）
        self.assertIn('class="sr-only"', body, "图标徽标必须配 .sr-only 文本")
        # 图标取自 ICONS，不得用符号字符充当图标
        for name in ("ICONS.check", "ICONS.warn", "ICONS.cross", "ICONS.link",
                     "ICONS.folder", "ICONS.minus"):
            with self.subTest(icon=name):
                self.assertIn(name, body, f"缺少 {name}")

    def test_mcp_and_hook_na_cells_are_tags(self):
        """MCP / Hook 列里原先的纯文字「不支持 / 0 / 未收录 / 仅审计」用中性 .tag 胶囊。"""
        body = self._row_renderer_body()
        for label in ("不支持", "未收录", "仅审计"):
            with self.subTest(label=label):
                self.assertRegex(body, rf'class="tag"[^>]*>{label}<',
                                 f"「{label}」应为中性 .tag 胶囊")

    def test_tooltip_legend_renders_icons(self):
        """列头气泡的图例行必须渲染图标/色点，不得用文字描述形状。

        用户要求（2026-10-14）：「弹出的内容中，最好有图标作为图例」——
        文字"绿点 已安装"要读者在脑中翻译成视觉，直接渲染那枚徽标才能与列内一一对应。
        """
        src = _src()
        # 1) data-help 用图例行标记格式：#图标名.颜色类:标签;...
        self.assertEqual(src.count('data-help="#'), 2,
                         "安装/技能目录的 data-help 应为纯图例行（# 开头）")
        self.assertIn("|#.ok:", src, "MCP/Hook 的 data-help 应含色点图例行")
        # 2) showThTip 有图例行的渲染逻辑
        i = src.index("function showThTip(")
        j = src.index("\n}\n", i) + 3
        fn = src[i:j]
        self.assertIn('line.startsWith("#")', fn, "showThTip 应识别 # 图例行")
        for marker in ("tt-legend", "tt-item", "tt-dot", "ICONS[icon]"):
            with self.subTest(marker=marker):
                self.assertIn(marker, fn, f"showThTip 缺少 {marker} 渲染逻辑")
        # 3) CSS 有 tt-dot 的颜色变体（与 legend-swatch 同色系，缺一个就有一种状态无色）
        for variant in ("ok", "warn", "err", "na", "neutral"):
            with self.subTest(variant=variant):
                self.assertTrue(_decl(f".th-tip .tt-dot.{variant}", "background"),
                                f".tt-dot.{variant} 缺 background")

    def test_status_columns_are_centered(self):
        """状态列（安装/技能目录/MCP/Hook）的 th 与 td 必须居中。

        用户反馈（2026-10-14）：「安装 技能目录等内容，没有和上面的标题栏居中对齐」。
        这四列的单元格是单枚徽标/短标签，左对齐时贴着单元格左缘，与更宽的列头
        （文字+问号图标）轴线不一致；居中后实测偏差 0.0px。
        """
        css = _css()
        for col in (3, 7, 8, 9):
            with self.subTest(col=col):
                self.assertIn(f".agent-list-table th:nth-child({col})", css,
                              f"第 {col} 列 th 未纳入居中规则")
                self.assertIn(f".agent-list-table td:nth-child({col})", css,
                              f"第 {col} 列 td 未纳入居中规则")
        m = re.search(r"\.agent-list-table th:nth-child\(3\)[^{]*\{([^}]*)\}", css, re.S)
        self.assertIsNotNone(m, "未找到居中规则体")
        self.assertIn("text-align: center", m.group(1), "居中规则应声明 text-align: center")


class ColumnWidthGovernanceTest(unittest.TestCase):
    """`.agent-list-table` 必须用 `table-layout: fixed` + 紧列定宽，防止图标列被撑宽。

    量化诊断（2026-10-14）：默认 auto 布局下，只装一枚 20px 徽标的列被分到 89-125px，
    1440px 窗口下整表约 65% 是横向空白。改为 fixed 布局 + 8 个紧列定宽后，
    三个窗口宽度（1018/1440/1680px）均验证零溢出、零横向滚动。
    不变量：table-layout: fixed 存在，且 8 个紧列各有 px 宽度声明。
    """

    def test_table_layout_is_fixed(self):
        css = _css()
        m = re.search(r"\.agent-list-table\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "未找到 .agent-list-table 规则")
        self.assertIn("table-layout: fixed", m.group(1),
                      ".agent-list-table 必须声明 table-layout: fixed，否则紧列会被 auto 布局撑宽")

    def test_tight_columns_have_px_width(self):
        """8 个紧列（安装/APP/CLI/CONFIG/技能目录/MCP/Hook/操作）必须有 px 定宽。"""
        css = _css()
        # 列号 → 期望最小宽度（内容并集 + 20px 内边，向上取 4 的倍数）
        expected = {3: 56, 4: 48, 5: 48, 6: 70, 7: 82, 8: 78, 9: 104, 10: 124}
        for col, min_w in expected.items():
            with self.subTest(col=col):
                # th 或 td 任一声明了 width 即可（两者通常成对出现）
                pat = rf"\.agent-list-table t[hd]:nth-child\({col}\)[^{{]*\{{[^}}]*width:\s*(\d+)px"
                m = re.search(pat, css)
                self.assertIsNotNone(m, f"第 {col} 列缺少 px 定宽声明")
                self.assertGreaterEqual(int(m.group(1)), min_w,
                                        f"第 {col} 列宽度 {m.group(1)}px 小于安全下限 {min_w}px")

    def test_text_columns_have_no_fixed_width(self):
        """名称（1）与类型（2）是弹性列，不得设 px 定宽，否则无法吸收剩余空间。"""
        css = _css()
        for col in (1, 2):
            with self.subTest(col=col):
                pat = rf"\.agent-list-table t[hd]:nth-child\({col}\)[^{{]*\{{[^}}]*width:\s*\d+px"
                self.assertIsNone(re.search(pat, css),
                                  f"第 {col} 列（文本列）不应设 px 定宽，应留弹性吸收剩余空间")

    def test_td_overflow_hidden_for_fixed_layout(self):
        """fixed 布局下 td 必须 overflow: hidden，否则超长内容会溢出到相邻列。"""
        css = _css()
        m = re.search(r"\.agent-list-table td\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "未找到 .agent-list-table td 规则")
        self.assertIn("overflow: hidden", m.group(1),
                      "fixed 布局下 td 必须 overflow: hidden 兜底裁切")

    def test_al_scope_is_deboxed(self):
        """`.al-scope`（Hook 列档数注记）必须去盒化：无 border、无 padding、无 background。

        2026-10-15 层级重构：此前是虚线描边徽标，与实底状态胶囊并排时同一格出现两种盒子，
        虚线那个并不显得"更弱"，反而像"另一种东西"，视觉噪音与主状态抢权重。
        档数是元信息，按密集数据表原则（盒子只承载主信息）降为裸文本。
        """
        css = _css()
        m = re.search(r"\.al-scope\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "未找到 .al-scope 规则")
        body = m.group(1)
        self.assertNotIn("border", body, ".al-scope 不应有 border（去盒化）")
        self.assertNotIn("padding", body, ".al-scope 不应有 padding（去盒化）")
        self.assertNotIn("background", body, ".al-scope 不应有 background（去盒化）")
        self.assertIn("color: var(--faint)", body, ".al-scope 应为 faint 色裸文本")
        self.assertIn("font-family: var(--mono)", body, ".al-scope 应为 mono 字体")


class ConfigPortCardContractTest(unittest.TestCase):
    """§2.10「配置导入 / 导出」卡片契约（v0.30.0 双轨测试轨）。

    守住三件事：① 卡片与两个动作入口存在（HTML 结构 + data-action 分发）；
    ② 行内控件容器不写 inline ``width:100%``（v0.29.1 裁剪缺陷根因，规范
    §2.10「组件约束」）；③ 规范 §2.10 与 dashboard.html 的卡片标题字面
    镜像（MD↔HTML 同源，防漂移）。
    """

    def test_card_and_actions_exist(self):
        src = _src()
        self.assertIn('id="cfg-port-card"', src, "设置页缺少 #cfg-port-card 卡片")
        self.assertIn('id="cfg-export-path"', src, "缺少导出路径输入框")
        self.assertIn('id="cfg-import-path"', src, "缺少导入路径输入框")
        self.assertIn('data-action="export-config"', src, "缺少导出按钮动作入口")
        self.assertIn('data-action="import-config"', src, "缺少导入按钮动作入口")
        # 分发器接线：两个动作必须挂进全局 data-action 分发链
        self.assertIn('a === "export-config") exportConfigAction()', src)
        self.assertIn('a === "import-config") importConfigAction()', src)

    def test_control_rows_no_inline_width_100pct(self):
        """卡片行内控件容器不得写 inline width:100%（v0.29.1 裁剪根因）。

        缺陷机理：``.row .v`` 按 max-content 定宽 + overflow:hidden，控件
        inline ``width:100%`` 撑满后，同行兄弟节点（按钮）被排到 .v 之外
        裁掉——有元素、无像素、点不到。守卫方式：cfg-port 卡片的两个
        ``.v`` 容器必须用 flex 布局且不含 ``width:100%``。
        """
        src = _src()
        # 卡片模板整体片段（从 cfg-port-card 到卡片闭合）
        m = re.search(r'id="cfg-port-card".*?</div>\s*`;\n', src, re.S)
        self.assertIsNotNone(m, "找不到 cfg-port-card 模板片段")
        frag = m.group(0)
        self.assertNotIn(
            "width:100%", frag,
            "cfg-port-card 行内控件写了 inline width:100%（v0.29.1 裁剪缺陷根因，"
            "改用 flex 填充，见规范 §2.10「组件约束」）",
        )
        self.assertIn("display:flex", frag, "控件容器应为 flex 布局")
        self.assertIn("flex-wrap:wrap", frag, "控件容器应允许换行（窄宽度兜底）")

    def test_spec_and_html_title_mirror(self):
        """规范 §2.10 与 dashboard.html 的卡片标题字面一致（MD↔HTML 镜像）。"""
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("配置导入 / 导出卡片", spec, "DESIGN.md §2.10 缺该卡片规范")
        self.assertIn("#cfg-port-card", spec, "规范未登记 #cfg-port-card 选择器")
        src = _src()
        self.assertIn("<h4>配置导入 / 导出</h4>", src, "HTML 卡片标题与规范不一致")


class RunTaskModalWrapperContractTest(unittest.TestCase):
    """runTaskModal 回调必须返回 {ok, message, detail}（v0.30.0 修复的缺陷门禁）。

    缺陷机理：``runTaskModal`` 判 ``ok = !!r.ok``，而 ``runCli`` 返回
    ``{code, stdout, stderr}``（Rust run_cli 的 JSON 外壳，无 ok 字段）——
    回调裸传 ``() => runCli(...)`` 时**即使 CLI 成功（code 0）任务模态也显示
    「失败」**。v0.28.0 的活动端点/自动发现切换两处即中招（成功也报失败），
    v0.30.0 的导入/导出初版复制了同一模式。本断言守住四处调用都必须走
    async 包装（与「应用预设」的既有正确模式一致）。
    """

    # 四处调用点（改代码必须同步更新此表）。
    _CALLS = [
        "runTaskModal(\"导出配置\", async () =>",
        "runTaskModal(\"导入配置\", async () =>",
        "runTaskModal(\"切换活动端点\", async () =>",
        "runTaskModal(\"切换自动发现\", async () =>",
    ]

    def test_all_four_calls_use_async_wrapper(self):
        src = _src()
        for call in self._CALLS:
            self.assertIn(call, src, f"缺少包装模式: {call!r}（裸传 runCli 会让成功显示失败）")

    def test_no_bare_runcb_in_taskmodal(self):
        """runTaskModal 的回调里不得再出现裸 ``() => runCli(`` 形态。"""
        src = _src()
        bare = re.findall(r"runTaskModal\([^,]+,\s*\(\)\s*=>\s*runCli\(", src)
        self.assertEqual(
            bare, [],
            "runTaskModal 回调裸传 runCli（{code,stdout,stderr} 无 ok 字段，成功也显示失败）",
        )


class EndpointStatusAllContractTest(unittest.TestCase):
    """概览页「端点状态」多端点整体渲染契约（v0.30.0 用户反馈落地）。

    用户反馈「首页的整体检查不应该具体到某个具体的端点」→
    ``--endpoint-status`` 无 ``--profile`` 检查端点库全部端点
    （kind=endpoint-status-all），GUI 渲染汇总 verdict + 每端点一行。
    本断言守住渲染分支与汇总语义不被回退成单端点绑定。
    """

    def test_all_endpoints_render_branch_exists(self):
        src = _src()
        self.assertIn(
            'st.kind === "endpoint-status-all"', src,
            "缺少多端点渲染分支（回退成只渲染单活动端点会违背整体检查语义）",
        )
        self.assertIn('"全部连通"', src, "缺少汇总 verdict 文案（全部连通）")
        self.assertIn('"部分不通"', src, "缺少汇总 verdict 文案（部分不通）")
        self.assertIn("重新检查连通性", src, "多端点视图缺少重试入口")

    def test_reprobe_does_not_pass_profile(self):
        """整体检查不得带 --profile（带了对单端点，违背用户反馈）。"""
        src = _src()
        self.assertIn(
            'runCli(["--endpoint-status", "--format", "json"])', src,
            "reprobe 应调用无 --profile 的整体检查",
        )
        self.assertNotIn(
            'runCli(["--endpoint-status", "--profile"', src,
            "reprobe 不得绑定 --profile（整体检查语义回退）",
        )

    def test_full_check_runs_snapshot_and_endpoint(self):
        """全量检查 = --snapshot（与托盘巡检同源）+ --endpoint-status 双命令。

        用户反馈（2026-10-22）：「首页的检查应该显示后台全量检查的内容，
        和状态栏的功能统一」——概览页检查必须跑与托盘巡检同一条
        --snapshot（4 维度对比），缺任一命令即语义回退。
        """
        src = _src()
        self.assertIn(
            'runCli(["--snapshot", "--format", "json"])', src,
            "全量检查缺 --snapshot（4 维度对比，与托盘巡检同源）",
        )
        self.assertIn("SNAPSHOT_DIFF_CACHE", src, "缺 4 维度 diff 渲染缓存")
        self.assertIn('"检测到变更"', src, "缺 4 维度汇总 verdict 文案")
        self.assertIn('"全部稳定"', src, "缺 4 维度稳定态文案")

    def test_full_check_unified_table_inline_details(self):
        """统一 UI（2026-10-22 用户反馈「直接在原有的内容中显示即可，
        不需要单独展示详情，请统一 ui 展示」）：

        - 4 维度 + 端点合并**一张 kv 表**（dimsRows + epRows 同一 tbody）；
        - 变更明细**行内展开**（维度行内直接列 name: detail）；
        - **不得**有「变更详情」跳转链接（不引导去单独页面）。
        """
        src = _src()
        # 一张表：dimsRows 与 epRows 拼进同一 tbody（中间隔分组行）
        self.assertIn(
            "dimsRows +", src,
            "4 维度与端点应合并同一张 kv 表（统一 UI）",
        )
        self.assertIn(
            "epRows +", src,
            "端点行应与 4 维度同表（统一 UI）",
        )
        # 两类数据之间必须有分组表头（语义分组，防混排回退）
        self.assertIn(
            '<tr class="kv-group"><td colspan="2">变更对比 · 4 维度</td></tr>', src,
            "4 维度行前缺分组表头（两类数据混排，语义断裂）",
        )
        self.assertIn(
            '<tr class="kv-group"><td colspan="2">端点连通性</td></tr>', src,
            "端点行前缺分组表头（两类数据混排，语义断裂）",
        )
        # 行内明细：维度行内直接渲染变更条目
        self.assertIn(
            "c.name", src,
            "变更明细应行内展开（维度行内直接列 name: detail）",
        )
        # 不得有跳转链接
        self.assertNotIn(
            'data-goto="changes" class="muted">变更详情', src,
            "全量检查区不得有「变更详情」跳转链接（用户要求直接显示，不单独展示）",
        )
