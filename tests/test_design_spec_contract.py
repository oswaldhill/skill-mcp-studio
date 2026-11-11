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

import html as html_mod
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
    # 这是 2026-10-11 实测的缺口：我曾在某设置页里连写了 `.table-wrap` 与 `.faint`
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
        # 2026-11-06：`ts-label` 随「假阶段进度」（task-stage 那套）一起删除，
        # 已无任何 markup/CSS 引用，按「只许减少」的规则从这里移除。
        "input", "kv", "panel", "pf-add", "pf-rm",
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
        # 2026-11-06 统一分页：旧的内边距档位被等宽页码取代（DESIGN.md §2.5d）
        (".pagination .pg-num", "min-width", "32px"),
        (".path-field-row button", "padding", "var(--sp-1) var(--sp-3)"),
        (".chg-btn", "min-height", "32px"),
        (".insight-dialog", "width", "min(1040px, 100%)"),
        (".ad-modal", "--modal-w", "min(880px, 94vw)"),
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

    # ── 反方向：MD → HTML ────────────────────────────────────────────────
    # 2026-10-23 补：DESIGN.md「附：双轨强制机制」原文写着「本文件与 HTML 可读版的
    # 章节由门禁**双向**比对 —— 两侧都不许单方面新增章节」，但此前只实现了
    # HTML→MD 一条。于是 §2.3d（图例放置与对齐）只在 MD 里存在、HTML 里整节缺失，
    # 门禁全绿 —— 正是 implements-only-one-direction 的沉默失败。
    @staticmethod
    def _section_core(raw: str) -> str:
        """把标题行归一到「核心词」：去标签/反引号/行首编号/括号说明/锚点井号。"""
        txt = re.sub(r"<[^>]+>", " ", raw)
        txt = html_mod.unescape(txt)
        txt = txt.replace("`", "").replace("#", "").strip()
        txt = txt.split("（")[0].strip()
        txt = re.sub(r"^[0-9]+[a-z]?\.?\s*", "", txt).strip()
        txt = txt.lstrip("附：").strip()
        return re.sub(r"\s+", "", txt)

    def test_every_md_section_appears_in_html(self):
        """MD 的每个章节标题（核心词）也必须在 HTML 里作为一个标题出现。

        取 HTML 的 ``h1``–``h4``：``h1`` 是文档标题，``h2``/``h3`` 是章节，``h4`` 是
        §5 检查清单的四个分组（MD 里是 ``###``，HTML 里折叠成 ``h4``）—— 只取 h2/h3
        会把这四个当成「缺失」，产生误报。
        """
        md = SPEC.read_text(encoding="utf-8")
        md_cores = [
            self._section_core(line.lstrip("#"))
            for line in md.splitlines()
            if re.match(r"^#{2,3}\s", line)
        ]
        md_cores = [c for c in md_cores if c]

        raw_html = SPEC_HTML.read_text(encoding="utf-8")
        html_cores = [
            self._section_core(m)
            for m in re.findall(r"<h[1-4][^>]*>(.*?)</h[1-4]>", raw_html, re.S)
        ]
        html_cores = [c for c in html_cores if c]

        missing = [
            c for c in md_cores
            if not any(c in h or h in c for h in html_cores)
        ]
        self.assertEqual(
            missing[:20],
            [],
            "以下 MD 章节在 DESIGN.html 的标题里找不到（MD 单方面新增/未同步）：%r"
            % missing[:20],
        )


