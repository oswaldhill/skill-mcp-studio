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


class PrimarySourceTest(unittest.TestCase):
    """主源 = 统一技能目录（2026-11-08 合并）。

    历史上「统一技能目录」与「Git 技能源」是两处独立配置，实践里总指向同一个
    目录，分别维护必然漂移。合并后统一目录由主源派生，这批断言守住三件事：
    主源唯一、目录跟随主源、无主源时不假装已配置。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="primary-")
        self.cfg = os.path.join(self.tmp, "git_sources.yaml")
        self.a = self._mk_repo("repo-a")
        self.b = self._mk_repo("repo-b")

    def _config_at(self, ledger):
        """把 ledger 摆到 <dir>/data/ 下，返回同目录的 config 路径（模拟仓库布局）。"""
        base = os.path.dirname(ledger)
        data_dir = os.path.join(base, "data")
        os.makedirs(data_dir, exist_ok=True)
        target = os.path.join(data_dir, "git_sources.yaml")
        if os.path.abspath(ledger) != os.path.abspath(target) and os.path.exists(ledger):
            import shutil

            shutil.copy2(ledger, target)
        cfg = os.path.join(base, "config.yaml")
        Path(cfg).write_text("unified_skills_dir: ~/.x\n", encoding="utf-8")
        return cfg

    def _mk_repo(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        _git(path, "init", "-q")
        _git(path, "config", "user.email", "t@example.com")
        _git(path, "config", "user.name", "Tester")
        return path

    def test_no_primary_returns_fallback_and_marks_missing(self):
        gs.add_source(self.a, source_id="a", config_path=self.cfg)
        directory, primary = gs.unified_dir_from_sources(gs.load_sources(self.cfg))
        self.assertIsNone(primary)
        self.assertTrue(directory.endswith(".skills-manager/skills"))

    def test_set_primary_makes_directory_follow_it(self):
        gs.add_source(self.a, source_id="a", config_path=self.cfg)
        gs.add_source(self.b, source_id="b", config_path=self.cfg)
        res = gs.set_primary("b", config_path=self.cfg)
        self.assertTrue(res["ok"])
        directory, primary = gs.unified_dir_from_sources(gs.load_sources(self.cfg))
        self.assertEqual(primary["id"], "b")
        self.assertEqual(directory, os.path.abspath(self.b))

    def test_primary_is_unique(self):
        """同一时刻只能有一个主源——两个会直接导致统一目录不确定。"""
        gs.add_source(self.a, source_id="a", config_path=self.cfg)
        gs.add_source(self.b, source_id="b", config_path=self.cfg)
        gs.set_primary("a", config_path=self.cfg)
        gs.set_primary("b", config_path=self.cfg)
        primaries = [s for s in gs.load_sources(self.cfg) if s.get("primary")]
        self.assertEqual(len(primaries), 1)
        self.assertEqual(primaries[0]["id"], "b")

    def test_primary_is_forced_enabled(self):
        """主源被禁用会让统一目录整天「跳过」，因此设主源时强制启用。"""
        gs.add_source(self.a, source_id="a", enabled=False, config_path=self.cfg)
        gs.set_primary("a", config_path=self.cfg)
        entry = gs.load_sources(self.cfg)[0]
        self.assertTrue(entry["enabled"])

    def test_unknown_primary_id_rejected(self):
        res = gs.set_primary("nope", config_path=self.cfg)
        self.assertFalse(res["ok"])

    def test_apply_primary_overrides_config(self):
        gs.add_source(self.a, source_id="a", config_path=self.cfg)
        gs.set_primary("a", config_path=self.cfg)
        cfg = {"unified_skills_dir": "~/.old-place"}
        out = gs.apply_primary_to_config(cfg, config_path=self._config_at(self.cfg))
        self.assertEqual(out["unified_skills_dir"], os.path.abspath(self.a))

    def test_apply_primary_fills_absent_key(self):
        """没有主源时不能把已有值抹掉（测试夹具会直接写 unified_skills_dir）。"""
        cfg = {"unified_skills_dir": "~/.explicit"}
        out = gs.apply_primary_to_config(cfg, config_path=self._config_at(self.cfg))
        self.assertEqual(out["unified_skills_dir"], "~/.explicit")

    def test_absent_key_gets_fallback_when_no_primary(self):
        cfg = {}
        out = gs.apply_primary_to_config(cfg, config_path=self._config_at(self.cfg))
        self.assertTrue(str(out["unified_skills_dir"]).endswith("skills"))

    def test_corrupt_ledger_does_not_break_config(self):
        """登记表损坏只影响 Git 源功能，不能锁死整个配置加载。"""
        Path(self.cfg).write_text("sources: [unclosed\n", encoding="utf-8")
        cfg = {"unified_skills_dir": "~/.keep"}
        out = gs.apply_primary_to_config(cfg, config_path=self.cfg)
        self.assertEqual(out["unified_skills_dir"], "~/.keep")


class CommitTest(unittest.TestCase):
    """提交现有改动（2026-11-08 需求：设置页只有检查/拉取/推送，缺了「提交」，
    于是脏工作区既不能拉也推不出去，成了死结）。"""

    def setUp(self):
        self.pair = _RepoPair()
        self.pair.add_skill(self.pair.a, "skill-a")
        self.pair.commit_all(self.pair.a, "init")
        _git(self.pair.a, "push", "-q", "origin", "master")

    def test_status_lists_files_with_counts(self):
        self.pair.add_skill(self.pair.a, "skill-b")
        os.makedirs(os.path.join(self.pair.a, "gone"), exist_ok=True)
        Path(self.pair.a, "gone", "x.md").write_text("x", encoding="utf-8")
        self.pair.commit_all(self.pair.a, "add gone")
        _git(self.pair.a, "push", "-q", "origin", "master")
        os.remove(os.path.join(self.pair.a, "gone", "x.md"))
        self.pair.add_skill(self.pair.a, "skill-c")

        st = ops.commit_status(self.pair.a)
        self.assertTrue(st["ok"])
        self.assertTrue(st["dirty"])
        self.assertIn("untracked", st["counts"])
        self.assertIn("deleted", st["counts"])
        self.assertEqual(st["total"], len(st["files"]))

    def test_dry_run_does_not_commit(self):
        self.pair.add_skill(self.pair.a, "skill-b")
        before = _git(self.pair.a, "rev-parse", "HEAD").stdout.strip()
        res = ops.commit_source("a", self.pair.a, dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        after = _git(self.pair.a, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(before, after, "dry-run 竟然产生了 commit")
        # 改动仍在
        self.assertTrue(ops.commit_status(self.pair.a)["dirty"])

    def test_commit_clears_worktree(self):
        self.pair.add_skill(self.pair.a, "skill-b")
        res = ops.commit_source("a", self.pair.a, message="add skill-b")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["status"], "committed")
        self.assertEqual(res["remaining"], 0, "提交后工作区应干净")
        self.assertNotEqual(res["before"], res["after"])

    def test_commit_includes_deletions(self):
        """删除也必须被提交——这正是真实仓库里 75 个 D 的来源。"""
        os.remove(os.path.join(self.pair.a, "skill-a", "SKILL.md"))
        res = ops.commit_source("a", self.pair.a, message="remove a")
        self.assertTrue(res["ok"], res)
        self.assertEqual(ops.commit_status(self.pair.a)["total"], 0)

    def test_nothing_to_commit(self):
        res = ops.commit_source("a", self.pair.a)
        self.assertEqual(res["status"], "nothing-to-commit")
        self.assertTrue(res["ok"])

    def test_default_message_used_when_blank(self):
        self.pair.add_skill(self.pair.a, "skill-b")
        res = ops.commit_source("a", self.pair.a, message="   ")
        self.assertTrue(res["ok"])
        subject = _git(self.pair.a, "log", "-1", "--pretty=%s").stdout.strip()
        self.assertTrue(subject, "提交信息不得为空")

    def test_custom_message_reaches_run_on_all(self):
        """`run_on_all` 必须把提交信息透传下去。

        这条是回归守卫：最初 scan.py 算了 message 却没传给 run_on_all，
        表单里填的信息被静默丢弃、一律用默认文案。ruff 的「未使用变量」
        抓到了它，但那个提示读起来像代码卫生问题，实际是功能缺陷。
        """
        tmp = tempfile.mkdtemp(prefix="commitall-")
        cfg = os.path.join(tmp, "git_sources.yaml")
        repo = os.path.join(tmp, "r")
        os.makedirs(repo)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "Tester")
        Path(repo, "a.md").write_text("x", encoding="utf-8")
        gs.add_source(repo, source_id="r", config_path=cfg)

        results, summary = ops.run_on_all(
            "commit", config_path=cfg, message="feat: 我的自定义信息"
        )
        self.assertEqual(summary["ok"], 1, results)
        subject = _git(repo, "log", "-1", "--pretty=%s").stdout.strip()
        self.assertEqual(subject, "feat: 我的自定义信息", "自定义提交信息被丢弃了")

    def test_missing_identity_reports_clearly(self):
        """缺作者身份要如实报错，且**不得**去改用户的 git config。"""
        solo = os.path.join(self.pair.tmp, "noident")
        os.makedirs(solo)
        _git(solo, "init", "-q")
        # 清掉仓库级身份，并屏蔽全局身份
        _git(solo, "config", "--unset", "user.email", check=False)
        _git(solo, "config", "--unset", "user.name", check=False)
        env_home = os.path.join(self.pair.tmp, "emptyhome")
        os.makedirs(env_home, exist_ok=True)
        old_home = os.environ.get("HOME")
        try:
            os.environ["HOME"] = env_home
            os.environ["GIT_CONFIG_GLOBAL"] = os.path.join(env_home, ".gitconfig")
            Path(solo, "f.txt").write_text("x", encoding="utf-8")
            res = ops.commit_source("s", solo)
            self.assertEqual(res["status"], "no-identity", res)
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home
            os.environ.pop("GIT_CONFIG_GLOBAL", None)


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
