"""FEAT-9: `--market` CLI 出口契约。"""

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "scan.py"


@contextlib.contextmanager
def isolated_home():
    """临时 HOME，内含一个 fixture 技能库。

    ``core/skill_market.py`` 的 ``_SKILLS_DIR`` 在 import 时由 ``Path.home()`` 求值，
    所以给子进程换一个 HOME 就能把技能库整体重定向到临时目录。测试因此不再依赖
    开发机本机的 ``~/.skills-manager/skills``：CI runner 上没有该目录，旧写法在那
    里必然失败（``list`` 只拿到空列表、``iterdir`` 抛 FileNotFoundError）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        fixture = home / ".skills-manager" / "skills" / "demo-skill"
        fixture.mkdir(parents=True)
        (fixture / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: isolated fixture\n---\n",
            encoding="utf-8",
        )
        yield home


def home_env(home):
    """POSIX 读 HOME，Windows 读 USERPROFILE；``Path.home()`` 两者都认。"""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def run_market(*args, timeout=240, home=None):
    return subprocess.run(
        [sys.executable, str(SCAN), "--market", *args, "--format", "json"],
        capture_output=True, text=True, timeout=timeout, cwd=str(ROOT),
        env=home_env(home) if home is not None else None,
    )


class MarketCliTest(unittest.TestCase):
    def test_sources_returns_json(self):
        proc = run_market("sources")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("sources", data)
        self.assertIn("skills.sh", data["sources"])

    def test_list_returns_installed(self):
        """隔离技能库里的 fixture 必须被 list 列出。

        旧写法直接读本机 ``~/.skills-manager/skills`` 并要求它非空，这在 CI runner
        上必然失败；改为自造 fixture 后，本机与 CI 的断言对象一致。
        """
        with isolated_home() as home:
            proc = run_market("list", home=home)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertIn("installed", data)
            self.assertIsInstance(data["installed"], list)
            self.assertEqual([s["name"] for s in data["installed"]], ["demo-skill"])

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

    def _run(self, *args, home=None):
        return subprocess.run(
            [sys.executable, str(SCAN), *args],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            env=home_env(home) if home is not None else None,
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
        """未加 --yes 的调用绝不能碰到技能库。

        在隔离 HOME 里先放一个技能，护栏才有非空基线可比对；旧写法对本机技能库直接
        iterdir()，CI runner 上没有该目录会抛 FileNotFoundError。
        """
        with isolated_home() as home:
            skills = home / ".skills-manager" / "skills"
            before = {p.name: p.stat().st_mtime_ns for p in skills.iterdir()}
            self._run("--market-install", "zzz/no-such-skill@nope", home=home)
            after = {p.name: p.stat().st_mtime_ns for p in skills.iterdir()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
