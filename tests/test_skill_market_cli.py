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


if __name__ == "__main__":
    unittest.main()