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
            explicit=False, inventory=None, supports=True):
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
    }


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
        self.assertEqual(rows[0][1], ["客户端", "ep1", "ep2", "挂载", "MCP 条目（分类）"])
        self.assertEqual(rows[1][1], ["已接入 自动", "已挂载", "已挂载", "2 / 2", "s1 · 已挂载"])
        self.assertEqual(rows[2][1], ["缺配置 自动", "缺失", "缺失", "0 / 2", "无"])

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
            ["ima.copilot 不支持 MCP", "不适用", "不适用", "不支持", "无"],
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
        self.assertEqual(rows[0][1], ["客户端", "挂载", "MCP 条目（分类）"])
        self.assertEqual(rows[1][1], ["孤立 自动", "无端点", "无"])

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
        self.assertEqual(rows[0][1], ["客户端", "ghost", "挂载", "MCP 条目（分类）"])
        self.assertEqual(rows[1][1], ["越界 自动", "已挂载", "1", "g · 已挂载"])

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


if __name__ == "__main__":
    unittest.main()