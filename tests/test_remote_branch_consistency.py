"""远端分支一致性约束（2026-11-15）。

**为什么需要这条约束**：本仓库同时推两个远端 —— codeup（origin）与 GitHub
（github）。实测出现过 GitHub `master` 停在 `50282e5`、落后 codeup `master`
**14 个提交**（含代码，不只是文档）的不一致，而没有任何检查会报出来。

分支拓扑的既定契约（写死在这里，改动需同步本文件与 docs）：
- **codeup（origin）**：`master` + `develop` 两条主干。
  `develop` 是日常开发线，`master` 是发布线；两者不一致是**正常**的。
- **GitHub（github）**：**只有 `master`**。
  它没有、也不应有 `develop` —— 历史清理时明确只保留 master。

因此本测试只守两件**跨远端**的事：
1. GitHub 上不该出现 `develop`（出现即说明有人误推）。
2. GitHub `master` 必须是 codeup `master` 的祖先（不许分叉）。

**刻意不守**「GitHub master 必须等值于 codeup master」：GitHub 是发布镜像，
允许阶段性落后；把「落后」判成失败会逼人频繁推无意义的同步。落后量交由
`check_remote_drift.py` 报告（可运行、可纳入巡检），而不是当门禁硬拦。
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args) -> str:
    out = subprocess.run(["git", "-C", str(ROOT), *args],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip()


def _has_remote(name: str) -> bool:
    return name in _git("remote").split()


def _remote_branch_exists(remote: str, branch: str) -> bool:
    """直接问服务器，不看本地 tracking ref（tracking 可能过期）。"""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-remote", "--heads", remote, branch],
        capture_output=True, text=True, timeout=30)
    return bool(out.stdout.strip())


@unittest.skipUnless(_has_remote("github"), "本机未配置 github 远端")
class GithubRemoteShapeTest(unittest.TestCase):
    """GitHub 远端的分支形状。"""

    def test_github_has_no_develop_branch(self):
        """GitHub 不应有 develop 分支（历史清理只保留 master）。"""
        self.assertFalse(
            _remote_branch_exists("github", "develop"),
            "GitHub 上出现了 develop 分支 —— 该远端约定只保留 master",
        )

    def test_github_has_master(self):
        self.assertTrue(_remote_branch_exists("github", "master"),
                        "GitHub 缺少 master 分支")

    def test_github_master_not_diverged(self):
        """GitHub master 必须是本地 master 的祖先（只许落后，不许分叉）。"""
        rc = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor",
             "github/master", "master"],
            capture_output=True, timeout=30).returncode
        self.assertEqual(0, rc,
                         "GitHub master 与本地 master 已分叉 —— 需要人工处理"
                         "（merge 或 reset），不能只推快进")


@unittest.skipUnless(_has_remote("origin"), "本机未配置 origin 远端")
class CodeupRemoteShapeTest(unittest.TestCase):
    """codeup 远端的分支形状。"""

    def test_codeup_has_both_trunks(self):
        self.assertTrue(_remote_branch_exists("origin", "master"))
        self.assertTrue(_remote_branch_exists("origin", "develop"))

    def test_develop_never_ahead_in_unknown_way(self):
        """develop 与 origin/develop 不应有分叉（本地可快进即可）。"""
        rc = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor",
             "origin/develop", "develop"],
            capture_output=True, timeout=30).returncode
        self.assertEqual(0, rc, "本地 develop 与 origin/develop 已分叉")


if __name__ == "__main__":
    unittest.main()


class DriftScriptTest(unittest.TestCase):
    """scripts/check_remote_drift.py 的行为契约。"""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_remote_drift.py"), *args],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT))

    def test_script_exists_and_is_readonly(self):
        p = ROOT / "scripts" / "check_remote_drift.py"
        self.assertTrue(p.is_file())
        src = p.read_text(encoding="utf-8")
        # 硬约束：只读 —— 不得 fetch / push / pull / 修改引用
        for forbidden in ("\"push\"", "\"fetch\"", "\"pull\"", "\"reset\""):
            self.assertNotIn(f"git\", \"-C\", str(ROOT), {forbidden}", src,
                             f"漂移检查必须只读，出现了 {forbidden}")

    def test_json_output_shape(self):
        r = self._run("--json")
        self.assertIn(r.returncode, (0, 1), r.stderr[:300])
        payload = json.loads(r.stdout)
        for key in ("remotes", "problems", "notes", "pairs"):
            self.assertIn(key, payload)

    def test_divergence_fails_but_behind_does_not(self):
        """无 --strict 时落后不判失败；有 --strict 时落后判失败。"""
        plain = self._run()
        strict = self._run("--strict")
        # 若当前存在落后：plain 应为 0、strict 应为 1
        rep = json.loads(self._run("--json").stdout)
        has_behind = any(p.get("behind") for p in rep["pairs"])
        has_problem = bool(rep["problems"])
        if has_problem:
            self.assertEqual(1, plain.returncode, "有问题时普通模式也必须失败")
        elif has_behind:
            self.assertEqual(0, plain.returncode, "仅落后时普通模式不应失败")
            self.assertEqual(1, strict.returncode, "仅落后时 --strict 应失败")
        else:
            self.assertEqual(0, plain.returncode)
            self.assertEqual(0, strict.returncode)

    def test_documents_github_has_no_develop(self):
        """契约要写清 GitHub 不该有 develop，防止后人误推。"""
        src = (ROOT / "scripts" / "check_remote_drift.py").read_text(encoding="utf-8")
        self.assertIn('"github": ["master"]', src)
