"""「MCP 探活正常」总览卡的三态判定护栏。

缺陷现场：总览卡显示 ``0/2 MCP 探活正常``（红框告警），而端点实际可用。
两个独立成因，本护栏分别锁定：

1. **未探活被算作失败**：快照里 ``probe`` 缺失或 ``error == "not probed"`` 时
   前端把它当成一次失败探活，分母又用端点总数，于是 ``0/2``。
   正确语义是「未探活」——既不是通过也不是故障。
2. **单次抖动即判故障**：后端原无重试，一次 socket 超时即写死失败
   （后端重试另见 ``tests/test_probe_retry.py``）。

口径必须与 MCP 面板一致：面板此前恒为绿色 ``tag ok``，即便探活未通过也说
「已设置」，与总览互相矛盾。
"""

import json
import re
import shutil
import subprocess
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


@unittest.skipUnless(NODE, "需要 node 才能执行渲染护栏")
class ProbeVerdictTest(unittest.TestCase):
    """``probeVerdict`` / ``probeVerdictFromRecord`` 的三态语义。"""

    @classmethod
    def setUpClass(cls):
        cls.js = "\n".join([_fn("probeVerdict"), _fn("probeVerdictFromRecord")])

    def _eval(self, cases):
        js = self.js + "\nconst cases = " + json.dumps(cases) + ";\n" + (
            "console.log(JSON.stringify(cases.map((c) => "
            "c.rec === undefined ? probeVerdict(c.probe) : probeVerdictFromRecord(c.rec))));"
        )
        out = subprocess.run([NODE, "-e", js], capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_pass_is_ok(self):
        self.assertEqual(self._eval([{"probe": {"initialize_ok": True, "tools_list_ok": True, "error": ""}}]), ["ok"])

    def test_timeout_is_fail_not_ok(self):
        self.assertEqual(
            self._eval([{"probe": {"initialize_ok": False, "tools_list_ok": False, "error": "<urlopen error timed out>"}}]),
            ["fail"],
        )

    def test_partial_success_is_fail(self):
        self.assertEqual(self._eval([{"probe": {"initialize_ok": True, "tools_list_ok": False, "error": ""}}]), ["fail"])

    def test_error_on_success_is_fail(self):
        self.assertEqual(
            self._eval([{"probe": {"initialize_ok": True, "tools_list_ok": True, "error": "boom"}}]),
            ["fail"],
        )

    def test_not_probed_is_unknown_not_fail(self):
        """核心回归：未探活不等于故障，否则总览会误报 0/N。"""
        self.assertEqual(
            self._eval([{"probe": {"initialize_ok": False, "tools_list_ok": False, "tool_names": [], "error": "not probed"}}]),
            ["unknown"],
        )

    def test_missing_probe_is_unknown(self):
        self.assertEqual(
            self._eval([{"probe": None}, {"probe": {}}]),
            ["unknown", "unknown"],
        )

    def test_record_verdict_mirrors_probe_verdict(self):
        self.assertEqual(
            self._eval([
                {"rec": {"mcp_initialize_ok": True, "mcp_tools_list_ok": True}},
                {"rec": {"mcp_initialize_ok": True, "mcp_tools_list_ok": False}},
                {"rec": None},
            ]),
            ["ok", "fail", "unknown"],
        )


class EndpointStatusWiringTest(unittest.TestCase):
    """「端点状态」独立区的三态呈现与手动触发入口。

    v0.24.0 复审后的迁移说明
    ------------------------
    原先这一组护栏锁的是**总览区那张「MCP 探活正常 x/y」卡片**（分母、
    未探活文案、失败提示）。用户明确要求「审计只判配置、端口通断单独看」后，
    那张卡片已从总览区**整体移除**，探活结果改由独立的「端点状态」区呈现。

    因此这里**不是删除护栏，而是把它们搬到新落点**：三条断言的核心意图
    逐条保留 ——

    1. 未探活不得被当成故障（原：分母不得用端点总数），
    2. 未探活必须是中性色、不能用警告色（原：``probeCls = ""``），
    3. 失败必须指名端点与原因（原：``探活失败：`` + ``${v.key || v.url}``）。
    """

    def setUp(self):
        self.src = _src()

    def test_overview_no_longer_shows_probe_stats(self):
        """审计总览区不得再出现探活统计卡片 —— 这是本次改造的核心产物。"""
        self.assertNotIn(
            "card(probeNum, probeLbl, probeCls, false, probeTip)",
            self.src,
            "总览区不得再渲染探活卡片：审计只判配置",
        )

    def test_not_run_is_neutral_not_warning(self):
        """迁移自 ``test_unprobed_endpoints_render_neutral_not_warn``。

        未检查既不是通过也不是故障；用警告色会让人以为端点有问题。
        新落点：``renderEndpointStatus`` 的三态 class 组装。
        """
        self.assertIn(
            'const cls = state === "ok" ? "ok" : state === "failed" ? "err" : "";',
            self.src,
            "未检查必须落到中性色（空 class），不能是 warn/err",
        )

    def test_failure_shows_endpoint_and_reason(self):
        """迁移自 ``test_failure_tip_names_endpoint_and_reason``。

        失败时必须能看到是哪个端点、为什么不通 —— 只报「失败」用户无从下手。
        """
        self.assertIn('rows.push(["错误", st.error]);', self.src)
        self.assertIn('["地址", ep.url || ""]', self.src)
        self.assertIn('["状态", label]', self.src)

    def test_endpoint_status_section_exists(self):
        """独立区域与容器必须真的存在，否则渲染函数会静默 return。"""
        self.assertIn('id="endpoint-status"', self.src)
        self.assertIn("function renderEndpointStatus()", self.src)
        self.assertIn("renderEndpointStatus();", self.src)

    def test_check_button_uses_independent_cli_exit(self):
        """按钮必须走独立出口 ``--endpoint-status``，不得再借道 --management。

        否则（--management 已关掉 live_probe）点了按钮只是刷新配置，
        用户却以为端点被检查过。
        """
        self.assertIn('data-action="endpoint-check"', self.src)
        self.assertIn('runCli(["--endpoint-status", "--format", "json"])', self.src)
        self.assertIn('else if (a === "endpoint-check") reprobeEndpoints(act);', self.src)

    def test_independent_exit_contract_is_documented(self):
        """源代码里必须写清「退出码 1 = 探活了但不通 → 是有效结论」。"""
        self.assertIn("ENDPOINT_STATUS = JSON.parse(res.stdout);", self.src)
        self.assertIn("退出码 1 = 探活了但端点不通", self.src)


class McpPanelVerdictSourceTest(unittest.TestCase):
    """MCP 面板继续复用同一套三态判据（不受本次搬迁影响）。"""

    def setUp(self):
        self.src = _src()

    def test_mcp_panel_uses_same_verdict_source(self):
        self.assertIn("const probeStates = (SNAP && SNAP.mcp && SNAP.mcp.endpoint_status) || {};", self.src)
        self.assertIn("const verdict = probe ? probeVerdict(probe) : probeVerdictFromRecord(rec);", self.src)

    def test_mcp_panel_no_longer_hardcodes_green_ok_tag(self):
        self.assertNotIn(
            'const probeOk = rec.mcp_initialize_ok && rec.mcp_tools_list_ok;',
            self.src,
            "面板不得再自行判定探活",
        )


if __name__ == "__main__":
    unittest.main()
