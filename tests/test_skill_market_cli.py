"""FEAT-9: `--market` CLI 出口契约。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "scan.py"


def run_market(*args, timeout=240):
    return subprocess.run(
        [sys.executable, str(SCAN), "--market", *args, "--format", "json"],
        capture_output=True, text=True, timeout=timeout, cwd=str(ROOT),
    )


class MarketCliTest(unittest.TestCase):
    def test_sources_returns_json(self):
        proc = run_market("sources")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("sources", data)
        self.assertIn("skills.sh", data["sources"])

    def test_list_returns_installed(self):
        proc = run_market("list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("installed", data)
        self.assertIsInstance(data["installed"], list)
        self.assertTrue(data["installed"])

    def test_search_without_query_is_usage_error(self):
        proc = run_market("search")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("market-query", proc.stdout + proc.stderr)

    def test_unknown_subcommand_is_usage_error(self):
        proc = subprocess.run(
            [sys.executable, str(SCAN), "--market", "bogus"],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_check_is_read_only(self):
        """护栏：--market check 前后统一库文件数与 mtime 快照必须一致。"""
        skills = Path.home() / ".skills-manager" / "skills"

        def snap():
            if not skills.is_dir():
                return {}
            return {p.name: p.stat().st_mtime_ns for p in skills.iterdir()}

        before = snap()
        proc = run_market("check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(before, snap(),
                         "--market check 修改了技能库；它必须是只读的")

    def test_check_reports_summary(self):
        proc = run_market("check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("summary", data)
        for key in ("total", "outdated", "current", "unknown"):
            self.assertIn(key, data["summary"])


class MarketCliHumanOutputTest(unittest.TestCase):
    """无 --format json 时给人看的输出。"""

    def test_sources_human_readable(self):
        proc = subprocess.run(
            [sys.executable, str(SCAN), "--market", "sources"],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("skills.sh", proc.stdout)

    def test_check_human_output_has_counts(self):
        proc = subprocess.run(
            [sys.executable, str(SCAN), "--market", "check"],
            capture_output=True, text=True, timeout=240, cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("有更新", proc.stdout)


class MarketWriteCliTest(unittest.TestCase):
    """写操作 CLI：必须 --yes 门禁，且测试期绝不真的执行。"""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(SCAN), *args],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )

    def test_install_without_yes_is_refused(self):
        proc = self._run("--market-install", "a/b@c")
        self.assertEqual(proc.returncode, 2, "未加 --yes 必须拒绝")
        self.assertIn("--yes", proc.stdout)
        self.assertIn("add a/b@c -g", proc.stdout)

    def test_upgrade_without_yes_is_refused(self):
        proc = self._run("--market-upgrade", "some-skill")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--yes", proc.stdout)

    def test_install_and_upgrade_are_mutually_exclusive(self):
        proc = self._run("--market-install", "a/b", "--market-upgrade", "x", "--yes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("互斥", proc.stdout)

    def test_empty_upgrade_name_is_refused(self):
        proc = self._run("--market-upgrade", "  ", "--yes")
        self.assertEqual(proc.returncode, 2)

    def test_dry_run_path_did_not_touch_skills(self):
        """未加 --yes 的调用绝不能碰到技能库。"""
        skills = Path.home() / ".skills-manager" / "skills"
        before = {p.name: p.stat().st_mtime_ns for p in skills.iterdir()}
        self._run("--market-install", "zzz/no-such-skill@nope")
        after = {p.name: p.stat().st_mtime_ns for p in skills.iterdir()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()