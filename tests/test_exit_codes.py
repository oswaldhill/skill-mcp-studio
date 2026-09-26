"""Exit-code contract (phase 2, ADR-10 / docs §7.2).

``_run_all_profiles`` returns 0 (all compliant), 1 (any non-compliant), or 2
(tool/config error). The CLI console script maps ``main() -> int`` straight to
``sys.exit``.
"""

import contextlib
import io
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scan  # noqa: E402  (imports core modules; no side effects at top level)


def _args(**overrides):
    values = {"profile": None, "config": "config.yaml", "discover": False, "format": "json"}
    values.update(overrides)
    return Namespace(**values)


def _compliant_result():
    return {"probe": {"error": ""}, "records": [], "unmanaged": [], "summary": {}}


def _non_compliant_result():
    return {"probe": {"error": "connect fail"}, "records": [], "unmanaged": [], "summary": {}}


@contextlib.contextmanager
def _captured_output():
    """捕获被测代码打到 stdout / stderr 的内容。

    为什么需要：这些负例分支**本该**向用户打印错误（这是 CLI 的正确行为），但测试
    直接调内部函数，输出会直通终端、混进 unittest 汇总里，让人误判「是不是有失败」
    （评审 P2-15）。捕获后一并断言「确实打印了那条错误」—— 既消音，又把此前从未被
    验证过的输出文案纳入断言，属于顺带变强而非单纯堵嘴。
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


class AllProfilesExitCodeTest(unittest.TestCase):
    def test_all_compliant_returns_0(self):
        with mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "list_profiles", return_value=["p1"]), \
                mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "check_agents", return_value=_compliant_result()), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            self.assertEqual(scan._run_all_profiles(_args(), {}, "config.yaml"), 0)

    def test_non_compliant_returns_1(self):
        with mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "list_profiles", return_value=["p1"]), \
                mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "check_agents", return_value=_non_compliant_result()), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            self.assertEqual(scan._run_all_profiles(_args(), {}, "config.yaml"), 1)

    def test_profile_mutex_returns_2(self):
        with _captured_output() as (out, _err):
            self.assertEqual(
                scan._run_all_profiles(_args(profile="x"), {}, "config.yaml"), 2
            )
        self.assertIn("--all-profiles 与 --profile 互斥", out.getvalue())

    def test_scan_failure_returns_2(self):
        with mock.patch.object(scan, "run_scan", side_effect=OSError("boom")):
            with _captured_output() as (out, _err):
                self.assertEqual(scan._run_all_profiles(_args(), {}, "config.yaml"), 2)
        self.assertIn("扫描失败: boom", out.getvalue())

    def test_single_profile_load_failure_is_config_error_returns_2(self):
        # 阶段二 §7.2（评审 CLI-1 整改）：profile/模板加载失败属「配置错误」，
        # 退出码 2；单 profile 失败不阻断其余 profile 继续执行（§6.3），
        # 但收尾任一配置错误 → 2（区别于端点探测失败 → 1）。
        with mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "list_profiles", return_value=["bad"]), \
                mock.patch.object(scan, "load_profile", side_effect=ValueError("template missing")), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            with _captured_output() as (out, _err):
                self.assertEqual(scan._run_all_profiles(_args(), {}, "config.yaml"), 2)
        # 失败必须指名道姓报出是哪个 profile —— 否则用户无从下手。
        self.assertIn("profile 'bad' 加载失败", out.getvalue())
        self.assertIn("template missing", out.getvalue())


class SingleProfileSnapshotTest(unittest.TestCase):
    def test_single_profile_compliant_returns_0(self):
        with mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "check_agents", return_value=_compliant_result()), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            self.assertEqual(scan._run_single_profile_snapshot(_args(), {}, "config.yaml"), 0)

    def test_single_profile_non_compliant_returns_1(self):
        with mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "check_agents", return_value=_non_compliant_result()), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            self.assertEqual(scan._run_single_profile_snapshot(_args(), {}, "config.yaml"), 1)

    def test_single_profile_load_failure_returns_2(self):
        with mock.patch.object(scan, "load_profile", side_effect=ValueError("missing")):
            with _captured_output() as (out, _err):
                self.assertEqual(scan._run_single_profile_snapshot(_args(), {}, "config.yaml"), 2)
        self.assertIn("profile 加载失败: missing", out.getvalue())

    def test_single_profile_emits_same_contract_as_all_profiles(self):
        # Both export paths produce JSON with one wrapper; here the single-profile
        # path delegates to the same report_all_profiles the aggregate path uses.
        captured = {}
        with mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "check_agents", return_value=_compliant_result()), \
                mock.patch.object(scan, "report_all_profiles", side_effect=lambda results, fmt=None, active_profile="": captured.update({"fmt": fmt, "n": len(results), "active": active_profile}) or "") as m:
            self.assertEqual(scan._run_single_profile_snapshot(_args(), {}, "config.yaml"), 0)
        self.assertEqual(captured.get("n"), 1)
        self.assertEqual(captured.get("active"), "p1")


if __name__ == "__main__":
    unittest.main()
