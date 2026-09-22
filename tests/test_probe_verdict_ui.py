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


class OverviewWiringTest(unittest.TestCase):
    """总览卡的分母、未探活文案与刷新入口。"""

    def setUp(self):
        self.src = _src()

    def test_denominator_counts_only_probed_endpoints(self):
        self.assertIn("const probed = verdicts.filter((v) => v.verdict !== \"unknown\");", self.src)
        self.assertIn("card(probeNum, probeLbl, probeCls, false, probeTip)", self.src)
        self.assertNotIn("probeOk}/${endpoints.length}`", self.src, "分母不得再用端点总数")

    def test_unprobed_endpoints_render_neutral_not_warn(self):
        self.assertIn('probeLbl = "MCP 未探活";', self.src)
        self.assertIn('probeCls = "";', self.src)

    def test_failure_tip_names_endpoint_and_reason(self):
        self.assertIn("探活失败：", self.src)
        self.assertIn("${v.key || v.url}", self.src)

    def test_open_probe_stats_are_clickable_and_wired(self):
        self.assertIn('data-action="reprobe"', self.src)
        self.assertIn("async function reprobeEndpoints(", self.src)
        self.assertIn('else if (a === "reprobe") reprobeEndpoints(act);', self.src)

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
