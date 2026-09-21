"""高危模块回归测试（T-2 整改）。

覆盖历史无测试但生产路径中被 scan.py 直接调用的模块中的高风险分支：

- ``workspace_cleaner``：临时文件/可疑文件分类 + 真实删除（os.remove/shutil.rmtree）
- ``version_checker``：版本号比较纯逻辑 + GitHub API 网络探测（mock curl）
- ``git_sync``：git 仓库识别（真实 temp git repo）

这些路径先前零测试（评审 T-2: 删除/网络/写备份类高危路径），现补上回归护栏。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import workspace_cleaner  # noqa: E402
import version_checker  # noqa: E402
import git_sync  # noqa: E402
import hooks_checker  # noqa: E402


class WorkspaceCleanerTest(unittest.TestCase):
    def test_is_temp_file_exact_and_pattern(self):
        self.assertTrue(workspace_cleaner._is_temp_file(os.path.join("x", "__pycache__")))
        self.assertTrue(workspace_cleaner._is_temp_file(os.path.join("x", "a.pyc")))
        self.assertTrue(workspace_cleaner._is_temp_file(os.path.join("x", ".DS_Store")))
        self.assertFalse(workspace_cleaner._is_temp_file(os.path.join("x", "main.py")))

    def test_is_suspicious_file(self):
        self.assertTrue(workspace_cleaner._is_suspicious_file(os.path.join("x", ".env")))
        self.assertTrue(workspace_cleaner._is_suspicious_file(os.path.join("x", "id_rsa")))
        self.assertTrue(workspace_cleaner._is_suspicious_file(os.path.join("x", "tls.pem")))
        self.assertFalse(workspace_cleaner._is_suspicious_file(os.path.join("x", "readme.md")))

    def test_classify_untracked_partitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            auto_add, ask, auto_delete = workspace_cleaner.classify_untracked(
                tmp, ["main.py", ".env", "cache.pyc", "data.xyz"]
            )
            self.assertIn("main.py", auto_add)
            self.assertIn(".env", ask)       # 敏感 → 问
            self.assertIn("cache.pyc", auto_delete)  # 临时 → 删
            self.assertIn("data.xyz", ask)   # 未知扩展名 → 问

    def test_clean_temp_files_dry_run_removes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 造一个临时文件 + 一个正常文件
            pyc = os.path.join(tmp, "dead.pyc")
            keep = os.path.join(tmp, "keep.py")
            open(pyc, "w").close()
            open(keep, "w").close()
            res = workspace_cleaner.clean_temp_files(tmp, dry_run=True)
            self.assertGreaterEqual(res["removed_count"], 1)
            self.assertTrue(os.path.exists(pyc), "dry_run 不应删除文件")
            self.assertTrue(os.path.exists(keep))

    def test_clean_temp_files_actually_removes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyc = os.path.join(tmp, "dead.pyc")
            keep = os.path.join(tmp, "keep.py")
            open(pyc, "w").close()
            open(keep, "w").close()
            res = workspace_cleaner.clean_temp_files(tmp, dry_run=False)
            self.assertFalse(os.path.exists(pyc), "非 dry_run 应删除临时文件")
            self.assertTrue(os.path.exists(keep), "正常源文件不应被删")


class VersionCheckerTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(version_checker.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(version_checker.parse_version("0.20.0"), (0, 20, 0))
        self.assertEqual(version_checker.parse_version(""), (0,))
        self.assertEqual(version_checker.parse_version("1.2.3-beta"), (1, 2, 3, 0))

    def test_is_newer(self):
        self.assertTrue(version_checker.is_newer("1.2.0", "1.1.9"))
        self.assertFalse(version_checker.is_newer("1.1.9", "1.2.0"))
        self.assertFalse(version_checker.is_newer("", "1.0.0"))
        self.assertTrue(version_checker.is_newer("1.0.0", ""))

    def test_get_github_latest_version_release(self):
        fake_stdout = '{"tag_name": "v1.2.3"}'
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = fake_stdout
            version = version_checker.get_github_latest_version("owner/repo")
        self.assertEqual(version, "1.2.3")

    def test_get_github_latest_version_fallback_to_tags(self):
        # 第一次调用返回空（release 无），第二次返回 tags 列表
        import subprocess as sp

        results = [sp.CompletedProcess([], 0, "", ""), sp.CompletedProcess([], 0, '[{"name": "v2.0.0"}]', "")]
        with patch("subprocess.run", side_effect=results) as run:
            version = version_checker.get_github_latest_version("owner/repo")
        self.assertEqual(version, "2.0.0")

    def test_get_github_latest_version_failure_returns_none(self):
        import subprocess as sp

        with patch("subprocess.run") as run:
            # 现实中的网络/超时失败 = subprocess.TimeoutExpired（SubprocessError 子类）。
            run.side_effect = sp.TimeoutExpired(cmd=["curl"], timeout=15)
            version = version_checker.get_github_latest_version("owner/repo")
        self.assertIsNone(version)


class GitSyncTest(unittest.TestCase):
    def test_is_git_repo_true(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            self.assertTrue(git_sync.is_git_repo(tmp))

    def test_is_git_repo_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(git_sync.is_git_repo(tmp))


class HooksCheckerTest(unittest.TestCase):
    """真实 hook 配置检测（history: combined_checker 测试用空 required_capabilities 短路了 hooks 分支）。"""

    def test_detects_ai_memory_hook(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            import json

            json.dump({
                "hooks": {
                    "Stop": [{"command": "ai-memory hook --event stop"}],
                    "Start": [{"command": "echo hello"}],
                }
            }, f)
            path = f.name
        try:
            res = hooks_checker.check_hooks(path)
            self.assertTrue(res["hooks_configured"])
            self.assertEqual(res["events"], ["Stop"])
        finally:
            os.unlink(path)

    def test_no_hooks_when_missing_file(self):
        res = hooks_checker.check_hooks("/nonexistent/hooks.json")
        self.assertFalse(res["hooks_configured"])
        self.assertEqual(res["events"], [])

    def test_no_hooks_when_no_ai_memory_command(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            import json

            json.dump({"hooks": {"Stop": [{"command": "other tool"}]}}, f)
            path = f.name
        try:
            res = hooks_checker.check_hooks(path)
            self.assertFalse(res["hooks_configured"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()