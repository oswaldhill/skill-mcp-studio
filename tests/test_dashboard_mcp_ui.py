"""MCP 面板（gui/dashboard.html）界面护栏。

P2 修复之后，「端点挂载状态」列（端点键 + 状态 + 来源长文案）与下方
「端点 × 客户端 覆盖矩阵」表达的是同一份数据，界面出现两张等价表：既重复，
又因为在单元格里重复端点名而难以纵向扫读。本护栏锁定合并后的单表形态：

* 单表：端点状态列 + 条目列，不再有第二张矩阵表；
* 端点名只出现在表头一次（表头保留大小写，不被 thead 的 uppercase 改写）；
* 状态用「形态 + 色彩」双编码，不单独依赖颜色；
* 异常行用左侧警示条标注，不与客户端名争视觉权重；
* 「不支持 MCP」与「缺失」严格区分：前者是能力缺失（不适用、横杠、不计异常），
  后者是声明要挂却没挂（异常、空心环、左侧警示条）；
* 真实数据渲染快照（node 可用时执行）。
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "gui" / "dashboard.html"
NODE = shutil.which("node")


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def _script() -> str:
    m = re.search(r"<script>(.*?)</script>", _src(), re.S)
    assert m is not None, "dashboard.html 缺少 script 块"
    return m.group(1)


def _fn(name: str) -> str:
    body = _script()
    i = body.index(f"function {name}(")
    j = body.index("\n}\n", i) + 3
    return body[i:j]


def _render_fn() -> str:
    return _fn("renderMcpClients")


def _css_block() -> str:
    s = _src()
    i = s.index("/* ============ MCP 面板")
    j = s.index("\n  /* 一键合并预览", i)
    return s[i:j]


def _rows(html: str):
    """把表格解析成 [(tr 属性, [单元格文本]), ...]，便于断言对齐后的内容。"""
    out = []
    for attrs, inner in re.findall(r"<tr([^>]*)>(.*?)</tr>", html, re.S):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", inner, re.S)
        ]
        out.append((attrs, cells))
    return out


def _legend(html: str) -> str:
    m = re.search(r'<div class="skill-legend mcp-legend">(.*?)</div>\s*<div class="table-scroll">', html, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""


def _render(mcp: dict, endpoints: list) -> str:
    """在 node 里执行真实 renderMcpClients，返回它写入面板的 HTML。"""
    src = _src()
    esc = re.search(r'const escapeHtml = \(v\) =>.*?&#39;"\);', src, re.S).group(0)
    translate = re.search(r"const CLASS_TRANSLATE = \{[^}]*\};", src).group(0)
    color = re.search(r"const CLASS_COLOR = \{[^}]*\};", src).group(0)
    js = "\n".join(
        [
            "const SNAP = " + json.dumps({"mcp": mcp, "endpoints": endpoints}, ensure_ascii=False) + ";",
            translate,
            color,
            esc,
            'const holder = { _v: "", set innerHTML(v) { this._v = v; }, get innerHTML() { return this._v; } };',
            'const $ = (id) => (id === "mcp-clients" ? holder : null);',
            _fn("_supportsMcp"),
            _render_fn(),
            "renderMcpClients(SNAP.mcp, SNAP.endpoints);",
            "process.stdout.write(holder._v);",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.js"
        path.write_text(js, encoding="utf-8")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise AssertionError("node 渲染失败：" + proc.stderr[:400])
    return proc.stdout


def _client(name, expected, observed, missing, undeclared,
            explicit=False, inventory=None, supports=True, drift=None):
    return {
        "name": name,
        "mcp_attach": expected,
        "observed_attach": observed,
        "missing_attach": missing,
        "undeclared_attach": undeclared,
        "has_explicit_attach": explicit,
        "supports_mcp": supports,
        "config_path": "~/.demo/mcp.json" if supports else "",
        "inventory": inventory or [],
        "drift": drift or {"suspected": False, "lost": [], "backup_count": 0,
                           "last_backup": "", "last_backup_at": ""},
    }


def _drift_client(name, lost):
    """被外部工具改写的客户端：有本工具备份，但期望的端点已不见。"""
    return _client(name, lost, [], lost, [], drift={
        "suspected": True, "lost": lost, "backup_count": 3,
        "last_backup": "~/.demo/mcp.json.bak-20260921-160315-913403",
        "last_backup_at": "2026-09-21 16:03:15",
    })


MCP_OK = {
    "clients": [
        _client(
            "已接入",
            ["ep1", "ep2"],
            ["ep1", "ep2"],
            [],
            [],
            inventory=[{"key": "s1", "classification": "attached", "endpoint_key": "ep1"}],
        ),
        _client("缺配置", ["ep1", "ep2"], [], ["ep1", "ep2"], []),
    ]
}
# 实况形态：ima.copilot 已安装但没有 MCP 配置文件 -> supports_mcp=False、期望与缺失均为空
MCP_UNSUPPORTED = {
    "clients": [
        _client("正常", ["ep1", "ep2"], ["ep1", "ep2"], [], [],
                inventory=[{"key": "s1", "classification": "attached", "endpoint_key": "ep1"}]),
        _client("ima.copilot", [], [], [], [], supports=False),
    ]
}
ENDPOINTS = [
    {"key": "ep1", "url": "https://e1.example/mcp"},
    {"key": "ep2", "url": "https://e2.example/mcp"},
]


class StaticShapeTest(unittest.TestCase):
    """不依赖 node 的源码护栏：结构一旦回退立即失败。"""

    def test_endpoint_name_rendered_only_in_header(self):
        fn = _render_fn()
        self.assertEqual(fn.count("escapeHtml(k)"), 1, "端点名应只在表头出现一次")

    def test_single_table_render(self):
        fn = _render_fn()
        self.assertEqual(fn.count("<table"), 1, "面板应只渲染一张表")
        self.assertNotIn("mcp-matrix", _src(), "旧覆盖矩阵表应已移除")

    def test_header_preserves_endpoint_case(self):
        css = _css_block()
        self.assertIn(".mcp-table thead th.mcp-c-ep", css)
        self.assertIn("text-transform: none", css, "端点表头须保留大小写（thead 默认 uppercase）")

    def test_states_are_shape_and_color_encoded(self):
        css = _css_block()
        self.assertIn(".mcp-dot.ok", css)
        self.assertIn("background: var(--ok)", css, "已挂载用实心点")
        for cls in (".mcp-dot.warn", ".mcp-dot.na"):
            self.assertIn(cls, css)
        self.assertGreaterEqual(
            css.count("inset 0 0 0 1.5px"), 2, "缺失/未纳入用空心环，与实心点在形态上区分"
        )

    def test_unsupported_shape_differs_from_missing(self):
        """不支持用横杠、缺失用空心环；两者颜色也不同，形状与色彩都区分得开。"""
        css = _css_block()
        off = re.search(r"\.mcp-dot\.off \{[^}]*\}", css)
        self.assertIsNotNone(off, "缺少不支持态样式")
        self.assertIn("border-top", off.group(0), "不支持用横杠，不是圆点")
        self.assertNotIn("border-radius: 50%", off.group(0))
        warn = re.search(r"\.mcp-dot\.warn \{[^}]*\}", css)
        self.assertIn("var(--warn)", warn.group(0), "缺失必须是警示色")
        self.assertIn(".mcp-st.off", css)
        self.assertIn(".mcp-src.off", css)

    def test_anomaly_row_uses_left_rail(self):
        css = _css_block()
        self.assertIn("tr.is-anomaly td:first-child", css)
        self.assertIn("box-shadow: inset 2px 0 0 var(--warn)", css)

    def test_unsupported_row_is_dimmed_not_flagged(self):
        css = _css_block()
        self.assertIn("tr.is-unsupported .mcp-client-name", css)
        self.assertNotIn("is-unsupported td:first-child", css, "不支持不得用异常警示条")

    def test_source_semantics_explained_once_not_per_row(self):
        src = _src()
        self.assertNotIn("来源：自动（默认全部端点）", _render_fn(), "行内不再重复来源长文案")
        hint = re.search(r'<h2>MCP</h2><div class="hint">(.*?)</div>', src, re.S).group(1)
        self.assertIn("自动", hint)
        self.assertIn("mcp_attach", hint, "页面提示须解释「自动」= 未显式声明 mcp_attach")

    def test_home_and_mcp_panel_share_unsupported_wording(self):
        """首页 MCP 列与 MCP 面板用同一套词汇（此前首页写「无配置」）。"""
        src = _src()
        self.assertNotIn("不支持 MCP 修复", src, "tooltip 文案应说明是能力缺失而非待修复")
        self.assertIn("不支持 MCP / 无端点", src, "首页 MCP 图例须与面板一致")
        self.assertGreaterEqual(src.count("不支持 MCP（非故障）"), 2, "首页两处单元格文案")


@unittest.skipUnless(NODE, "需要 node 才能执行渲染护栏")
class RenderTest(unittest.TestCase):
    """真实执行 renderMcpClients，锁定对齐后的内容与状态标注。"""

    def test_rows_align_after_merge(self):
        rows = _rows(_render(MCP_OK, ENDPOINTS))
        self.assertEqual(rows[0][1], ["客户端", "ep1", "ep2", "MCP 条目（分类）"])
        self.assertEqual(rows[1][1], ["已接入 自动", "已挂载", "已挂载", "无"])
        self.assertEqual(rows[2][1], ["缺配置 未应用 回流", "缺失", "缺失", "无"])

    def test_only_missing_client_is_flagged(self):
        rows = _rows(_render(MCP_OK, ENDPOINTS))
        self.assertNotIn("is-anomaly", rows[1][0], "已接入的客户端不应被标异常")
        self.assertIn("is-anomaly", rows[2][0], "声明要挂却缺失的客户端须标异常")

    def test_unsupported_row_reads_as_not_applicable(self):
        rows = _rows(_render(MCP_UNSUPPORTED, ENDPOINTS))
        self.assertIn("is-unsupported", rows[2][0], "不支持 MCP 的行须有自己的标记")
        self.assertNotIn("is-anomaly", rows[2][0], "不支持不是异常，不得用异常标记")
        self.assertEqual(
            rows[2][1],
            ["ima.copilot 不支持 MCP", "不适用", "不适用", "无"],
        )

    def test_unsupported_counted_separately_from_missing(self):
        mcp = {"clients": MCP_UNSUPPORTED["clients"] + [_client("真缺失", ["ep1"], [], ["ep1"], [])]}
        legend = _legend(_render(mcp, ENDPOINTS))
        self.assertIn("1 个不支持 MCP", legend)
        self.assertIn("1 个存在缺失", legend, "缺失与不支持须分别计数")

    def test_unsupported_only_legend_has_no_anomaly(self):
        legend = _legend(_render(MCP_UNSUPPORTED, ENDPOINTS))
        self.assertIn("1 个不支持 MCP", legend)
        self.assertNotIn("存在缺失", legend, "能力缺失不得计入异常")

    def test_old_snapshot_without_supports_mcp_falls_back(self):
        """旧快照没有 supports_mcp 字段时，按 config_path 是否为空判定。"""
        legacy = [
            {k: v for k, v in _client("旧快照无能力字段", [], [], [], [], supports=False).items()
             if k != "supports_mcp"},
        ]
        html = _render({"clients": legacy}, ENDPOINTS)
        self.assertIn("is-unsupported", html, "config_path 为空应回退判为不支持")

    def test_rendered_output_has_no_pictographs(self):
        for mcp in (MCP_OK, MCP_UNSUPPORTED):
            html = _render(mcp, ENDPOINTS)
            for glyph in ("\u26a0", "\u2713"):  # 警告三角 / 对勾：改用形态点表达
                self.assertNotIn(glyph, html)

    def test_empty_endpoint_library_does_not_crash(self):
        html = _render({"clients": [_client("孤立", [], [], [], [])]}, [])
        rows = _rows(html)
        self.assertEqual(rows[0][1], ["客户端", "MCP 条目（分类）"])
        self.assertEqual(rows[1][1], ["孤立 自动", "无"])

    def test_library_outside_endpoint_still_gets_a_column(self):
        """实况条目引用了端点库之外的端点时，不能把状态静默丢掉。"""
        mcp = {
            "clients": [
                _client(
                    "越界",
                    [],
                    ["ghost"],
                    [],
                    ["ghost"],
                    inventory=[{"key": "g", "classification": "attached", "endpoint_key": "ghost"}],
                )
            ]
        }
        rows = _rows(_render(mcp, []))
        self.assertEqual(rows[0][1], ["客户端", "ghost", "MCP 条目（分类）"])
        self.assertEqual(rows[1][1], ["越界 自动", "已挂载", "无"])

    def test_no_client_renders_empty_state(self):
        html = _render({"clients": []}, [])
        self.assertIn("无客户端", html)
        self.assertNotIn("<table", html)

    def test_explicit_attach_labelled_manual(self):
        mcp = {
            "clients": [
                _client("手动", ["ep1"], ["ep1"], [], [], explicit=True,
                        inventory=[{"key": "s1", "classification": "attached", "endpoint_key": "ep1"}])
            ]
        }
        rows = _rows(_render(mcp, ENDPOINTS))
        self.assertEqual(rows[1][1][0], "手动 手动")
        self.assertEqual(rows[1][1][2], "未纳入", "未声明的端点列须显示「未纳入」")


@unittest.skipUnless(NODE, "需要 node 才能执行渲染护栏")
class DriftRenderTest(unittest.TestCase):
    """被外部工具改写：说清「为什么缺」并就地给出回流入口。"""

    def test_rewritten_client_shows_cause_and_reflow(self):
        rows = _rows(_render({"clients": [_drift_client("Codex", ["ep1", "ep2"])]}, ENDPOINTS))
        client_cell = rows[1][1][0]
        self.assertIn("被外部改写", client_cell, "有备份且端点不见 => 报「被外部改写」")
        self.assertIn("回流", client_cell, "须就地给出回流入口")
        self.assertEqual(rows[1][1][1], "缺失", "端点列仍是缺失（原因与状态分开表达）")

    def test_unapplied_client_not_labelled_as_rewrite(self):
        """无备份（从未写入成功）只说「未应用」，不误报外部改写。"""
        mcp = {"clients": [_client("新客户端", ["ep1"], [], ["ep1"], [])]}
        rows = _rows(_render(mcp, ENDPOINTS))
        cell = rows[1][1][0]
        self.assertIn("未应用", cell)
        self.assertNotIn("被外部改写", cell)

    def test_reflow_button_wired_to_existing_fix_action(self):
        html = _render({"clients": [_drift_client("Codex", ["ep1"])]}, ENDPOINTS)
        self.assertIn('data-action="fix-mcp"', html, "回流须复用已接线的 fix-mcp 动作")
        self.assertIn('data-name="Codex"', html)

    def test_drift_count_in_legend(self):
        mcp = {"clients": [_drift_client("Codex", ["ep1"]), _client("正常", ["ep1"], ["ep1"], [], [])]}
        legend = _legend(_render(mcp, ENDPOINTS))
        self.assertIn("1 个疑似被外部改写", legend)

    def test_no_drift_keeps_plain_source_chip(self):
        """全部已挂载时保持原来的「手动/自动」来源标签，不引入回流入口。"""
        mcp = {"clients": [_client("已接入", ["ep1"], ["ep1"], [], [],
                                   inventory=[{"key": "s1", "classification": "attached",
                                               "endpoint_key": "ep1"}])]}
        html = _render(mcp, ENDPOINTS)
        self.assertIn("自动", html)
        self.assertNotIn("回流", html, "没有丢失时不该出现回流按钮")
        self.assertNotIn("被外部改写", html)

    def test_drift_is_not_reported_for_unsupported_client(self):
        """不支持 MCP 的客户端没有配置文件，谈不上被改写。"""
        rows = _rows(_render(MCP_UNSUPPORTED, ENDPOINTS))
        self.assertNotIn("被外部改写", rows[2][1][0])


@unittest.skipUnless(NODE, "需要 node 才能执行渲染护栏")
class ResidualEntryColumnTest(unittest.TestCase):
    """最后一列只承载端点列表达不了的信息，不再重复「已挂载」。

    端点列已逐列给出挂载状态（「已挂载」单元格本身即可点进明细），最后一列
    若再列一遍「x · 已挂载」就是同一事实的第二种写法。这一列只留旧通道 /
    未纳管 / 带风险标记的条目，顺序固定为 旧通道 -> 未纳管，避免行与行间抖动。
    """

    def _mixed(self):
        return {
            "clients": [
                _client(
                    "混合",
                    ["ep1", "ep2"],
                    ["ep1", "ep2"],
                    [],
                    [],
                    inventory=[
                        {"key": "u1", "classification": "unmanaged", "url": "https://u1/mcp"},
                        {"key": "l1", "classification": "legacy", "command": "npx l1"},
                        {"key": "ep2", "classification": "attached", "endpoint_key": "ep2"},
                        {"key": "ep1", "classification": "attached", "endpoint_key": "ep1"},
                    ],
                )
            ]
        }

    def test_mounted_entries_not_repeated_in_last_column(self):
        cell = _rows(_render(self._mixed(), ENDPOINTS))[1][1][-1]
        self.assertNotIn("已挂载", cell, "端点列已表达的已挂载不得在最后一列重复")
        self.assertIn("l1 · 旧通道", cell)
        self.assertIn("u1 · 未纳管", cell)

    def test_residual_order_is_stable(self):
        cell = _rows(_render(self._mixed(), ENDPOINTS))[1][1][-1]
        self.assertLess(
            cell.index("l1 · 旧通道"), cell.index("u1 · 未纳管"),
            "旧通道（异常）应排在未纳管之前，且不随 inventory 原始顺序抖动",
        )

    def test_risky_mounted_entry_still_listed(self):
        """带风险标记的已挂载条目是端点列表达不了的信息，须保留。"""
        mcp = {"clients": [_client(
            "带风险", ["ep1"], ["ep1"], [], [],
            inventory=[{"key": "ep1", "classification": "attached", "endpoint_key": "ep1",
                        "high_risk": True, "risk_reason": "疑似客户端自带"}],
        )]}
        cell = _rows(_render(mcp, ENDPOINTS))[1][1][-1]
        self.assertIn("ep1 · 已挂载", cell)

    def test_attached_outside_header_is_kept(self):
        """端点列里没有这一列时，条目不能被静默丢掉。"""
        mcp = {"clients": [_client(
            "端点库外", [], [], [], [],
            inventory=[{"key": "x", "classification": "attached", "endpoint_key": "not-in-header"}],
        )]}
        cell = _rows(_render(mcp, []))[1][1][-1]
        self.assertIn("x · 已挂载", cell)

    def test_cover_column_removed_everywhere(self):
        """「挂载」列整体删除：渲染输出与源码都不再出现 mcp-c-cover / mcp-cover-btn。"""
        self.assertNotIn("mcp-c-cover", _render(MCP_OK, ENDPOINTS))
        self.assertNotIn("mcp-cover-btn", _src())
        self.assertNotIn("mcp-c-cover", _src())

    def test_attached_cell_is_clickable_entry(self):
        """端点列的「已挂载」自己就是明细入口，不再需要单独的「挂载」列。"""
        html = _render(MCP_OK, ENDPOINTS)
        # 已接入挂载了 ep1/ep2 => 恰好两个「已挂载」按钮，每个都指向 attached 明细
        self.assertEqual(html.count('data-action="show-mcp-class"'), 2)
        self.assertEqual(html.count('data-class="attached"'), 2)
        self.assertEqual(html.count('data-name="已接入"'), 2)
        btns = re.findall(
            r'<button type="button" class="mcp-st ok mcp-ep-btn"[^>]*>.*?</button>', html, re.S
        )
        self.assertEqual(len(btns), 2, "已接入挂载了 ep1/ep2，应有两个「已挂载」按钮")
        for b in btns:
            self.assertIn('data-action="show-mcp-class"', b)
            self.assertIn('data-class="attached"', b)
            self.assertIn("mcp-dot ok", b, "形态与色彩双重编码，不单靠颜色")


if __name__ == "__main__":
    unittest.main()