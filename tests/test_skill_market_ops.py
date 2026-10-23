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


class SkillBackupRollbackTest(unittest.TestCase):
    """升级前备份 + 回滚（2026-10-23 评审修复）。

    背景：升级弹框一直对用户承诺「本地内容会被上游覆盖，升级前自动备份」，
    但 execute_plan 只跑 npx + 安装后校验，**从未备份**——上游把内容改坏
    或迁移后重装成完全不同内容时，用户将永久失去原版。
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        self.backups = self.root / "backups"
        # 造一个技能
        self.skill = self.skills / "demo-skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text("version: 1.0.0\n", encoding="utf-8")
        (self.skill / "extra.txt").write_text("payload", encoding="utf-8")

        import skill_market_ops
        self.ops = skill_market_ops
        self._patch = mock.patch.object(skill_market_ops, "_backup_root",
                                        return_value=self.backups)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_backup_copies_whole_directory(self):
        path = self.ops.backup_skill("demo-skill", skills_dir=self.skills)
        self.assertIsNotNone(path)
        from pathlib import Path
        copied = Path(path)
        self.assertTrue((copied / "SKILL.md").is_file())
        self.assertTrue((copied / "extra.txt").is_file())

    def test_backup_missing_skill_returns_none(self):
        """技能不存在时不得返回路径——None 就是「没备份成」的诚实信号。"""
        self.assertIsNone(self.ops.backup_skill("nope", skills_dir=self.skills))

    def test_list_backups_newest_first(self):
        p1 = self.ops.backup_skill("demo-skill", skills_dir=self.skills)
        p2 = self.ops.backup_skill("demo-skill", skills_dir=self.skills)
        self.assertNotEqual(p1, p2, "两次备份必须是不同时间戳目录")
        items = self.ops.list_skill_backups("demo-skill")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["path"], p2, "列表应新到旧")

    def test_restore_recovers_content(self):
        path = self.ops.backup_skill("demo-skill", skills_dir=self.skills)
        # 模拟升级把内容改坏
        (self.skill / "SKILL.md").write_text("version: 9.9.9\n", encoding="utf-8")
        (self.skill / "extra.txt").unlink()
        res = self.ops.restore_skill_backup("demo-skill", path, skills_dir=self.skills)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual((self.skill / "SKILL.md").read_text(encoding="utf-8"),
                         "version: 1.0.0\n")
        self.assertTrue((self.skill / "extra.txt").is_file(), "回滚要恢复整个目录")

    def test_restore_stashes_current_before_overwrite(self):
        """回滚必须可撤销：覆盖前把当前版本另存。"""
        path = self.ops.backup_skill("demo-skill", skills_dir=self.skills)
        (self.skill / "SKILL.md").write_text("version: 9.9.9\n", encoding="utf-8")
        res = self.ops.restore_skill_backup("demo-skill", path, skills_dir=self.skills)
        self.assertTrue(res["ok"])
        saved = res.get("previous_saved_at")
        self.assertTrue(saved, "应回报另存位置")
        from pathlib import Path
        self.assertTrue(Path(saved).is_dir())
        self.assertIn("9.9.9", (Path(saved) / "SKILL.md").read_text(encoding="utf-8"))

    def test_restore_rejects_path_outside_backup_root(self):
        """防误传：备份必须在受管备份目录内。"""
        outside = self.root / "someone-else"
        outside.mkdir()
        res = self.ops.restore_skill_backup("demo-skill", str(outside),
                                           skills_dir=self.skills)
        self.assertFalse(res["ok"])
        self.assertIn("受管备份目录", res["reason"])

    def test_restore_missing_backup_fails(self):
        res = self.ops.restore_skill_backup("demo-skill", str(self.backups / "gone"),
                                           skills_dir=self.skills)
        self.assertFalse(res["ok"])

    def test_upgrade_plan_executes_backup(self):
        """升级路径必须真的触发备份（此前完全缺失）。"""
        created = []

        def fake_backup(name, skills_dir=None):
            created.append(name)
            return f"/tmp/fake/{name}"

        def runner(argv, timeout):
            return {"code": 0, "stdout": "ok"}

        plan = {"ok": True, "action": "upgrade", "names": ["a", "b"],
                "package": "x/y@a", "argv": ["update", "a", "b"]}
        with mock.patch.object(self.ops, "backup_skill", side_effect=fake_backup), \
             mock.patch.object(self.ops, "verify_installed",
                               return_value={"ok": True, "present": ["a", "b"],
                                             "missing": [], "root": "/tmp"}):
            res = self.ops.execute_plan(plan, runner=runner)
        self.assertEqual(created, ["a", "b"], "每个待升级技能都要备份")
        self.assertIn("a", res["backups"])
        self.assertIn("b", res["backups"])

    def test_install_plan_does_not_backup(self):
        """安装是新装、无旧内容可留，不应产生备份。"""
        plan = {"ok": True, "action": "install", "names": ["new"],
                "package": "x/y@new", "argv": ["add", "x/y", "-g", "-y"]}
        with mock.patch.object(self.ops, "backup_skill") as bk, \
             mock.patch.object(self.ops, "verify_installed",
                               return_value={"ok": True, "present": ["new"],
                                             "missing": [], "root": "/tmp"}):
            res = self.ops.execute_plan(
                plan, runner=lambda argv, timeout: {"code": 0, "stdout": "ok"})
        bk.assert_not_called()
        self.assertEqual(res["backups"], {})