class CardLabelColumnAlignmentTest(unittest.TestCase):
    """卡片里「路径区」与「能力摘要区」的标签列必须逐项同构（2026-10-12 用户反馈）。

    用户截图指出设置页卡片「最好保持对齐」。实测错位来自两套几何：
    `.ac-path-row` 是 `grid` + 58px 标签列 + 无竖线，而 `.ac-meta-row` 是
    `flex` + `.k` 宽 74px + `border-right` 竖线 —— 标签列宽、字体、分隔线全不一致，
    于是 APP/CLI/CONFIG 与 Skills/MCP 两组的值区起点差 16px，一眼能看出错位。

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
        """淡化变体**只改颜色不改形状**（用户问「Skill 与 MCP 样式为何不同」）。

        根因：`.is-dim` 曾设 `border-color: var(--line)`，而默认胶囊是透明无边框，
        于是同一张卡片里 Skills 显示成方框、MCP 是纯文本。现改为 transparent，
        并让两行（Skills / MCP）在未安装时统一淡化。
        """
        self.assertEqual(_norm_ws(_decl(".agent-card .ac-path-val.is-dim", "border-color")),
                         "transparent", "淡化变体不得引入可见边框（须与默认胶囊同形）")
        self.assertEqual(_norm_ws(_decl(".agent-card .ac-path-val.is-dim", "background")),
                         "transparent", "淡化变体背景应透明")
        src = _src()
        for fn in ("_agentSkillsSummary", "_agentMcpSummary"):
            i = src.index(f"function {fn}(")
            j = src.find("\nfunction ", i + 10)
            body = src[i:j if j > 0 else i + 900]
            self.assertIn('const dimCls = t.installed ? "" : " is-dim";', body,
                          f"{fn} 未按安装状态使用淡化变体（两行应一致）")


    def test_value_and_empty_have_identical_metrics(self):
        """值胶囊与「未收录」空态必须**度量完全一致**，否则 meta 带高度会随内容变化。

        这是 2026-10-12 实测抓到的真实缺陷：`.ac-path-none` 比 `.ac-path-val` 少 3px
        （字号少 1px + 缺那条 `border: 1px solid transparent`），于是"MCP 未收录"的卡片
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
        """主干源码不得出现 ai-memory 命令字符串（v0.29.0 剥离后）。

        v0.33.0：Hook 功能整体移除，原先唯一被检的 ``core/hooks_fixer.py`` 已删除。
        断言范围随之扩大为**全部主干 Python 源码**（core/ 与 scan.py）——
        覆盖面只加不减，仍是同一条反向守护。
        """
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        sources = sorted((root / "core").glob("*.py")) + [root / "scan.py"]
        self.assertTrue(sources, "未找到主干 Python 源码")
        offenders = []
        for path in sources:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "ai-memory hook" in text or "is_ai_memory" in text:
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(
            [], offenders,
            "主干源码不得含 ai-memory 命令 / is_ai_memory 字段：%r" % offenders,
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
                      "标签列未定宽：不同页面图例名字长短不一会让色点列错位")

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
         同行 MCP 却是 `.tag` 胶囊 → 混形态。
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

    def test_mcp_na_cells_are_tags(self):
        """MCP 列里原先的纯文字「不支持 / 0」用中性 .tag 胶囊。

        v0.33.0：Hook 列随 Hook 功能整体移除，原先一并检查的「未收录 / 仅审计」
        两个占位文案只存在于 Hook 单元格，现已在页面里不复存在，故从判据中移除；
        剩下的「不支持 / 0」仍是 MCP 列真实产出的两种空态，断言强度不变。
        """
        body = self._row_renderer_body()
        # v0.39.7：MCP 「不支持」改为与约束一致的「—」破折号（tag-none），
        # 「0」仍是中性 .tag。两者都必须是标签形态而不是裸文字。
        for label in ("·", "0"):
            with self.subTest(label=label):
                # v0.39.7：空态可能带修饰类（如 .tag-none），只要根类是 .tag 即可
                self.assertRegex(body, rf'class="tag[ "][^>]*>{re.escape(label)}<',
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
        self.assertIn("|#.ok:", src, "MCP 的 data-help 应含色点图例行")
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
        """状态列（安装/技能目录/MCP）的 th 与 td 必须居中。

        用户反馈（2026-10-14）：「安装 技能目录等内容，没有和上面的标题栏居中对齐」。
        这三列的单元格是单枚徽标/短标签，左对齐时贴着单元格左缘，与更宽的列头
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


class TrayPanelDimsTest(unittest.TestCase):
    """托盘面板四格统计必须与产品实际能力一致（v0.39.8）。

    用户截图反馈：「这里的 hook 还存在，请修改成 DSH 插件」。
    Hook 功能已于 v0.33.0 整体下线（CLI / GUI / 配置 / 代码全删），但托盘面板
    第四格一直写着 Hook——它永远读不到数、恒为 0，既误导又占位置。
    """

    def test_no_hook_dim_in_tray(self):
        pop = (ROOT / "gui" / "popover.html").read_text(encoding="utf-8")
        self.assertNotIn('"hooks", "Hook"', pop,
                         "托盘面板不应再有 Hook 格：Hook 功能已于 v0.33.0 下线")

    def test_dsh_dim_present(self):
        pop = (ROOT / "gui" / "popover.html").read_text(encoding="utf-8")
        self.assertIn('["dsh", "DSH 插件"', pop,
                      "第四格应显示 DSH 插件（与本工具实际提供的 DSH 插件页同源）")

    def test_totals_provide_dsh_count(self):
        import subprocess
        import sys as _sys
        out = subprocess.run(
            [_sys.executable, "-c",
             "import sys; sys.path.insert(0,'.');"
             "from scan import _snapshot_totals;"
             "print(sorted(_snapshot_totals({'agents':[],'skills':{},'mcp':{}}).keys()))"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn("'dsh'", out.stdout, "totals 必须带 dsh 维度，否则面板第四格恒为 0")
        self.assertNotIn("'hooks'", out.stdout, "totals 不应再有 hooks 维度")


class ListRowAffordanceTest(unittest.TestCase):
    """主表的行级交互与空态形态（v0.39.7 用户评审整改）。

    用户定了三条边界：不合并 APP/CLI/CONFIG、类型保留独立列、安装列保留。
    在这些边界内改进：
    1. 整行可点（含键盘）——此前只能瞄准右上角 64px 的「详情」按钮；
    2. 0 值计数用虚线（`.al-metric.dim`）——此前 0 与 1 几乎同款；
    3. 约束列统一 `N/M`，无约定与不支持共用 `.tag.tag-none` 占位。
    """

    def test_row_is_clickable_with_keyboard(self):
        src = _src()
        self.assertIn('data-row-open="${escapeHtml(a.name)}" tabindex="0" role="button"', src,
                      "行必须可点且键盘可达")
        self.assertIn('body.querySelectorAll("tr[data-row-open]")', src,
                      "行点击事件必须绑定")
        self.assertIn('e.key === "Enter"', src, "键盘 Enter 应能打开详情")

    def test_zero_metric_is_dashed(self):
        css = _css()
        m = re.search(r"\.al-metric\.dim\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "缺少 .al-metric.dim 样式")
        self.assertIn("dashed", m.group(1), "0 值必须用虚线，与有值区分")
        src = _src()
        self.assertIn('(n ? " hit" : " dim")', src, "0 值必须套 .dim")

    def test_empty_state_uses_shared_placeholder(self):
        src = _src()
        self.assertEqual(src.count('class="tag tag-none"'), 2,
                         "约束「无约定」与 MCP「不支持」应共用 .tag.tag-none 占位")
        css = _css()
        m = re.search(r"\.tag\.tag-none\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "缺少 .tag.tag-none 样式")
        self.assertIn("dashed", m.group(1), "空态占位应为虚线，表「没有」而非「未加载」")


class ListStatusCellsClickableTest(unittest.TestCase):
    """主表「安装 / 技能目录 / 约束 / MCP」四列都必须可点开明细（v0.39.6）。

    用户：「后面红色框的几个按钮也需要和绿色框一样是完全可点击的，可以展示出
    它们具体的内容」。此前 APP/CLI/CONFIG 是按钮，技能目录/安装是静态 span，
    约束/MCP 是静态标签 —— 同一行一半能点一半不能，用户会以为功能坏了。
    """

    def _body(self):
        return self._row_renderer_body() if hasattr(self, "_row_renderer_body") else _src()

    def test_install_and_skills_are_buttons(self):
        src = _src()
        self.assertIn('data-popkind="install"', src, "安装列应可点开安装证据")
        self.assertIn('data-popkind="skills"', src, "技能目录列应可点开目录")

    def test_rules_and_mcp_are_buttons(self):
        src = _src()
        # 单路径：data-action="view-rules" + data-client + data-index="0"（属性顺序不固定）
        self.assertRegex(src, r'data-action="view-rules"[^`\n]*data-index="0"',
                         "单路径约束应直接打开只读预览")
        self.assertIn('data-action="list-rules"', src, "多路径约束应先列出再点进去")
        # MCP：有端点的三种状态都要可点（0 与不支持是中性空态，不点）
        self.assertEqual(src.count('class="tag tag-btn') >= 3, True,
                         "MCP 的 ok / warn / err 三态都应是可点标签")

    def test_clickable_badges_have_affordance(self):
        css = _css()
        for sel in ("button.al-ico", ".tag-btn"):
            self.assertIn(sel, css, f"{sel} 缺少可点样式（无 hover 反馈用户不知道能点）")
        self.assertIn("button.al-ico:hover", css)
        self.assertIn(".tag-btn:hover", css)


class NoToastTest(unittest.TestCase):
    """结果通知一律弹框，页面里不得再有吐司/横幅（v0.40.9 用户定案）。

    用户：「整个项目都不允许使用这种吐司，都必须使用弹框。弹框的样式必须按照
    统一的 UI 规范进行设置」。
    """

    def test_no_banner_element_or_style(self):
        src = _src()
        self.assertNotIn('id="banner"', src, "页面级横幅元素已删除")
        css = _css()
        self.assertNotRegex(css, r"\n\s*\.banner[\s.]", "横幅样式已删除")
        self.assertNotIn('class="banner', src, "不得再出现横幅用法")

    def test_show_banner_routes_to_modal(self):
        src = _src()
        # showBanner 必须委托给 modalNotice（.cfm-card 家族），不得自建容器
        start = src.index("function showBanner(kind, text)")
        body = src[start: start + 600]
        self.assertIn("modalNotice(", body, "showBanner 必须走统一弹框")

    def test_notice_card_family_is_the_modal(self):
        src = _src()
        start = src.index("function modalNotice(")
        body = src[start: start + 1600]
        self.assertIn("modal-backdrop", body)
        self.assertIn("modal cfm-card", body, "通知必须是 .cfm-card 弹框家族")


class NoInlineTableAlignmentTest(unittest.TestCase):
    """表格里不得用内联 `style="text-align:..."` 控制列对齐（v0.44.0）。

    实测：表头写着 `<th style="text-align:right">操作</th>`，内联样式优先级高于
    任何样式表选择器，于是三轮 CSS 修复（nth-child → thead 层级 → 显式类）全被压住，
    用户连报三次「没有居中对齐」。对齐必须写在样式表里，用 `.al-op-cell` 之类的类。
    """

    def test_no_inline_text_align_in_tables(self):
        src = _src()
        bad = [ln.strip()[:90] for ln in src.splitlines()
               if 'style="text-align' in ln and ("<th" in ln or "<td" in ln)]
        self.assertEqual(bad, [], "表格单元格不得用内联 text-align 控制对齐")

    def test_operation_column_uses_semantic_class(self):
        src = _src()
        self.assertIn('<th class="al-op-cell">操作</th>', src, "操作列表头必须用 .al-op-cell")
        self.assertNotIn('<th style="text-align:right">操作</th>', src,
                         "禁止内联右对齐（会压过所有样式表规则）")


class CellDisplayGuardTest(unittest.TestCase):
    """单元格不得被装饰类改成非 table-cell（v0.43.4）。

    实测根因：`<td class="al-type">` 与内部 `<span class="al-type">` 共用同一个类，
    而 `.agent-list-table .al-type { display: inline-block }` 命中单元格后，该列宽度
    从 240px 塌到 **72.98px**，整表竖线全部错位——用户连报三轮「线断了 / 没对齐」。
    表头一直正常，所以只量表头量不出这个问题。
    """

    def test_type_cell_does_not_carry_decorative_class(self):
        src = _src()
        self.assertIn('<td class="al-type-cell"><span class="al-type">', src,
                      "类型单元格必须用 .al-type-cell，装饰类只挂在内部 span 上")
        self.assertNotIn('<td class="al-type">', src, "单元格不得直接挂 .al-type")

    def test_cells_pinned_to_table_cell(self):
        css = _css()
        m = re.search(r"\.agent-list-table th, \.agent-list-table td\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m)
        self.assertIn("display: table-cell", m.group(1),
                      "单元格 display 必须显式钉死为 table-cell")

    def test_no_decorative_class_targets_cells(self):
        """装饰类只应出现在树内层，不得与 td 元素同名。"""
        src = _src()
        for bad in ('<td class="al-name"', '<td class="al-type"', '<td class="tag"'):
            self.assertNotIn(bad, src, f"单元格不得挂装饰类：{bad}")


class ListVerticalRulesTest(unittest.TestCase):
    """主表必须有贯通整列的竖线（v0.43.2）。

    用户两轮反馈「中间的线还是断的」。原来表格只有横线 + `border-collapse: collapse`，
    列与列之间靠宽度对齐"看起来"像分隔；表头与表体之间没有一条连续的竖线。
    """

    def test_cells_draw_vertical_rule(self):
        css = _css()
        self.assertRegex(css, r"\.agent-list-table th:not\(:last-child\)::after",
                         "单元格必须用 ::after 画竖线")
        m = re.search(r"\.agent-list-table td:not\(:last-child\)::after\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "缺少 td 竖线规则")
        for prop in ("position: absolute", "top: 0", "bottom: 0", "width: 1px"):
            self.assertIn(prop, m.group(1), f"竖线规则缺 {prop}")

    def test_collapse_disabled(self):
        """`border-collapse: collapse` 下伪元素会被合边裁掉，必须改 separate。"""
        css = _css()
        blocks = re.findall(r"\n\s*\.agent-list-table\s*\{([^}]*)\}", css)
        self.assertTrue(blocks)
        joined = " ".join(blocks)
        self.assertIn("border-collapse: separate", joined)
        self.assertIn("border-spacing: 0", joined)

    def test_header_has_background(self):
        """separate 布局下表头背景需要显式给，否则竖线穿过表头时露白。"""
        css = _css()
        self.assertRegex(css, r"\.agent-list-table thead th \{[^}]*background")


class OperationColumnAxisTest(unittest.TestCase):
    """操作列：表头与按钮必须同轴，且分隔线不被光晕糊住（v0.43.1）。

    用户截图两处：「这里的线没有对齐，连在一起」「标题栏中操作和下面的按钮没有居中对齐」。
    根因有两层：
      1. 表头 `text-align` 被 `.agent-list-table th` 主规则覆盖，仍是左对齐；
      2. 按钮组是 [详情][kebab]，以整组右缘对齐时详情按钮中心偏左 31px。
    """

    def test_header_and_cell_share_explicit_class(self):
        """操作列表头与单元格必须同轴居中，且用**显式类**而不是 nth-child（v0.44.0）。

        前几版靠 `th:nth-child(10)` 单列特判，反复被别的 th/td 规则层叠盖掉，
        用户连报三轮「没有居中对齐」。显式类选择器更短、无 nth 依赖。
        """
        css = _css()
        self.assertIn(".agent-list-table th.al-op-cell", css, "表头需显式 al-op-cell 类")
        self.assertIn(".agent-list-table td.al-op-cell", css, "单元格需显式 al-op-cell 类")
        self.assertRegex(css, r"\.agent-list-table th\.al-op-cell,[\s\S]{0,80}td\.al-op-cell \{[^}]*text-align: center")
        src = _src()
        self.assertIn('<th class="al-op-cell">操作</th>', src, "表头必须带该类")
        self.assertIn('<td class="al-ops al-op-cell">', src, "操作单元格必须带该类")

    def test_detail_and_kebab_are_equalsized(self):
        """详情与更多必须等高（28px），间距固定，详情默认无边框（v0.44.0）。

        用户：「详情和 3 个点的操作按钮的排版布局也不是很好看」——此前详情是
        26px 带边框胶囊、kebab 是 24px 裸图标，一胖一瘦并排。
        """
        css = _css()
        detail = re.search(r"\n  \.al-detail \{([^}]*)\}", css)
        kebab = re.search(r"\.al-ops \.kebab \{([^}]*)\}", css)
        self.assertIsNotNone(detail)
        self.assertIsNotNone(kebab)
        self.assertIn("height: 28px", detail.group(1))
        self.assertIn("height: 28px", kebab.group(1))
        self.assertIn("border: 1px solid transparent", detail.group(1),
                      "详情默认无边框，hover 才浮现胶囊底")

    def test_ops_cell_overflow_visible(self):
        css = _css()
        self.assertIn("td:nth-child(10) { overflow: visible; }", css,
                      "操作列不得裁切，否则 hover 光晕被削成直角与竖线粘连")

    def test_kebab_is_inline_not_overlay(self):
        """次要操作必须与详情并排，**不得**绝对定位覆盖（v0.43.3）。

        上一版 kebab 用 `right: calc(sp-4 + 68px)` 浮在单元格右上角，详情按钮一改
        宽度就压到按钮上（用户：「操作按钮和详情按钮发生了干涉和冲突」）。
        """
        css = _css()
        self.assertNotIn(".kebab-row", css, "覆盖层方案已废弃")
        src = _src()
        self.assertNotIn('class="kebab kebab-row"', src, "行内 kebab 不得再带覆盖层类")
        m = re.search(r"\.al-ops \{[^}]*\}", css)
        self.assertIsNotNone(m)
        self.assertIn("justify-content: center", m.group(0))

    def test_type_column_has_ratio_width(self):
        """类型列必须有宽度声明（v0.45.0 起为百分比 + min-width）。

        `width: auto` 在 `table-layout: fixed` 下按内容算宽、不吸收剩余；
        但写死 px 又会溢出容器。现在的折中是「百分比 + min-width 兜底」。
        """
        css = _css()
        pat = r"\.agent-list-table th:nth-child\(2\),\s*\.agent-list-table td:nth-child\(2\)\s*\{([^}]*)\}"
        m = re.search(pat, css)
        self.assertIsNotNone(m, "缺少类型列宽度声明")
        self.assertRegex(m.group(1), r"width:\s*[\d.]+%", "类型列必须用百分比宽度")
        self.assertIn("min-width", m.group(1), "类型列需要 min-width 兜底可读性")


class ModalFamilyConsistencyTest(unittest.TestCase):
    """四类弹框共用同一套度量（v0.42.0 用户要求「所有弹框同样规范」）。

    容器的**骨架**本来就不同（表单 / 确认 / 通知 / 详情各司其职），但标题刻度、
    按钮度量、主体内边这些「可共享的数字」必须是同一套——否则同一应用里两种
    弹框看起来像两个产品。
    """

    def test_title_scale_is_uniform(self):
        css = _css()
        # 表单弹框标题
        form = re.search(r"\.modal-form \.form-title\s*\{([^}]*)\}", css)
        self.assertIsNotNone(form)
        self.assertIn("font-size: var(--fs-md)", form.group(1))
        self.assertIn("font-weight: 600", form.group(1))
        # 详情弹框标题必须同档（此前 1.35rem/700，与表单差两档）
        ad = re.search(r"\.ad-name\s*\{([^}]*)\}", css)
        self.assertIsNotNone(ad, "缺少 .ad-name 规则")
        self.assertIn("font-size: var(--fs-md)", ad.group(1),
                      "详情弹框标题必须与表单弹框标题同字号")
        self.assertIn("font-weight: 600", ad.group(1),
                      "详情弹框标题必须与表单弹框标题同字重")

    def test_actions_button_metrics_are_uniform(self):
        css = _css()
        form = re.search(r"\.modal-form \.form-actions button\s*\{([^}]*)\}", css)
        cfm = re.search(r"\.cfm-card \.actions button\s*\{([^}]*)\}", css)
        self.assertIsNotNone(form)
        self.assertIsNotNone(cfm)
        for prop in ("min-height: 32px", "padding: var(--sp-3) var(--sp-8)",
                     "border-radius: var(--r-control)", "font-size: var(--fs-sm)"):
            self.assertIn(prop, form.group(1), f"表单弹框按钮缺 {prop}")
            self.assertIn(prop, cfm.group(1), f"确认/通知弹框按钮缺 {prop}")

    def test_body_padding_aligns(self):
        css = _css()
        body = re.search(r"\.modal-form \.form-body\s*\{([^}]*)\}", css)
        ad = re.search(r"\.ad-body\s*\{([^}]*)\}", css)
        self.assertIsNotNone(body)
        self.assertIsNotNone(ad)
        self.assertIn("var(--sp-6)", body.group(1))
        self.assertIn("var(--sp-6)", ad.group(1), "详情弹框主体顶部内边必须与表单弹框一致")


class ConfirmDialogSemanticsTest(unittest.TestCase):
    """确认弹框按破坏性分色（v0.45.1 用户截图）。

    用户截图：「写入共享约束到 Codex」的确认框用了红主按钮 + 红圈图标，
    正文还露着 `**意思相同**` 的 Markdown 星号。
    """

    def test_non_danger_uses_primary_button(self):
        src = _src()
        self.assertIn('${danger ? "cfm-btn-danger" : "cfm-btn-primary"}', src,
                      "主按钮必须按 danger 分色：非破坏性用 accent 主色")

    def test_danger_class_on_card(self):
        src = _src()
        self.assertIn('${danger ? "cfm-danger" : "cfm-info"}', src,
                      "卡片需带语义类，图标才能分色")

    def test_info_icon_is_neutral(self):
        css = _css()
        self.assertRegex(css, r"\.cfm-card\.cfm-info \.cfm-icon \{[^}]*var\(--muted\)",
                         "非破坏性确认的图标必须是中性色，不能沿用 err 红")

    def test_icon_is_svg_not_glyph(self):
        src = _src()
        self.assertNotIn('<div class="cfm-icon">!</div>', src,
                         "图标不得用字面 ! 字符")
        self.assertIn("NOTICE_META.warn.path", src, "图标应复用 NOTICE_META 的描边 SVG")

    def test_no_markdown_stars_in_confirm_message(self):
        """`.cfm-msg` 不解析 Markdown，正文不得出现 ** 星号。"""
        src = _src()
        start = src.index('`写入共享约束到 ${name}`')
        block = src[start: start + 400]
        self.assertNotIn("**", block, "确认正文不得含 Markdown 星号")


class SharedBadgeLabelTest(unittest.TestCase):
    """共享约束徽标文案必须说明「文件里的状态」（v0.45.1）。

    用户问「这个无共享是什么意思？」——absent/missing 曾兜底成「无共享」，
    与「设置里没填内容」混淆，而两者处置完全不同。
    """

    def test_absent_and_missing_have_distinct_labels(self):
        src = _src()
        self.assertIn("absent:", src)
        self.assertIn("未写入", src, "absent 应显示「未写入」")
        # 断言到**具体映射值**，而不是只查有没有 `|| "无共享"` 这个兜底写法：
        # 后者可以被任何一行无关代码满足，反向验证写不出会失败的用例（实测踩到）。
        self.assertIn('absent: ["warn", "未写入"', src, "absent 映射必须直接写「未写入」")
        self.assertIn('missing: ["warn", "未写入"', src, "missing 映射必须直接写「未写入」")
        self.assertNotIn('"无共享"', src, "界面文案中不得再出现「无共享」")

    def test_each_state_has_hint(self):
        src = _src()
        start = src.index("const SHARED_MARK = {")
        block = src[start: start + 900]
        for state in ("current", "covered", "stale", "absent", "missing"):
            self.assertIn(state + ":", block, f"SHARED_MARK 缺 {state}")
        self.assertIn("写入共享约束", block, "提示必须告诉用户下一步怎么做")


class NoticeLayoutTest(unittest.TestCase):
    """通知弹框的排版与交互统一（v0.41.0 用户要求「信息太乱」）。

    用户截图：绿勾配粉红底、正文居中折行、结论与下一步挤在一句里。
    """

    def test_icon_color_follows_kind(self):
        css = _css()
        # 不再一律 err-bg：ok / warn / err / info 各自上色
        for kind in ("ok", "warn", "err", "info"):
            self.assertIn(f".notice-card.notice-{kind} .cfm-icon", css,
                          f"{kind} 通知的图标必须按语义色上色（不能一律红底）")

    def test_body_left_aligned_title_centered(self):
        css = _css()
        m = re.search(r"\.notice-card \.cfm-msg\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "缺少 .notice-card 正文样式")
        self.assertIn("text-align: left", m.group(1), "通知正文必须左对齐")

    def test_split_notice_separates_next_step(self):
        src = _src()
        self.assertIn("function _splitNotice(text)", src, "结论与下一步必须拆分")
        # 精确匹配「渲染进模板」的那一处（`<div class="notice-action">`）：
        # 只查裸类名会被 CSS 规则或注释满足，反向验证写不出会失败的用例。
        # 精确到「模板里那一处」：断言一个更长的、带前导箭头的片段，
        # 避免别处的同类片段（如 o.action 分支）让断言恒真。
        # 断言绑定到**拆分出来的那一段**（parts.next），而不是同工程里另一处
        # 结构相同的 o.action 分支——否则把前者删掉，断言仍被后者满足（实测两次）。
        self.assertIn("${escapeHtml(parts.next)}", src,
                      "拆分出的下一步必须渲染进 .notice-action 块")
        #  与中文不兼容（JS 的  只认 ASCII 单词字符），不得再用它匹配中文动词
        start = src.index("function _splitNotice(text) {")
        body = src[start: start + 900]
        self.assertNotIn("\\b运行", body, "不得用 \\b 匹配中文（实测永不匹配）")


class ModalSkeletonTest(unittest.TestCase):
    """对话框统一骨架：头固定 / 主体滚动 / 操作栏固定（v0.39.5）。

    用户：「保存、取消这些操作按钮永远是显示的，滚动部分不应该包括操作按钮」。
    此前 `.modal` 整体 `overflow-y: auto`，按钮会跟着内容一起滚出视口。
    """

    def test_form_modal_is_three_sections(self):
        css = _css()
        self.assertIn(".modal-form .form-body", css, "缺少可滚动主体")
        self.assertIn(".modal-form .form-actions", css, "缺少固定操作栏")
        body = re.search(r"\.modal-form \.form-body\s*\{([^}]*)\}", css)
        self.assertIsNotNone(body)
        self.assertIn("overflow-y: auto", body.group(1), "主体必须自己滚动")
        actions = re.search(r"\.modal-form \.form-actions\s*\{([^}]*)\}", css)
        self.assertIsNotNone(actions)
        self.assertIn("flex: 0 0 auto", actions.group(1), "操作栏不得参与滚动压缩")

    def test_mount_modal_normalizes(self):
        html = _src()
        self.assertIn("function _normalizeFormModal(root)", html,
                      "应有统一的对话框结构重排函数")
        self.assertIn("_normalizeFormModal(modal);", html,
                      "mountModal 必须调用重排，否则每个弹框都要自己包一层")


class CardTitleAlignmentTest(unittest.TestCase):
    """卡片标题与内容行的对齐（v0.38.6 用户「标题和内容没完全对齐，往下偏」）。

    实测（620px 宽卡片）：改前标题左边 17px、标签左边 17px（已对齐），但标题中心到
    第一行内容中心 36.8px，而行间距是 30px —— 多出 6.8px，视觉上内容「往下偏」。
    改后：标题顶部内边 12px（与左右 16px 的视觉起点一致）、路径区顶部 10px，
    标题到首行的中心距 32.8px，与行间距只差 2.8px。
    """

    def test_title_and_content_share_left_padding(self):
        css = _css()
        head = re.search(r"\.agent-card \.ac-head\s*\{([^}]*)\}", css)
        paths = re.search(r"\.agent-card \.ac-paths\s*\{([^}]*)\}", css)
        self.assertIsNotNone(head, "未找到 .ac-head 规则")
        self.assertIsNotNone(paths, "未找到 .ac-paths 规则")
        # 左右内边同档 —— 标题与标签列因此左对齐
        self.assertIn("var(--sp-7)", head.group(1))
        self.assertIn("var(--sp-7)", paths.group(1))

    def test_title_and_content_vertical_rhythm(self):
        css = _css()
        head = re.search(r"\.agent-card \.ac-head\s*\{([^}]*)\}", css).group(1)
        paths = re.search(r"\.agent-card \.ac-paths\s*\{([^}]*)\}", css).group(1)
        # 标题：顶 12px / 左右 16px / 底 0（底部间距交给路径区）
        self.assertIn("var(--sp-5) var(--sp-7) 0", head,
                      "标题行应为 12px 16px 0：顶部与左右视觉起点一致，底部不留")
        # 路径区：顶 10px（标题到首行的间距因此接近行间距）
        self.assertIn("var(--sp-2) var(--sp-7) var(--sp-5)", paths,
                      "路径区顶部应为 6px：标题底到首行顶 8.8px，与行间隙 6px 同档；"
                      "用 10px 时是 12.8px，内容看起来被整体推下去")


class RowBaselineAlignmentTest(unittest.TestCase):
    """路径行 / 能力摘要行必须**基线对齐**（v0.38.8）。

    标签是 11px / line-height 1.9，值是 12px / line-height 1.5 再套胶囊 padding——
    两者行盒高度不同。用 `align-items: start` 时标签顶对齐值顶，标签文字因此比值的
    文字高 1.5~2px（用户截图红框：「左边的字比右边的字高一点」）。
    `align-items: baseline` 让两边文字的**基线**落在同一条线上，实测底部差 0.00px。
    """

    def test_path_row_uses_baseline_alignment(self):
        css = _css()
        row = re.search(r"\.agent-card \.ac-path-row\s*\{([^}]*)\}", css)
        self.assertIsNotNone(row, "未找到 .ac-path-row 规则")
        self.assertIn("align-items: baseline", row.group(1),
                      "路径行必须基线对齐：标签与值字号不同，顶对齐会让标签偏高")

    def test_meta_row_uses_baseline_alignment(self):
        css = _css()
        meta = re.search(r"\.agent-card \.ac-meta-row\s*\{([^}]*)\}", css)
        self.assertIsNotNone(meta, "未找到 .ac-meta-row 规则")
        self.assertIn("align-items: baseline", meta.group(1),
                      "能力摘要行（SKILLS / MCP）与路径行同构，同样必须基线对齐")


class NoHorizontalScrollTest(unittest.TestCase):
    """主表必须跟着外框压缩，不出现横向滚动条（v0.45.0 用户要求）。

    用户：「默认应该跟着外面的框进行压缩，不应该有横向的滚动条」。
    原来 10 列写死 px 合计 1036，容器一窄就溢出、右侧被截断。
    """

    def test_all_columns_use_percentage(self):
        css = _css()
        for col in range(1, 11):
            with self.subTest(col=col):
                pat = rf"\.agent-list-table t[hd]:nth-child\({col}\)[^{{]*\{{[^}}]*width:\s*[\d.]+%"
                self.assertRegex(css, pat, f"第 {col} 列必须用百分比宽度")

    def test_percentage_sum_not_over_100(self):
        css = _css()
        total = 0.0
        for col in range(1, 11):
            pat = rf"\.agent-list-table t[hd]:nth-child\({col}\)[^{{]*\{{[^}}]*width:\s*([\d.]+)%"
            m = re.search(pat, css)
            self.assertIsNotNone(m, f"第 {col} 列缺少百分比宽度")
            total += float(m.group(1))
        self.assertLessEqual(total, 101.0, f"列宽合计 {total}% 超过 100% 必然溢出")

    def test_text_columns_have_ellipsis_fallback(self):
        """压窄时文本列必须走省略号，而不是撑开或换行。"""
        css = _css()
        m = re.search(r"\.agent-list-table \.al-type\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m)
        self.assertIn("text-overflow: ellipsis", m.group(1))


class AllActionsInMenuTest(unittest.TestCase):
    """操作列只能有「⋯」，详情等操作全部进菜单（v0.45.0 用户要求）。

    用户：「所有的操作按钮都应该在三个点里面，不应该单独有一个展示的内容」。
    """

    def test_ops_column_has_only_kebab(self):
        src = _src()
        m = re.search(r'<td class="al-ops al-op-cell">(.*?)</td>', src, re.S)
        self.assertIsNotNone(m, "未找到操作单元格")
        cell = m.group(1)
        n_btn = cell.count("<button")
        self.assertEqual(n_btn, 1, f"操作列应只有 1 个按钮，实际 {n_btn}")
        self.assertIn('class="kebab"', cell, "唯一按钮必须是「⋯」")
        self.assertNotIn("al-detail", cell, "详情按钮不得常驻在操作列")

    def test_detail_is_first_menu_item(self):
        src = _src()
        start = src.index("function toggleAgentMenu(")
        body = src[start: start + 2600]
        idx_detail = body.index('data-pm="detail"')
        idx_rescan = body.index('data-pm="rescan"')
        self.assertLess(idx_detail, idx_rescan, "「查看详情」应是菜单第一项")

    def test_kebab_is_always_visible(self):
        """唯一入口不能藏：kebab 默认必须有可见颜色，不能只在 hover 才出现。"""
        css = _css()
        m = re.search(r"\.al-ops \.kebab \{([^}]*)\}", css)
        self.assertIsNotNone(m)
        self.assertIn("color: var(--muted)", m.group(1), "kebab 默认必须可见")
        self.assertNotIn("opacity: 0", m.group(1), "kebab 不得默认隐藏")


class ColumnWidthGovernanceTest(unittest.TestCase):
    """`.agent-list-table` 必须用 `table-layout: fixed` + 紧列定宽，防止图标列被撑宽。

    量化诊断（2026-10-14）：默认 auto 布局下，只装一枚 20px 徽标的列被分到 89-125px，
    1440px 窗口下整表约 65% 是横向空白。改为 fixed 布局 + 7 个紧列定宽后，
    三个窗口宽度（1018/1440/1680px）均验证零溢出、零横向滚动。
    不变量：table-layout: fixed 存在，且 7 个紧列各有 px 宽度声明。
    """

    def test_table_layout_is_fixed(self):
        css = _css()
        # v0.45.0 起 `.agent-list-table` 有两条规则（主规则 + min-width 覆盖），
        # 必须合并检查，否则只看第一条会漏。
        blocks = re.findall(r"\n\s*\.agent-list-table\s*\{([^}]*)\}", css)
        self.assertTrue(blocks, "未找到 .agent-list-table 规则")
        self.assertTrue(any("table-layout: fixed" in b for b in blocks),
                        ".agent-list-table 必须声明 table-layout: fixed，否则紧列会被 auto 布局撑宽")

    def test_tight_columns_have_ratio_width(self):
        """10 列必须都声明**百分比**宽度（v0.45.0，用户要求不出现横向滚动条）。

        原来 10 列写死 px 合计 1036，容器一窄就溢出、右侧被截断。改成百分比后
        表格跟着外框压缩，超长文本走省略号。
        """
        css = _css()
        for col in range(1, 11):
            with self.subTest(col=col):
                pat = rf"\.agent-list-table t[hd]:nth-child\({col}\)[^{{]*\{{[^}}]*width:\s*([\d.]+)%"
                m = re.search(pat, css)
                self.assertIsNotNone(m, f"第 {col} 列缺少百分比宽度声明")

    def test_column_widths_sum_to_full(self):
        """各列百分比合计应为 100%，否则一定留白或溢出。"""
        css = _css()
        total = 0.0
        for col in range(1, 11):
            pat = rf"\.agent-list-table t[hd]:nth-child\({col}\)[^{{]*\{{[^}}]*width:\s*([\d.]+)%"
            m = re.search(pat, css)
            self.assertIsNotNone(m, f"第 {col} 列缺少百分比宽度")
            total += float(m.group(1))
        # 允许 85~101：有些列带 min-width 兜底，浏览器会按内容微调；
        # 关键是不能**超过** 100%（超过就一定溢出、出横向滚动条）。
        self.assertLessEqual(total, 101.0, f"列宽合计 {total}% 超过 100% 会溢出")
        self.assertGreaterEqual(total, 85.0, f"列宽合计 {total}% 过小，会留大片空白")

    def test_td_overflow_hidden_for_fixed_layout(self):
        """fixed 布局下 td 必须 overflow: hidden，否则超长内容会溢出到相邻列。

        v0.43.1 例外：操作列显式改为 visible（按钮 hover 光晕需要不被裁切），
        主规则仍保持 hidden 作为其它列的兜底。
        """
        css = _css()
        # 注意：`\.agent-list-table td\s*\{` 会先匹配到
        # `.agent-list-table td:nth-child(10)` 那条（`td` 后面直接是 `:`，\s* 允许零宽）。
        # 必须锚定「td 后面紧跟空格或右括号」，否则拿到的是操作列的覆盖规则。
        # 必须用 `[^{]*` 跳过 `, .agent-list-table td` 这种多选择器：
        # 第 1 行「竖线贯通」规则写的是 `.agent-list-table th, .agent-list-table td {`，
        # 单选择器正则会把它的声明当成 td 主规则（实测踩到）。
        m = re.search(r"^\s*\.agent-list-table td\s*\{([^}]*)\}", css, re.M)
        self.assertIsNotNone(m, "未找到独立的 .agent-list-table td 主规则")
        self.assertIn("overflow: hidden", m.group(1),
                      "fixed 布局下 td 必须 overflow: hidden 兜底裁切")
        op = re.search(r"\.agent-list-table td:nth-child\(10\)\s*\{([^}]*)\}", css)
        self.assertIsNotNone(op, "操作列应有独立的 overflow 覆盖")
        self.assertIn("overflow: visible", op.group(1), "操作列不得裁切 hover 光晕")

    def test_al_scope_is_deboxed(self):
        """`.al-scope`（分层作用域档数注记）必须去盒化：无 border、无 padding、无 background。

        v0.33.0：Hook 列随 Hook 功能整体移除，`.al-scope` 若已无任何引用则该不变量
        自然消解（无从谈「去盒化」）。为避免「类删了但测试还在报红」与「类还在但
        没人管它的样式」两种失真，这里显式分叉：仍被使用时必须去盒化，完全不用时
        必须连 CSS 规则一起清掉 —— 两种情况都有断言，不会静默放过。

        2026-10-15 层级重构：此前是虚线描边徽标，与实底状态胶囊并排时同一格出现两种盒子，
        虚线那个并不显得"更弱"，反而像"另一种东西"，视觉噪音与主状态抢权重。
        档数是元信息，按密集数据表原则（盒子只承载主信息）降为裸文本。
        """
        css = _css()
        m = re.search(r"\.al-scope\s*\{([^}]*)\}", css)
        if m is None:
            self.assertNotIn("al-scope", _src(),
                             "CSS 已无 .al-scope 规则，markup/JS 却还在引用它（死引用）")
            return
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
        self.assertIn("重新全量检查", src, "多端点视图缺少重试入口（卡片头 fc-head）")

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
        # 两列分组网格（v0.30.2 重设计）：4 维度与端点各一组，同网格呈现
        self.assertIn(
            "dimsRows +", src,
            "4 维度行应与端点行同网格呈现（统一 UI）",
        )
        self.assertIn(
            "epRows +", src,
            "端点行应与 4 维度同网格呈现（统一 UI）",
        )
        # 两组必须有分组小标题（语义分组，防混排回退）
        self.assertIn(
            '<div class="fc-group-title">变更对比 · 3 维度</div>', src,
            "4 维度组缺分组小标题（两类数据混排，语义断裂）",
        )
        self.assertIn(
            '<div class="fc-group-title">端点连通性</div>', src,
            "端点组缺分组小标题（两类数据混排，语义断裂）",
        )
        # 状态点行语言（.dot 语义色 + fc-row）
        self.assertIn(
            'class="fc-row"><span class="dot ', src,
            "状态行应用 .dot 语义色点（§2.5 状态覆盖语言）",
        )
        # 动作按钮收进卡片头（不再占底部一整行）
        self.assertIn(
            'class="hd fc-head"', src,
            "卡片头应为 fc-head 两端对齐（动作按钮在标题行右侧）",
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


class SkillVersionUiContractTest(unittest.TestCase):
    """Skills 页版本/更新展示 + 设置页市场源卡片契约（v0.31.0 #4 双轨测试轨）。"""

    def test_skill_table_has_version_and_update_columns(self):
        src = _src()
        # 2026-11-06 用户反馈后合并：「本地 / 远端」两列是**两个不同的量**
        # （本地 = SKILL.md mtime，远端 = 上游仓库基准提交时间），并排显示会让
        # 读者把「07/17 vs 11/02」误读成「本地旧、远端新」。
        # 现在合并为单列「同步」，只给关系结论；具体时间降级到 title。
        # 本断言的意图仍是「技能表必须暴露版本/同步信息」，只是载体变了。
        self.assertNotIn('<th class="st-ver">本地</th>', src,
                         "「本地」列已按用户要求合并，不得单独出现")
        self.assertNotIn('<th class="st-upd">远端</th>', src,
                         "「远端」列已按用户要求合并，不得单独出现")
        self.assertIn('<th class="st-sync"', src, "技能表缺合并后的同步列")
        # 评审修复六项的可机检约束（2026-10-23）
        css = _css()
        self.assertIn(".upg-bar-fill { transition: none !important; }", css,
                      "reduced-motion 未覆盖升级进度条（用户开启减少动效后仍在动）")
        self.assertIn("--modal-w: min(440px, 92vw)", css,
                      "升级模态宽度应走 --modal-w 变量体系")
        # 表格密度统一：升级确认表与主技能表同档 sp-2
        self.assertIn(".upg-table td { font-size: var(--fs-sm); padding: var(--sp-2) var(--sp-2)", css,
                      "升级确认表行内边距应与主技能表同档（sp-2）")
        # 装饰性图标 aria-hidden（ICONS 全体）
        self.assertIn('aria-hidden="true" viewBox=', src,
                      "内联 SVG 图标应统一 aria-hidden，避免读屏器播报")
        # 全量检查空态覆盖 4 维度 + 端点，不只端点
        self.assertIn("尚未检查：点右上「重新全量检查」", src,
                      "全量检查空态文案应覆盖整个检查范围，不只端点连通性")
        self.assertIn("st-sync", _css(), "缺 .st-sync 列样式")

    def test_check_updates_button_and_data_flow(self):
        src = _src()
        self.assertIn('data-action="skill-check-updates"', src, "缺「检查更新」按钮")
        self.assertIn("runSkillCheckUpdates", src, "缺检查更新处理函数")
        self.assertIn('runCli(["--market", "check", "--format", "json"]', src,
                      "检查更新应走 --market check（版本比对）")
        self.assertIn("SKILL_UPDATES", src, "缺更新结果缓存变量")
        # 三态 tag 文案
        self.assertIn("有更新", src)
        self.assertIn("最新", src)

    def test_skill_upgrade_entry_points_and_flow(self):
        """升级入口（v0.31.0 用户反馈定案）：tag 可点击 + kebab 菜单项，
        **不得有独立升级按钮**；确认流走 --market-upgrade --yes。"""
        src = _src()
        # 入口一：可点击 tag（role=button + data 属性）
        self.assertIn('class="tag warn tag-upgradable" data-skill-upgrade=', src,
                      "「有更新」tag 应可点击（tag-upgradable + data-skill-upgrade）")
        # 入口二：kebab 菜单项（outdated 时）
        self.assertIn('data-spm="upgrade"', src, "kebab 菜单缺「升级」项")
        self.assertIn('升级到最新版', src)
        # 不得有独立升级按钮（用户明确反馈去掉）
        self.assertNotIn('class="ghost sm" data-skill-upgrade=', src,
                         "不得有独立升级按钮（tag 即入口，用户定案）")
        self.assertIn("runSkillUpgrade", src, "缺升级处理函数")
        self.assertIn('--market-upgrade", name, "--yes"', src,
                      "升级应走 --market-upgrade --yes（写操作带确认）")
        # 可升级筛选段
        self.assertIn('data-seg="updatable">可升级', src, "筛选段缺「可升级」")
        self.assertIn('seg === "updatable"', src, "筛选逻辑缺 updatable 分支")
        # 升级确认文案：danger 视觉 + 「确认升级」文案（不得误用「确认删除」）
        self.assertIn(">确认升级</button>", src, "升级确认按钮文案应为「确认升级」")
        self.assertIn("confirmText || (danger", src, "confirmModal 应支持自定义确认文案")
        # 「最新」/「有更新」tag 都显示远端版本号或提交时间（用户需求）
        self.assertIn("remoteTime", src, "检查结果缺 remoteTime（远端提交时间）")
        # 2026-11-06：渲染从「显示日期」改为「显示关系」，但「远端信息必须出现在
        # 界面上」这条意图不变 —— 现在它在同步列的 title 里（含完整时间）。
        self.assertIn("远端较新", src, "同步列缺「远端较新」态（有更新）")
        self.assertIn("一致", src, "同步列缺「一致」态")
        self.assertRegex(src, r"function syncCell\(",
                         "缺 syncCell —— 同步列的渲染函数")
        # 确认框带远端信息
        self.assertIn("upg-ver-num", src, "升级确认框应有版本对比条（当前 → 远端）")
        # GUI 入口（v0.31.1）：回滚与远程同步必须有可达的界面，
        # 不能只留 CLI（用户是不可见 CLI 的）。
        self.assertIn('data-spm="rollback"', src, "技能 kebab 缺「回滚到升级前」")
        self.assertIn("runSkillRollback", src, "缺回滚流程函数")
        self.assertIn("--list-skill-backups", src, "回滚前应探测是否存在备份")
        self.assertIn("before-restore-", src, "回滚确认文案应说明当前版本会另存")
        self.assertIn('id="webdav-sync-card"', src, "设置页缺 WebDAV 远程同步卡片")
        self.assertIn("loadWebdavStatus", src, "缺 WebDAV 状态加载")
        self.assertIn("initWebdavActions", src, "缺 WebDAV 动作绑定")
        self.assertIn("--sync-webdav-push", src, "缺推送动作")
        self.assertIn("--sync-webdav-pull", src, "缺拉取动作")
        self.assertIn('type="password"', src, "凭据输入应为 password 类型")
        # GUI 入口（v0.31.1）：回滚与远程同步必须有可达的界面，
        # 不能只留 CLI（用户看不到 CLI）。
        self.assertIn('data-spm="rollback"', src, "技能 kebab 缺「回滚到升级前」")
        self.assertIn("runSkillRollback", src, "缺回滚流程函数")
        self.assertIn("--list-skill-backups", src, "回滚前应探测是否存在备份")
        self.assertIn("before-restore-", src, "回滚确认文案应说明当前版本会另存")
        self.assertIn('id="webdav-sync-card"', src, "设置页缺 WebDAV 远程同步卡片")
        self.assertIn("loadWebdavStatus", src, "缺 WebDAV 状态加载")
        self.assertIn("initWebdavActions", src, "缺 WebDAV 动作绑定")
        self.assertIn("--sync-webdav-push", src, "缺推送动作")
        self.assertIn("--sync-webdav-pull", src, "缺拉取动作")
        self.assertIn('type="password"', src, "凭据输入应为 password 类型（不回显明文）")
        # WebDAV 同步范围纪律（v0.31.1）：凭据/技能包永不进同步清单。
        wd = (ROOT / "core" / "webdav_sync.py").read_text(encoding="utf-8")
        scope = wd[wd.index("SYNC_FILES"):wd.index("CONFIG_NAME")]
        for forbidden in ("webdav_credential", "github_token", "skill_backups"):
            self.assertNotIn(forbidden, scope,
                             f"同步清单不得包含 {forbidden}（凭据/备份不能上远端）")
        self.assertIn("0o600", wd, "凭据文件必须 0600（仅属主可读写）")
        self.assertIn("_mask_credential", wd, "凭据输出必须脱敏")
        # 弹框宽度治理（v0.31.0 收敛）：所有弹框走 --modal-w 变量，
        # 禁止再出现「用 !important 覆盖自身 width」的写法。
        css = _css()
        self.assertIn("width: var(--modal-w, min(560px, 92vw))", css,
                      ".modal 应通过 --modal-w 消费宽度")
        self.assertNotIn("--modal-w: min(440px, 92vw); min-width", css,
                         "升级模态不应再用 min-width 硬写（应改 --modal-w）")
        self.assertIn(".ad-modal { --modal-w: min(880px, 94vw)", css,
                      "宽详情弹框应走变量体系")
        self.assertIn("text-align: left", css,
                      "ad-modal 应显式左对齐（详情排版，不是确认框居中）")
        # 升级弹框承诺「升级前自动备份」——代码里必须真有备份调用，
        # 否则就是 UI 对用户说谎（2026-10-23 评审发现的空承诺）。
        ops = (ROOT / "core" / "skill_market_ops.py").read_text(encoding="utf-8")
        self.assertIn("backup_skill(name)", ops,
                      "升级流程必须真的备份（弹框承诺「升级前自动备份」）")
        self.assertIn('"backups": backups', ops,
                      "备份路径必须随执行结果返回（否则用户不知道去哪回滚）")
        self.assertIn("def restore_skill_backup", ops, "缺回滚实现")
        self.assertIn(".before-restore-", ops,
                      "回滚前必须另存当前版本（回滚本身也要可撤销）")
        # 完成态必须展示版本变迁与失败原因（2026-10-23 用户需求）。
        # 断言必须落在「渲染逻辑」而非类名定义上，否则删掉渲染代码
        # 仍会因 CSS 里残留选择器而误通过（反向验证已证实这点）。
        self.assertIn('<span class="upg-done-ver">',
                      src, "完成态渲染必须输出版本变迁节点（不是仅有 CSS 定义）")
        self.assertIn('class="upg-done-reason err"',
                      src, "完成态失败行必须渲染原因节点")
        self.assertIn("results[i].reason = String(reason);",
                      src, "失败原因必须在升级失败分支被逐技能记录")
        self.assertIn("const verText = st === \"done\" && to !== \"-\"",
                      src, "版本变迁只在成功且远端可判定时展示")
        # 升级确认表：列宽治理 + 取值纪律（2026-10-23 用户反馈「UI 问题」）
        self.assertIn("table-layout: fixed", src, "升级表应定宽布局（防列宽随内容漂移）")
        self.assertIn('<colgroup><col class="c-name">', src, "升级表应显式声明列宽")
        self.assertIn("col.c-arrow", src, "箭头列应独立定宽（不应与技能名争空间）")
        # 版本列不放判定说明文字（长文案会撑破固定列宽且语义错位）
        self.assertNotIn('"（按时间判定）"', src,
                         "版本列不得放「按时间判定」说明文字（应进 title）")
        self.assertIn("const verTip =", src, "应有 verTip() 提供完整取值说明")
        # 警告行必须保留 flex 布局三项（删掉会退化为 block，文案出现单字孤行）
        self.assertIn(".upg-warn { display: flex;", src, "警告行应为 flex 行内布局")
        self.assertIn("text-wrap: pretty", src, "警告行应声明 text-wrap: pretty 防孤字")
        # 升级模态排版（2026-10-23 优化）：进度条 + 状态词 + 汇总统计块
        self.assertIn("upg-bar-fill", src, "升级模态缺进度条")
        self.assertIn("upg-state-word", src, "升级行缺状态词（成功/失败/升级中）")
        self.assertIn("upg-stat-num", src, "完成态缺汇总统计块（语义色数字）")
        self.assertIn("STATE_WORD", src, "缺状态词映射")
        # 单一弹框（2026-10-23 用户反馈「弹框遮挡」）：确认内嵌 upg-modal，
        # 不再叠加 confirmModal
        self.assertIn('id="upg-confirm"', src, "确认阶段应内嵌升级模态（单一弹框）")
        self.assertIn('id="upg-cancel"', src, "确认阶段内嵌取消按钮")
        # 升级流程内不得再调 confirmModal（防回退到双弹框）
        upg_start = src.index("async function runSkillUpgradeModal")
        upg_end = src.index("async function runSkillUpgradeAll")
        upg_body = src[upg_start:upg_end]
        self.assertNotIn("await confirmModal(", upg_body,
                         "升级流程不得叠加 confirmModal（用户定案单一弹框）")
        # 市场源添加表单：不用 placeholder 充当 label（taste-skill 4.6）
        self.assertIn('aria-label="源 ID"', src, "表单字段缺 aria-label（placeholder 不是标签）")
        self.assertIn('<span class="k">源 ID</span>', src, "表单缺可见 label（.k 行结构）")

    def test_github_token_card_exists(self):
        """GitHub token 设置卡片（v0.31.0）：状态行 + 保存/清除，读写经 CLI。"""
        src = _src()
        self.assertIn('id="github-token-card"', src, "设置页缺 GitHub token 卡片")
        self.assertIn("loadGithubTokenStatus", src, "缺状态加载函数")
        self.assertIn("--get-github-token", src, "状态读取应经 CLI")
        self.assertIn("--set-github-token", src, "保存应经 CLI")
        # 脱敏显示 + password 输入
        self.assertIn('type="password" id="gt-input"', src, "token 输入应为 password 型")
        self.assertIn("data.masked", src, "状态行应脱敏显示（前4后4）")

    def test_market_sources_card_exists(self):
        src = _src()
        self.assertIn('id="market-sources-card"', src, "设置页缺市场源卡片")
        self.assertIn("loadMarketSources", src, "缺市场源加载函数")
        self.assertIn("--list-market-sources", src, "市场源卡片应经 CLI 读写")
        self.assertIn("--set-market-source", src)
        self.assertIn("--remove-market-source", src)
        # 默认源可删改的说明
        self.assertIn("可删可改", src)

    # ---- 市场源卡片结构（v0.37.3 用户截图「排版和视觉有问题」后重排） ----
    # 这四条守的是**版面不变量**，不是内部类名：此前源行直接拼进 body、
    # 添加字段与源行连排、按钮用 ghost.sm，整块读起来像散落的表单。

    def test_market_sources_rows_are_grouped(self):
        """.rows 容器决定行内边距与 hairline 分隔线，缺了列表就是一团。"""
        src = _src()
        self.assertIn(
            '<div class="rows" style="font-size:var(--fs-sm)">${rows}</div>', src,
            "市场源行必须包在 .rows 里（`.settings-card .rows .row` 才给行分隔线）")

    def test_market_sources_add_form_is_a_group(self):
        """新增表单必须独立成组并带标题，用户才看得出这是新增入口。"""
        src = _src()
        self.assertIn(
            '<div class="settings-group">\n      <h4>添加源</h4>', src,
            "添加源表单必须放进 .settings-group 并带「添加源」标题")

    def test_market_sources_buttons_use_btn_soft(self):
        """动作按钮统一 .btn-soft：ghost.sm 读起来像文字链接，不像可点操作。"""
        src = _src()
        self.assertNotIn('class="ghost sm" data-ms-toggle', src,
                         "源行「停用」不应再用 ghost.sm")
        self.assertNotIn('class="ghost sm" data-ms-remove', src,
                         "源行「删除」不应再用 ghost.sm")
        self.assertNotIn('class="ghost sm" data-ms-add', src,
                         "「添加源」不应再用 ghost.sm")
        self.assertIn('class="btn-soft" data-ms-add="1"', src,
                      "「添加源」应是 .btn-soft")

    def test_market_sources_fields_have_no_inline_width(self):
        """字段宽度由 CSS 统一撑满，不允许每个字段内联写不同的 min-width。"""
        src = _src()
        for field in ("ms-add-id", "ms-add-label", "ms-add-url"):
            self.assertNotRegex(
                src, rf'id="{field}"[^>]*style="[^"]*min-width',
                f"{field} 不应内联写 min-width（宽度由 `.settings-card .row .v > input` 统一）")
        # 反向确认「统一撑满」这条 CSS 真的存在，而不是靠删断言蒙混过去。
        self.assertIn(
            '.settings-card .row .v > input[type="text"],\n  .settings-card .row .v > select { width: 100%; max-width: 24rem; }',
            src,
            "缺少「设置卡片内表单控件撑满值列」的样式规则")
        # width:100% 只有在值列本身是 flex 增长项时才生效 —— `.row .v` 默认
        # 由内容决定宽度，漏掉 flex:1 会让输入框仍停在内容宽度（实测 180px）。
        self.assertIn(".settings-card .row .v { color: var(--muted); flex: 1; min-width: 0; }",
                      src,
                      "值列必须 flex:1，否则输入框的 width:100% 等于没生效")


class PaginationConsistencyTest(unittest.TestCase):
    """全站只能有一套分页组件（2026-11-06 用户要求「统一一下分页组件」）。

    ## 现状（改造前）

    项目里同时跑了 4 处、3 种样式的分页：
    - `.pagination`（_paginationBar）：页码 + 上一页/下一页 + 跳转输入框；
    - `.skill-pager`（技能表）：只有「‹ 上一页 | 第 3 / 13 页 · 共 248 个 | 下一页 ›」；
    - `.upg-pager`（升级确认框）、`.skill-pager`（合并预览）：同 `.skill-pager`。

    用户截图指出最后这种**没有页码可点**，只能一页页翻。

    ## 判据

    1. 只存在一个分页渲染函数 `paginationBar`；
    2. 它必须产出页码按钮（`pg-num`）；
    3. 源码里不得再出现另外三套分页的类名或 `data-*-pg` 私有协议。
    """

    def test_single_pagination_renderer(self):
        src = _src()
        self.assertEqual(
            src.count("function paginationBar("), 1,
            "分页渲染函数必须唯一（paginationBar）",
        )

    def test_renderer_emits_page_numbers(self):
        src = _src()
        i = src.find("function paginationBar(")
        self.assertGreater(i, 0)
        body = src[i:src.find("\nfunction ", i + 10)]
        self.assertIn("pg-num", body, "分页控件缺少可点击的页码")
        self.assertIn("上一页", body)
        self.assertIn("下一页", body)

    def test_no_competing_pagination_markup(self):
        src = _src()
        for stale in ("skill-pager", "upg-pager", "pg-btn", "data-upg-pg", "data-mp-pg"):
            self.assertNotIn(
                stale, src,
                f"仍存在另一套分页实现：{stale}（应统一到 .pagination）",
            )

    def test_renderer_actually_runs(self):
        """分页函数必须真的能执行（2026-11-06 实测踩过的坑）。

        本次改造中我把常量名 `PAGINATION_WINDOW` 写成了 `PAGINATION_WIND`，
        静态断言全绿，但一调用就 ReferenceError。只查字符串存在**抓不住**
        这类拼写错误，必须实际执行一次。
        """
        import subprocess

        src = _src()
        # 需要一并执行三块：每页条数常量、页码窗口常量、渲染函数。
        # 起点取最早出现的那个常量（2026-11-06 常量前移过一次，不能写死顺序）。
        # 精确取三块，不要取区间：区间里夹着 DOM 相关的顶层语句（addEventListener 等），
        # 在 node 里会因 document 未定义而失败（2026-11-06 实测）。
        fstart = src.index("function paginationBar(page, pages, opts) {")
        lines = src.splitlines()
        def find_line(prefix: str) -> int:
            return next(k for k, line in enumerate(lines) if line.startswith(prefix))

        blocks = [
            "\n".join(lines[find_line("const PAGE_SIZE_OPTIONS"):find_line("function savePageSize")]),
            lines[find_line("const PAGINATION_WINDOW")],
        ]
        i = fstart
        depth, j = 0, fstart
        while True:
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        code = "\n".join(blocks) + "\n" + src[fstart : j + 1]
        # 被提取的片段会间接调用 loadStore → localStorage，需要最小桩
        probe = (
            'globalThis.localStorage = { getItem: () => null, setItem: () => {} };\n'
            'var loadStore = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } };\n'
            'var saveStore = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };\n'
        ) + code + """
const out = [];
for (const [p, n] of [[2,13],[0,5],[6,13]]) {
  const h = paginationBar(p, n, { total: 10 });
  out.push(String(h).includes("pg-num"));
}
const single = String(paginationBar(0, 1, { total: 1, perPage: 20 }));
console.log(JSON.stringify({ ok: out, single }));
"""
        res = subprocess.run(
            ["node", "-e", probe], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(res.returncode, 0, f"分页函数执行报错：\n{res.stderr}")
        import json as _json

        data = _json.loads(res.stdout.strip().splitlines()[-1])
        self.assertTrue(all(data["ok"]), "多页时应渲染出页码按钮")
        # 单页时页码部分为空，但「共 N 条」与每页条数选择器仍须出现
        # （2026-11-06：第一版返回空串，只有 1 页时用户看不到任何计数与选择器）
        self.assertIn("共 1 条", data["single"], "单页时应显示总数")
        self.assertIn("pg-size-sel", data["single"], "单页时仍应可调整每页条数")
        self.assertNotIn("pg-num", data["single"], "单页时不应出现页码按钮")

    def test_shows_range_and_page_size_selector(self):
        """分页必须显示「当前第几到第几 / 共多少」和「每页几条」可切换
        （2026-11-06 用户要求：「还缺少当前显示几个、每一页显示几个这种配置」）。

        改造前只有一句「共 248 个」，用户看不出当前这页覆盖了哪 20 个，
        也无法改变每页条数。

        判据（可机检）：
        1. 渲染函数接受 perPage 与 total，产出「第 X-Y 条 / 共 N 条」；
        2. 存在每页条数选择器 `.pg-size`，且选项来自统一常量（不得各页写死）；
        3. 选择器变化时回到第 1 页（否则用户可能落在越界页）。
        """
        src = _src()
        i = src.find("function paginationBar(")
        self.assertGreater(i, 0)
        body = src[i : src.find("\nfunction ", i + 10)]
        self.assertIn("perPage", body, "分页渲染没有接收每页条数")
        self.assertIn("pg-size", body, "缺少每页条数选择器")
        self.assertIn("pg-range", body, "缺少「当前显示第几条到第几条」")
        # 选项必须来自统一常量，不允许各页硬编码
        self.assertIn("PAGE_SIZE_OPTIONS", src, "每页条数选项没有统一常量")
