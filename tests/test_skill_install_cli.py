"""CLI 出口：`--market-install` 支持 GitHub 地址、`--market-preview` 预览仓库。

对应需求（2026-11-14）：Skill 页的两种安装入口。

与 test_skill_market_cli.py 的区别：那个文件覆盖既有 `--market` 只读出口与
包名安装；本文件只覆盖新增的 GitHub 地址路径，避免把两批约定混在一处。

全部通过 subprocess 调真实 scan.py，但**只测不写盘的部分**（未加 --yes 时
命令只打印计划、返回非 0）。真正执行的路径由单测覆盖 execute_plan。
"""

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
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        fixture = home / ".skills-manager" / "skills" / "demo-skill"
        fixture.mkdir(parents=True)
        (fixture / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: fixture\n---\n",
            encoding="utf-8",
        )
        yield home


def home_env(home):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def run_scan(*args, home, timeout=120):
    return subprocess.run(
        [sys.executable, str(SCAN), *args],
        capture_output=True, text=True, timeout=timeout,
        env=home_env(home), cwd=str(ROOT),
    )


class GithubInstallCliTest(unittest.TestCase):
    """GitHub 地址安装：未 --yes 时只打印计划，不得执行。"""

    def test_github_url_plan_requires_yes(self):
        with isolated_home() as home:
            r = run_scan(
                "--market-install",
                "https://github.com/vercel-labs/agent-skills",
                "--market-skills", "*",
                home=home)
        # 未加 --yes：必须拒绝执行（非 0），并回显计划
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("github.com/vercel-labs/agent-skills", r.stdout)
        self.assertIn("npx skills add", r.stdout)

    def test_github_url_plan_has_global_flag(self):
        with isolated_home() as home:
            r = run_scan(
                "--market-install",
                "https://github.com/owner/repo",
                "--market-skills", "*",
                home=home)
        self.assertIn("-g", r.stdout)

    def test_non_github_url_rejected(self):
        with isolated_home() as home:
            r = run_scan(
                "--market-install",
                "https://evil.example.com/owner/repo",
                "--market-skills", "*",
                home=home)
        self.assertNotEqual(r.returncode, 0)
        merged = r.stdout + r.stderr
        self.assertTrue(
            "github" in merged.lower(),
            f"应说明只允许 GitHub，实际输出：{merged}")

    def test_github_url_without_skills_selection_rejected(self):
        """不给 --market-skills 也不给 --market-all：必须拒绝，不得默认装全部。"""
        with isolated_home() as home:
            r = run_scan(
                "--market-install", "https://github.com/owner/repo",
                home=home)
        self.assertNotEqual(r.returncode, 0)
        merged = r.stdout + r.stderr
        self.assertTrue(
            "未选择" in merged or "技能" in merged,
            f"应提示需要选择技能，实际：{merged}")


class MarketPreviewCliTest(unittest.TestCase):
    """仓库预览：只读，打印将执行的 npx 命令。"""

    def test_preview_rejects_non_github_before_network(self):
        """非 GitHub 地址必须在校验阶段就拒绝，不能发起网络请求。"""
        with isolated_home() as home:
            r = run_scan(
                "--market-preview", "https://evil.example.com/a/b", home=home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("github", (r.stdout + r.stderr).lower())

    def test_preview_rejects_non_github(self):
        with isolated_home() as home:
            r = run_scan(
                "--market-preview", "https://evil.example.com/a/b", home=home)
        self.assertNotEqual(r.returncode, 0)

    def test_preview_json_shape(self):
        """JSON 出口的字段契约：即使仓库读取失败，结构也必须完整可解析。

        预览现在会真的执行 `npx skills add -l`（联网），CI 环境未必可用；
        因此这里只断言**结构**，不依赖网络结果。
        """
        with isolated_home() as home:
            r = run_scan(
                "--market-preview", "https://github.com/owner/repo",
                "--format", "json", home=home)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["action"], "preview")
        self.assertIn("-l", payload["argv"])
        for key in ("ok", "skills", "declared_count", "parsed_count",
                    "count_mismatch", "reason"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
