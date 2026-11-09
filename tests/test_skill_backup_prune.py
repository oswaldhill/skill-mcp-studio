"""升级备份的维护（去重 / 上限 / 清理）门禁断言。

背景（2026-11-09 用户实测）：每次升级都无条件备份一份技能目录，实测
``find-skills`` 攒了 **327 份**，其中 **326 份字节完全一致**——纯占盘。
用户要求「备份前比对内容、每技能保留上限、给一个清理入口」。

这批断言守 6 类事实：

1. 内容指纹只看路径与字节，与 mtime 无关；
2. 内容与最近一份备份相同 → ``skipped``，不新增目录；
3. 内容不同 → 正常新增一份；
4. 超过 ``keep`` 上限 → 备份后自动淘汰最旧的；
5. ``prune_skill_backups`` 同时做「内容去重」与「上限」，``dry-run`` 不删；
6. CLI 端到端（``--skill-backup-stats`` / ``--prune-skill-backups``）与 GUI 契约
   （按钮、命令、Rust 白名单、DESIGN.md 登记）。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import skill_market_ops as ops  # noqa: E402


def _make_skill(root: Path, name: str, content: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


class _Fixture:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        self.backups = self.root / "backups"
        self.backups.mkdir()

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def patch(self):
        return mock.patch("skill_market_ops._backup_root",
                          return_value=self.backups)


class TreeHashTest(unittest.TestCase):
    def setUp(self):
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_same_content_same_hash(self):
        a = _make_skill(self.fx.skills, "a", "# same\n")
        b = _make_skill(self.fx.skills, "b", "# same\n")
        self.assertEqual(ops._tree_hash(a), ops._tree_hash(b))

    def test_different_content_different_hash(self):
        a = _make_skill(self.fx.skills, "a", "# one\n")
        b = _make_skill(self.fx.skills, "b", "# two\n")
        self.assertNotEqual(ops._tree_hash(a), ops._tree_hash(b))

    def test_hash_ignores_mtime(self):
        a = _make_skill(self.fx.skills, "a", "# x\n")
        h1 = ops._tree_hash(a)
        os.utime(a / "SKILL.md", (1, 1))
        self.assertEqual(ops._tree_hash(a), h1, "指纹必须与 mtime 无关")


class BackupSkillTest(unittest.TestCase):
    def setUp(self):
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_first_backup_ok(self):
        _make_skill(self.fx.skills, "s", "# v1\n")
        with self.fx.patch():
            res = ops.backup_skill("s", self.fx.skills)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(Path(res["path"]).is_dir())

    def test_identical_content_is_skipped(self):
        """内容没变就不再复制——这是 find-skills 攒 326 份重复的根因。"""
        _make_skill(self.fx.skills, "s", "# v1\n")
        with self.fx.patch():
            first = ops.backup_skill("s", self.fx.skills)
            second = ops.backup_skill("s", self.fx.skills)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["path"], first["path"],
                         "skipped 时返回已有那份的路径，仍可作为回滚点")
        self.assertEqual(len(list((self.fx.backups / "s").iterdir())), 1,
                         "不得多出第二份目录")

    def test_changed_content_creates_new_snapshot(self):
        skill = _make_skill(self.fx.skills, "s", "# v1\n")
        with self.fx.patch():
            ops.backup_skill("s", self.fx.skills)
            (skill / "SKILL.md").write_text("# v2\n", encoding="utf-8")
            res = ops.backup_skill("s", self.fx.skills)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(list((self.fx.backups / "s").iterdir())), 2)

    def test_keep_limit_evicts_oldest(self):
        skill = _make_skill(self.fx.skills, "s", "# v0\n")
        with self.fx.patch():
            for i in range(5):
                (skill / "SKILL.md").write_text(f"# v{i}\n", encoding="utf-8")
                ops.backup_skill("s", self.fx.skills, keep=3)
            dirs = sorted((self.fx.backups / "s").iterdir())
        self.assertEqual(len(dirs), 3, "超过 keep 的旧备份应被淘汰")
        # 保留的应是最近三次（v2/v3/v4）
        contents = sorted((d / "SKILL.md").read_text(encoding="utf-8") for d in dirs)
        self.assertEqual(contents, ["# v2\n", "# v3\n", "# v4\n"])

    def test_missing_skill_is_failed(self):
        with self.fx.patch():
            res = ops.backup_skill("nope", self.fx.skills)
        self.assertEqual(res["status"], "failed")


class PruneSkillBackupsTest(unittest.TestCase):
    def setUp(self):
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def _snap(self, skill: str, stamp: str, content: str) -> Path:
        d = self.fx.backups / skill / stamp
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(content, encoding="utf-8")
        return d

    def test_deduplicates_same_content_keeps_newest(self):
        self._snap("s", "20260101-000000", "# same\n")
        self._snap("s", "20260102-000000", "# same\n")
        newest = self._snap("s", "20260103-000000", "# same\n")
        with self.fx.patch():
            res = ops.prune_skill_backups()
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["removed"], 2)
        remaining = list((self.fx.backups / "s").iterdir())
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0], newest, "同内容保留时间戳最新的一份")

    def test_enforces_keep_limit(self):
        for i in range(6):
            self._snap("s", f"2026010{i+1}-000000", f"# v{i}\n")
        with self.fx.patch():
            res = ops.prune_skill_backups(keep=2)
        self.assertEqual(res["removed"], 4)
        self.assertEqual(len(list((self.fx.backups / "s").iterdir())), 2)

    def test_dry_run_deletes_nothing(self):
        self._snap("s", "20260101-000000", "# same\n")
        self._snap("s", "20260102-000000", "# same\n")
        with self.fx.patch():
            res = ops.prune_skill_backups(dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertEqual(res["removed"], 1)
        self.assertEqual(len(list((self.fx.backups / "s").iterdir())), 2,
                         "dry-run 不得删任何目录")

    def test_nothing_to_prune_when_clean(self):
        self._snap("s", "20260101-000000", "# one\n")
        self._snap("s", "20260102-000000", "# two\n")
        with self.fx.patch():
            res = ops.prune_skill_backups()
        self.assertEqual(res["status"], "nothing-to-prune")
        self.assertEqual(res["removed"], 0)

    def test_stats_reports_duplicates(self):
        self._snap("s", "20260101-000000", "# same\n")
        self._snap("s", "20260102-000000", "# same\n")
        self._snap("t", "20260101-000000", "# other\n")
        with self.fx.patch():
            st = ops.backup_stats()
        self.assertEqual(st["skills"], 2)
        self.assertEqual(st["snapshots"], 3)
        self.assertEqual(st["duplicates"], 1)
        self.assertGreater(st["bytes"], 0)


class BackupCliTest(unittest.TestCase):
    """端到端：GUI 直接 JSON.parse 这两条命令的 stdout。"""

    def test_stats_and_prune_json(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), "--skill-backup-stats", "--format", "json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        for key in ("skills", "snapshots", "duplicates", "bytes", "keep"):
            self.assertIn(key, stats)

        dry = subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), "--prune-skill-backups", "--dry-run",
             "--format", "json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(dry.returncode, 0, dry.stderr)
        payload = json.loads(dry.stdout)
        self.assertIn(payload["status"], ("dry-run", "nothing-to-prune"))


class BackupGuiContract(unittest.TestCase):
    """界面可达性：按钮、命令、Rust 白名单、规范文档必须同时在。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")
        cls.lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        cls.design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")

    def test_card_and_button_exist(self):
        self.assertIn('id="skill-backups-card"', self.dashboard, "缺技能备份卡片")
        self.assertIn('data-action="prune-skill-backups"', self.dashboard,
                      "缺「清理备份」按钮")

    def test_handlers_are_wired(self):
        self.assertIn("function loadSkillBackupStats", self.dashboard)
        self.assertIn("function openPruneSkillBackupsModal", self.dashboard)
        self.assertIn('"--skill-backup-stats"', self.dashboard,
                      "统计必须经 CLI 读取")
        self.assertIn('"--prune-skill-backups", "--dry-run"', self.dashboard,
                      "清理必须先 dry-run 再确认")

    def test_rust_whitelist(self):
        for flag in ("--skill-backup-stats", "--prune-skill-backups"):
            self.assertIn(f'"{flag}"', self.lib_rs,
                          f"Rust run_cli 白名单缺少 {flag}")

    def test_design_spec_registers_card(self):
        self.assertIn("技能备份", self.design,
                      "docs/DESIGN.md 未登记「技能备份」卡片")


if __name__ == "__main__":
    unittest.main()
