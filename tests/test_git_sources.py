"""Git 技能源（``core/git_sources.py`` + ``core/git_sync_ops.py``）的门禁断言。

这批断言全部用**真实临时 git 仓库**跑，不 mock git：本功能的语义就是 git
子命令的行为（领先/落后/分叉、脏工作区、快进 vs 合并），mock 掉就等于把要
验的东西删了。

覆盖 6 类事实：
1. 技能发现口径与统一库一致——顶层计入数量，嵌套单独列出，``_trash`` 与
   隐藏目录不算技能；
2. 登记只接受真实 git 工作区，重复/占位 id 被拒绝；
3. ``check`` 能区分 current / behind / ahead / diverged；
4. ``pull`` 默认只快进：脏工作区拒绝且**不动**任何文件；分叉时 ff-only 拒绝；
   ``--merge`` 才允许合并；
5. ``push`` 在落后时拒绝，``dry-run`` 不真推；
6. 配置非法时不静默——坏文件抛错并点名，绝不返回「没有源」。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import git_sources as gs  # noqa: E402
import git_sync_ops as ops  # noqa: E402


def _git(cwd, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if check:
        assert proc.returncode == 0, f"git {' '.join(args)} 失败: {proc.stderr}"
    return proc


class _RepoPair:
    """一个 bare 远端 + 两个工作副本，用来制造「远端有新提交」与「分叉」。"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="gitsrc-")
        self.remote = os.path.join(self.tmp, "remote.git")
        self.a = os.path.join(self.tmp, "a")
        self.b = os.path.join(self.tmp, "b")
        os.makedirs(self.remote)
        _git(self.remote, "init", "--bare", "-q", "-b", "master")
        _git(self.tmp, "clone", "-q", self.remote, self.a)
        for repo in (self.a,):
            _git(repo, "config", "user.email", "t@example.com")
            _git(repo, "config", "user.name", "Tester")

    def add_skill(self, repo, name, sub=""):
        d = os.path.join(repo, sub, name) if sub else os.path.join(repo, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(f"# {name}\n")
        return d

    def commit_all(self, repo, msg="c"):
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", msg, "--allow-empty")

    def clone_second(self):
        _git(self.tmp, "clone", "-q", self.remote, self.b)
        _git(self.b, "config", "user.email", "t@example.com")
        _git(self.b, "config", "user.name", "Tester")


class DiscoverSkillsTest(unittest.TestCase):
    """发现口径：必须与统一库一致，否则同一技能在页面间会算出两个数。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="discover-")

    def _mk(self, rel):
        d = os.path.join(self.tmp, rel)
        os.makedirs(d, exist_ok=True)
        Path(d, "SKILL.md").write_text("# x\n", encoding="utf-8")

    def test_top_level_counted_nested_listed(self):
        self._mk("skill-a")
        self._mk("skill-b")
        self._mk("pack/skill-c")
        found = gs.discover_skills(self.tmp)
        self.assertEqual(sorted(found["top_level"]), ["skill-a", "skill-b"])
        self.assertEqual(found["nested"], {"pack": ["pack/skill-c"]})

    def test_trash_and_hidden_are_ignored(self):
        """`_trash` 是软删除回收站，里面的 SKILL.md 绝不能算成技能。"""
        self._mk("real")
        self._mk("_trash/old-skill")
        self._mk(".hidden/skill")
        self._mk("node_modules/pkg/skill")
        found = gs.discover_skills(self.tmp)
        self.assertEqual(found["top_level"], ["real"])
        self.assertEqual(found["nested"], {})

    def test_missing_dir_returns_empty(self):
        found = gs.discover_skills(os.path.join(self.tmp, "nope"))
        self.assertEqual(found, {"top_level": [], "nested": {}})


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reg-")
        self.cfg = os.path.join(self.tmp, "git_sources.yaml")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "Tester")

    def test_add_and_list(self):
        res = gs.add_source(self.repo, source_id="r1", label="仓库一", config_path=self.cfg)
        self.assertTrue(res["ok"])
        loaded = gs.load_sources(self.cfg)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "r1")
        self.assertEqual(loaded[0]["path"], os.path.abspath(self.repo))

    def test_reject_non_git_dir(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        res = gs.add_source(plain, config_path=self.cfg)
        self.assertFalse(res["ok"])
        self.assertIn("不是 git 仓库", res["error"])

    def test_reject_duplicate_id(self):
        gs.add_source(self.repo, source_id="r1", config_path=self.cfg)
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        _git(other, "init", "-q")
        res = gs.add_source(other, source_id="r1", config_path=self.cfg)
        self.assertFalse(res["ok"])
        self.assertIn("已被另一个目录占用", res["error"])

    def test_remove_only_unregisters(self):
        gs.add_source(self.repo, source_id="r1", config_path=self.cfg)
        res = gs.remove_source("r1", config_path=self.cfg)
        self.assertTrue(res["ok"])
        self.assertEqual(gs.load_sources(self.cfg), [])
        # 磁盘目录必须原样还在——删除登记不等于删目录
        self.assertTrue(os.path.isdir(self.repo))

    def test_corrupt_config_raises_not_silent(self):
        """坏文件必须抛错并点名，绝不能静默当成「没有源」。"""
        Path(self.cfg).write_text("sources: [unclosed\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            gs.load_sources(self.cfg)
        self.assertIn("git_sources", str(ctx.exception))

    def test_missing_config_is_empty_not_error(self):
        self.assertEqual(gs.load_sources(os.path.join(self.tmp, "none.yaml")), [])


class InspectAndCheckTest(unittest.TestCase):
    def setUp(self):
        self.pair = _RepoPair()
        self.pair.add_skill(self.pair.a, "skill-a")
        self.pair.commit_all(self.pair.a, "init")
        _git(self.pair.a, "push", "-q", "origin", "master")

    def test_inspect_reports_counts_and_branch(self):
        info = gs.inspect(self.pair.a)
        self.assertTrue(info["is_repo"])
        self.assertEqual(info["branch"], "master")
        self.assertEqual(info["skill_count"], 1)
        self.assertFalse(info["dirty"])

    def test_check_current(self):
        res = ops.check_source("a", self.pair.a)
        self.assertEqual(res["status"], "current")

    def test_check_behind_after_remote_commit(self):
        self.pair.clone_second()
        self.pair.add_skill(self.pair.b, "skill-b")
        self.pair.commit_all(self.pair.b, "add b")
        _git(self.pair.b, "push", "-q", "origin", "master")
        res = ops.check_source("a", self.pair.a)
        self.assertEqual(res["status"], "behind")
        self.assertEqual(res["behind"], 1)

    def test_check_ahead_after_local_commit(self):
        self.pair.add_skill(self.pair.a, "local-only")
        self.pair.commit_all(self.pair.a, "local")
        res = ops.check_source("a", self.pair.a)
        self.assertEqual(res["status"], "ahead")
        self.assertEqual(res["ahead"], 1)

    def test_check_diverged(self):
        self.pair.clone_second()
        self.pair.add_skill(self.pair.b, "theirs")
        self.pair.commit_all(self.pair.b, "theirs")
        _git(self.pair.b, "push", "-q", "origin", "master")
        self.pair.add_skill(self.pair.a, "mine")
        self.pair.commit_all(self.pair.a, "mine")
        res = ops.check_source("a", self.pair.a)
        self.assertEqual(res["status"], "diverged")


class PullTest(unittest.TestCase):
    def setUp(self):
        self.pair = _RepoPair()
        self.pair.add_skill(self.pair.a, "skill-a")
        self.pair.commit_all(self.pair.a, "init")
        _git(self.pair.a, "push", "-q", "origin", "master")

    def _advance_remote(self, name="skill-b"):
        self.pair.clone_second()
        self.pair.add_skill(self.pair.b, name)
        self.pair.commit_all(self.pair.b, f"add {name}")
        _git(self.pair.b, "push", "-q", "origin", "master")

    def test_dry_run_does_not_change_worktree(self):
        self._advance_remote()
        res = ops.pull_source("a", self.pair.a, dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertFalse(os.path.exists(os.path.join(self.pair.a, "skill-b")))

    def test_fast_forward_pull(self):
        self._advance_remote()
        res = ops.pull_source("a", self.pair.a)
        self.assertEqual(res["status"], "pulled")
        self.assertTrue(os.path.exists(os.path.join(self.pair.a, "skill-b")))

    def test_dirty_worktree_refused_and_files_kept(self):
        """脏工作区必须拒绝，且**不 stash、不覆盖**用户改动。"""
        self._advance_remote()
        wip = os.path.join(self.pair.a, "wip.txt")
        Path(wip).write_text("work in progress", encoding="utf-8")
        res = ops.pull_source("a", self.pair.a)
        self.assertEqual(res["status"], "dirty")
        self.assertTrue(os.path.exists(wip), "未提交改动被删了")
        self.assertFalse(
            os.path.exists(os.path.join(self.pair.a, "skill-b")), "脏工作区仍被拉取了"
        )

    def test_diverged_refused_in_ff_only(self):
        self._advance_remote()
        self.pair.add_skill(self.pair.a, "mine")
        self.pair.commit_all(self.pair.a, "mine")
        res = ops.pull_source("a", self.pair.a, mode="ff-only")
        self.assertEqual(res["status"], "diverged")
        self.assertIn("--merge", res["message"])

    def test_diverged_merges_when_explicitly_allowed(self):
        self._advance_remote()
        self.pair.add_skill(self.pair.a, "mine")
        self.pair.commit_all(self.pair.a, "mine")
        res = ops.pull_source("a", self.pair.a, mode="merge")
        self.assertTrue(res["ok"], res)
        self.assertTrue(os.path.exists(os.path.join(self.pair.a, "skill-b")))

    def test_no_remote_is_not_an_error(self):
        solo = os.path.join(self.pair.tmp, "solo")
        os.makedirs(solo)
        _git(solo, "init", "-q")
        res = ops.pull_source("solo", solo)
        self.assertEqual(res["status"], "no-remote")


class PushTest(unittest.TestCase):
    def setUp(self):
        self.pair = _RepoPair()
        self.pair.add_skill(self.pair.a, "skill-a")
        self.pair.commit_all(self.pair.a, "init")
        _git(self.pair.a, "push", "-q", "origin", "master")

    def test_dry_run_does_not_push(self):
        self.pair.add_skill(self.pair.a, "new")
        self.pair.commit_all(self.pair.a, "new")
        res = ops.push_source("a", self.pair.a, dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.pair.clone_second()
        self.assertFalse(os.path.exists(os.path.join(self.pair.b, "new")))

    def test_push_then_remote_has_it(self):
        self.pair.add_skill(self.pair.a, "new")
        self.pair.commit_all(self.pair.a, "new")
        res = ops.push_source("a", self.pair.a)
        self.assertEqual(res["status"], "pushed")
        self.pair.clone_second()
        self.assertTrue(os.path.exists(os.path.join(self.pair.b, "new")))

    def test_nothing_to_push(self):
        res = ops.push_source("a", self.pair.a)
        self.assertEqual(res["status"], "nothing-to-push")

    def test_no_local_commit_reports_nothing_to_push(self):
        """远端领先但本地无提交时，应报「没有需要推送的提交」而不是失败。"""
        self.pair.clone_second()
        self.pair.add_skill(self.pair.b, "theirs")
        self.pair.commit_all(self.pair.b, "theirs")
        _git(self.pair.b, "push", "-q", "origin", "master")
        res = ops.push_source("a", self.pair.a)
        self.assertEqual(res["status"], "nothing-to-push")

    def test_behind_with_local_commit_refuses(self):
        self.pair.clone_second()
        self.pair.add_skill(self.pair.b, "theirs")
        self.pair.commit_all(self.pair.b, "theirs")
        _git(self.pair.b, "push", "-q", "origin", "master")
        self.pair.add_skill(self.pair.a, "mine")
        self.pair.commit_all(self.pair.a, "mine")
        res = ops.push_source("a", self.pair.a)
        self.assertEqual(res["status"], "behind")


class CloneTest(unittest.TestCase):
    def setUp(self):
        self.pair = _RepoPair()
        self.pair.add_skill(self.pair.a, "skill-a")
        self.pair.commit_all(self.pair.a, "init")
        _git(self.pair.a, "push", "-q", "origin", "master")

    def test_dry_run_reports_without_cloning(self):
        dest = os.path.join(self.pair.tmp, "cloned")
        res = ops.clone_source(self.pair.remote, dest, dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertFalse(os.path.exists(dest))

    def test_clone_success(self):
        dest = os.path.join(self.pair.tmp, "cloned")
        res = ops.clone_source(self.pair.remote, dest)
        self.assertTrue(res["ok"], res)
        self.assertTrue(os.path.exists(os.path.join(dest, "skill-a", "SKILL.md")))

    def test_refuses_non_empty_target(self):
        dest = os.path.join(self.pair.tmp, "busy")
        os.makedirs(dest)
        Path(dest, "x").write_text("y", encoding="utf-8")
        res = ops.clone_source(self.pair.remote, dest)
        self.assertFalse(res["ok"])
        self.assertIn("非空", res["message"])


class CheckAllTest(unittest.TestCase):
    def test_disabled_source_is_skipped(self):
        tmp = tempfile.mkdtemp(prefix="all-")
        cfg = os.path.join(tmp, "g.yaml")
        repo = os.path.join(tmp, "r")
        os.makedirs(repo)
        _git(repo, "init", "-q")
        gs.add_source(repo, source_id="r", enabled=False, config_path=cfg)
        results = gs.check_all(config_path=cfg)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["skipped"])

    def test_summarize_counts(self):
        results = [
            {"enabled": True, "is_repo": True, "dirty": True, "behind": 0, "ahead": 0,
             "skill_count": 3, "error": ""},
            {"enabled": True, "is_repo": True, "dirty": False, "behind": 2, "ahead": 0,
             "skill_count": 5, "error": ""},
            {"enabled": True, "error": "目录不存在", "skill_count": 0},
        ]
        s = gs.summarize(results)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["dirty"], 1)
        self.assertEqual(s["behind"], 1)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["skills"], 8)


if __name__ == "__main__":
    unittest.main()
