"""FEAT-9: 市场写操作（安装/升级）。全部 mock，绝不真的调用 npx。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_market_ops import (  # noqa: E402
    execute_plan,
    plan_install,
    plan_upgrade,
    verify_installed,
)


class PlanTest(unittest.TestCase):
    def test_plan_install_shape(self):
        plan = plan_install("vercel-labs/agent-skills@x")
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["action"], "install")
        self.assertEqual(plan["package"], "vercel-labs/agent-skills@x")
        self.assertEqual(plan["argv"][:2], ["add", "vercel-labs/agent-skills@x"])
        self.assertIn("-g", plan["argv"])
        self.assertIn("-y", plan["argv"])

    def test_plan_install_rejects_empty(self):
        plan = plan_install("   ")
        self.assertFalse(plan["ok"])
        self.assertTrue(plan["reason"])

    def test_plan_upgrade_shape(self):
        plan = plan_upgrade(["a", "b"])
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["action"], "upgrade")
        self.assertEqual(plan["names"], ["a", "b"])
        self.assertEqual(plan["argv"][0], "update")

    def test_plan_upgrade_empty_is_rejected(self):
        plan = plan_upgrade([])
        self.assertFalse(plan["ok"])
        self.assertTrue(plan["reason"])

    def test_plan_upgrade_strips_and_drops_blanks(self):
        plan = plan_upgrade([" a ", "", "  ", "b"])
        self.assertEqual(plan["names"], ["a", "b"])

    def test_plans_never_use_check(self):
        """护栏：写操作也绝不使用 check —— 它实为升级，语义混乱且不受选择控制。"""
        for plan in (plan_install("a/b"), plan_upgrade(["a"])):
            self.assertNotIn("check", plan["argv"])

    def test_install_plan_pins_global_flag(self):
        """安装必须 -g：只有全局安装才落在统一库（~/.agents/skills 是符号链接）。"""
        self.assertIn("-g", plan_install("a/b@c")["argv"])


class VerifyTest(unittest.TestCase):
    def test_reports_present_and_missing(self):
        with mock.patch("skill_market_ops._skills_dir") as sd:
            sd.return_value = Path("/nonexistent-dir-for-test-xyz")
            out = verify_installed(["a", "b"])
        self.assertFalse(out["ok"])
        self.assertEqual(sorted(out["missing"]), ["a", "b"])
        self.assertEqual(out["present"], [])

    def test_detects_present_skill(self):
        with mock.patch("skill_market_ops._skills_dir") as sd:
            sd.return_value = ROOT  # core/ 存在，用 tests 目录名当技能名
            out = verify_installed(["tests"])
        self.assertEqual(out["present"], ["tests"])
        self.assertTrue(out["ok"])


class ExecTest(unittest.TestCase):
    def test_execute_uses_injected_runner(self):
        """执行器必须可注入 runner，测试期永不真跑 npx。"""
        calls = []

        def fake_runner(argv, timeout=None):
            calls.append(argv)
            return {"code": 0, "stdout": "ok", "stderr": ""}

        with mock.patch("skill_market_ops.verify_installed",
                        return_value={"ok": True, "present": ["x"], "missing": []}):
            res = execute_plan(plan_install("a/b@x"), runner=fake_runner)
        self.assertTrue(res["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "add")

    def test_execute_reports_failure_without_raising(self):
        def bad_runner(argv, timeout=None):
            return {"code": 1, "stdout": "", "stderr": "clone failed"}

        res = execute_plan(plan_install("a/b@x"), runner=bad_runner)
        self.assertFalse(res["ok"])
        self.assertIn("clone failed", res["stderr"])

    def test_execute_rejects_bad_plan_without_running(self):
        called = []

        def runner(argv, timeout=None):
            called.append(argv)
            return {"code": 0, "stdout": "", "stderr": ""}

        res = execute_plan(plan_install(""), runner=runner)
        self.assertFalse(res["ok"])
        self.assertEqual(called, [])

    def test_command_success_but_missing_on_disk_is_failure(self):
        """命令退出码 0 不等于装上了：必须装后校验统一库。"""
        def fake_runner(argv, timeout=None):
            return {"code": 0, "stdout": "done", "stderr": ""}

        with mock.patch("skill_market_ops.verify_installed",
                        return_value={"ok": False, "present": [], "missing": ["x"]}):
            res = execute_plan(plan_install("a/b@x"), runner=fake_runner)
        self.assertFalse(res["ok"])
        self.assertIn("未找到安装结果", res["stderr"])

    def test_execute_never_raises_on_runner_exception(self):
        def boom(argv, timeout=None):
            raise OSError("npx exploded")

        res = execute_plan(plan_install("a/b@x"), runner=boom)
        self.assertFalse(res["ok"])
        self.assertIn("npx exploded", res["stderr"])


if __name__ == "__main__":
    unittest.main()