"""--fix-skills 的 FEAT-7 口径回归（v0.22.x 用户报"总路径还是 7 个，实际只有 6 个 IDE"）。

CC Switch 是 `non_agent: true` 的配置工具：IDE/Agent 页与统计不展示它，
但「修复链接」预览（--fix-skills --dry-run --format json）把它的
~/.cc-switch/skills 也扫了进来，卡片于是显示 7 条路径。该口径漏在两层：
预览的 fix_all 输入、以及主流程 Phase 6 的实写输入。现由共享的
`_drop_non_agent_rows` 同源过滤——本文件盯住这条共享与两侧接线。
"""

import io
import json
import re
import sys
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

import scan  # noqa: E402


CONFIG = str(ROOT / "config.yaml")


def _row(tool, status="correct"):
    return {"tool_name": tool, "status": status, "path": f"~/x/{tool}",
            "expanded_path": f"/tmp/{tool}", "type": "ide"}


class NonAgentConfigTest(unittest.TestCase):
    def test_real_config_declares_ccswitch_non_agent(self):
        # 若有人删了 config.yaml 的 non_agent 声明，本口径过滤会静默失效——先钉住
        self.assertIn("ccswitch", scan._non_agent_names(CONFIG))

    def test_agents_are_not_non_agent(self):
        names = scan._non_agent_names(CONFIG)
        self.assertNotIn("qoder", names)
        self.assertNotIn("codex", names)


class DropRowsTest(unittest.TestCase):
    TOOLS = [{"name": "CC Switch", "non_agent": True}, {"name": "Qoder"}]

    def _patched(self):
        return (mock.patch.object(scan, "load_config", return_value={}),
                mock.patch.object(scan, "effective_tools", return_value=self.TOOLS))

    def test_removes_non_agent_rows_normalized(self):
        # tool_name 书写变体（CC Switch / cc-switch）都必须命中同一别名口径
        rows = [_row("CC Switch"), _row("Qoder"), _row("cc-switch")]
        with mock.patch.object(scan, "_non_agent_names",
                               return_value={"ccswitch"}):
            out = scan._drop_non_agent_rows({"results": rows}, CONFIG)
        self.assertEqual([r["tool_name"] for r in out["results"]], ["Qoder"])

    def test_input_not_mutated(self):
        rows = [_row("CC Switch"), _row("Qoder")]
        original = {"results": rows}
        with mock.patch.object(scan, "_non_agent_names",
                               return_value={"ccswitch"}):
            scan._drop_non_agent_rows(original, CONFIG)
        self.assertEqual(len(original["results"]), 2)

    def test_noop_identity_when_no_non_agent(self):
        data = {"results": [_row("Qoder")]}
        with mock.patch.object(scan, "_non_agent_names", return_value=set()):
            self.assertIs(scan._drop_non_agent_rows(data, CONFIG), data)

    def test_helper_uses_effective_tools(self):
        lc = mock.patch.object(scan, "load_config", return_value={})
        et = mock.patch.object(scan, "effective_tools", return_value=self.TOOLS)
        with lc, et:
            names = scan._non_agent_names(CONFIG)
        self.assertEqual(names, {"ccswitch"})


class PreviewPipelineTest(unittest.TestCase):
    """预览：non_agent 必须在 fix_all 之前就被剔除（计划与表格同源）。"""

    TOOLS = [{"name": "Qoder"}, {"name": "CC Switch", "non_agent": True},
             {"name": "GhostIDE"}]

    def _run(self):
        scan_rows = [_row("Qoder"), _row("CC Switch"), _row("GhostIDE")]
        captured = {}

        def fake_fix_all(result, dry_run, client):
            captured["rows"] = [r["tool_name"] for r in result["results"]]
            return {"fixed": 0, "errors": 0, "details": []}

        args = Namespace(discover=False, client=None)
        with mock.patch.object(scan, "load_config", return_value={}), \
             mock.patch.object(scan, "effective_tools", return_value=self.TOOLS), \
             mock.patch.object(scan, "detect_installation",
                               side_effect=lambda t: {"install_state":
                                                      "none" if t["name"] == "GhostIDE"
                                                      else "installed"}), \
             mock.patch.object(scan, "run_scan",
                               return_value={"results": scan_rows, "summary": {}}), \
             mock.patch.object(scan, "fix_all", side_effect=fake_fix_all), \
             mock.patch.object(scan, "compute_changes", return_value={}), \
             redirect_stdout(io.StringIO()) as buf:
            rc = scan._run_fix_skills_preview(args, {}, CONFIG)
        payload = json.loads(buf.getvalue())
        return rc, captured, payload

    def test_rc_zero(self):
        rc, _, _ = self._run()
        self.assertEqual(rc, 0)

    def test_fix_plan_excludes_non_agent_and_ghost(self):
        _, captured, _ = self._run()
        self.assertEqual(captured["rows"], ["Qoder"],
                         "fix_all 收到非面板口径的行：预览计划与表格不同源")

    def test_payload_rows(self):
        _, _, payload = self._run()
        names = [r["tool_name"] for r in payload["scan"]["results"]]
        self.assertEqual(names, ["Qoder"])


class Phase6WiringTest(unittest.TestCase):
    def test_main_flow_filters_before_fix_all(self):
        src = (ROOT / "scan.py").read_text(encoding="utf-8")
        m = re.search(r"if args\.fix:\n(.*?)fix_result = fix_all\(", src, re.S)
        self.assertTrue(m, "未找到 Phase 6 的 fix_all 调用")
        self.assertIn("_drop_non_agent_rows(scan_result, config_path)", m.group(1),
                      "实写没有按 FEAT-7 口径过滤（预览 6 项、实写 7 项会再演）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
