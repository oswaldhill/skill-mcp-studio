"""仓库形态技能源（core/skill_repo_source.py）的门禁断言。

这批断言用**真实临时 git 仓库**跑，不是 grep：仓库形态的判定全是 git 子命令
的语义（diff 的目录收敛、rename 行、dirty 收口、上游 ref 缺失），mock 掉命令
就等于把要验的东西删了。

覆盖 5 类事实：
1. 上游分支上某技能目录有新提交 → 该技能 repo_outdated，其他技能 current；
2. 本地有未提交修改 → unknown（不能笼统说「可同步」，同步必冲突）；
3. 缺少 origin/<branch> ref → ok=False + 明确原因（不是静默 current）；
4. 目录不是 git 工作区 → ok=False；
5. diff 里的非技能路径（README.md、_core/ 等）不得被算成技能。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import skill_repo_source as repo  # noqa: E402


def _git(cwd, *args):
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败: {proc.stderr}"
    return proc.stdout.strip()


class _TmpRepo:
    """建一个带两个技能目录的临时 git 仓库，并造一条「上游」引用。"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="repo-form-")
        self.path = self.tmp
        _git(self.path, "init", "-q", "-b", "master")
        _git(self.path, "config", "user.email", "t@example.com")
        _git(self.path, "config", "user.name", "t")
        self._write("alpha/SKILL.md", "# alpha v1\n")
        self._write("beta/SKILL.md", "# beta v1\n")
        self._write("README.md", "root readme\n")
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "-q", "-m", "c1")

    def _write(self, rel, text):
        p = Path(self.path) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def set_upstream_to_head(self):
        """把 origin/master 指到当前 HEAD：造出「已同步」的基准。"""
        tip = _git(self.path, "rev-parse", "HEAD")
        _git(self.path, "update-ref", "refs/remotes/origin/master", tip)

    def upstream_changes(self, only=("alpha",)):
        """造「上游有新提交」：改 only 里的目录，提交后把 origin/master 指过来。

        本地 HEAD 回退到 c1，于是 `git diff HEAD origin/master` 会显出这些变更。
        """
        base = _git(self.path, "rev-parse", "HEAD")
        if not only:
            self.set_upstream_to_head()
            return
        for name in only:
            self._write(f"{name}/SKILL.md", f"# {name} v2\n")
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "-q", "-m", "upstream change")
        tip = _git(self.path, "rev-parse", "HEAD")
        _git(self.path, "update-ref", "refs/remotes/origin/master", tip)
        _git(self.path, "reset", "-q", "--hard", base)

    def cleanup(self):
        subprocess.run(["rm", "-rf", self.tmp], timeout=30)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.repo = _TmpRepo()
        self.addCleanup(self.repo.cleanup)

    def test_upstream_change_is_repo_outdated(self):
        self.repo.upstream_changes(only=("alpha",))
        snap = repo.snapshot(self.repo.path, {"alpha", "beta"})
        self.assertTrue(snap["ok"], snap["error"])
        self.assertEqual(snap["upstream"], "origin/master")
        self.assertIn("alpha", snap["changed"])
        self.assertNotIn("beta", snap["changed"])

        state, note, remote_time = repo.classify("alpha", snap)
        self.assertEqual(state, repo.REPO_OUTDATED)
        self.assertIn("origin/master", note)
        self.assertTrue(remote_time, "基准提交时间必须透出，否则「很久没 fetch」会被读成「远端没变」")

        state_b, _n, _t = repo.classify("beta", snap)
        self.assertEqual(state_b, "current")

    def test_dirty_skill_is_unknown_not_current(self):
        # 本地改了 alpha 但没提交：同步会冲突，只能报 unknown
        self.repo.set_upstream_to_head()
        (Path(self.repo.path) / "alpha" / "SKILL.md").write_text("# alpha local\n", encoding="utf-8")
        snap = repo.snapshot(self.repo.path, {"alpha", "beta"})
        self.assertTrue(snap["ok"], snap["error"])
        state, note, _t = repo.classify("alpha", snap)
        self.assertEqual(state, "unknown")
        self.assertIn("未提交", note)

    def test_missing_upstream_ref_is_not_success(self):
        # 没有 origin/master → ok=False，绝不能静默判成 current
        snap = repo.snapshot(self.repo.path, {"alpha", "beta"})
        self.assertFalse(snap["ok"])
        self.assertIn("origin/master", snap["error"])
        state, note, _t = repo.classify("alpha", snap)
        self.assertEqual(state, "unknown")
        self.assertIn("origin/master", note)

    def test_non_repo_dir_is_not_success(self):
        plain = tempfile.mkdtemp(prefix="plain-")
        self.addCleanup(subprocess.run, ["rm", "-rf", plain], timeout=30)
        snap = repo.snapshot(plain, {"alpha"})
        self.assertFalse(snap["ok"])
        self.assertIn("不是 git 工作区", snap["error"])

    def test_non_skill_paths_are_not_counted(self):
        # README.md 在根上、_core/ 是保留目录：都不该被当成技能
        self.repo.set_upstream_to_head()
        (Path(self.repo.path) / "README.md").write_text("readme v2\n", encoding="utf-8")
        base = _git(self.repo.path, "rev-parse", "HEAD")
        _git(self.repo.path, "add", "-A")
        _git(self.repo.path, "commit", "-q", "-m", "readme only")
        tip = _git(self.repo.path, "rev-parse", "HEAD")
        _git(self.repo.path, "update-ref", "refs/remotes/origin/master", tip)
        _git(self.repo.path, "reset", "-q", "--hard", base)

        snap = repo.snapshot(self.repo.path, {"alpha", "beta"})
        self.assertTrue(snap["ok"], snap["error"])
        self.assertEqual(set(), snap["changed"],
                         "根目录 README.md 不该被算成技能待同步")


class TopDirTest(unittest.TestCase):
    def test_rename_line_maps_to_new_dir(self):
        got = repo._top_dirs_from_diff(["alpha/{old.md => new.md}"], {"alpha"})
        self.assertEqual({"alpha"}, got)

    def test_unknown_top_dir_ignored(self):
        got = repo._top_dirs_from_diff(["LICENSE", "_core/x.md", "alpha/SKILL.md"], {"alpha"})
        self.assertEqual({"alpha"}, got)


if __name__ == "__main__":
    unittest.main()


class FetchBeforeCompareTest(unittest.TestCase):
    """判定前必须先看真实远端（2026-11-05 用户反馈）。

    ## 缺陷

    ``snapshot`` 只比对**本地缓存的 origin/<branch> ref**，从不动网络。本机实测：
    该 ref 停在 2026-11-02（一周前），期间远端即便有新提交也发现不了 —— 153 个
    仓库形态技能会全部显示「与远端一致」。

    用户的直觉是对的：他看到某技能本地 07/21、远端基准 11/02，问「差这么大为什么
    不算可更新」。那次碰巧远端确实没变（fetch 验证过），但**判定方法本身不足以
    支撑这个结论** —— 一个永远说「一致」的检查等于没检查。

    ## 判据

    1. ``refresh=True`` 时先 fetch，再对比；fetch 成功则用**真实远端**判定；
    2. fetch 失败（无网络 / 认证失败）**不能静默当成 current**：参考基准比不了，
       结果标 ``stale`` 并说明原因，调用方可据此提示「结论可能不准」；
    3. ``refresh=False``（默认）保持原行为 —— 纯只读、不联网，供高频调用路径使用。
    """

    def setUp(self):
        self.repo = _TmpRepo()
        self.addCleanup(self.repo.cleanup)

    def _add_bare_remote(self):
        """造一个 bare 仓库当 origin，再把两个仓库连起来。"""
        bare = tempfile.mkdtemp(prefix="bare-")
        self.addCleanup(subprocess.run, ["rm", "-rf", bare], timeout=30)
        _git(bare, "init", "-q", "--bare", "-b", "master")
        _git(self.repo.path, "remote", "add", "origin", bare)
        return bare

    def test_refresh_fetches_so_new_remote_commits_are_seen(self):
        bare = self._add_bare_remote()
        _git(self.repo.path, "push", "-q", "origin", "master")
        _git(self.repo.path, "update-ref", "refs/remotes/origin/master",
             _git(self.repo.path, "rev-parse", "HEAD"))

        # 另一侧（模拟别人）往远端推了一条改动 alpha 的提交
        other = tempfile.mkdtemp(prefix="other-")
        self.addCleanup(subprocess.run, ["rm", "-rf", other], timeout=30)
        _git(other, "clone", "-q", bare, ".")
        _git(other, "config", "user.email", "o@example.com")
        _git(other, "config", "user.name", "o")
        Path(other, "alpha", "SKILL.md").write_text("# alpha v2 remote\n", encoding="utf-8")
        _git(other, "add", "-A")
        _git(other, "commit", "-q", "-m", "remote: alpha v2")
        _git(other, "push", "-q", "origin", "master")

        # 不 fetch：基准还是旧的 → 看不到这条提交
        stale_snap = repo.snapshot(self.repo.path, {"alpha", "beta"})
        self.assertNotIn("alpha", stale_snap["changed"],
                         "前提：不 fetch 时基准未更新，应看不到远端新提交")

        # fetch 后再判：必须看到
        fresh_snap = repo.snapshot(self.repo.path, {"alpha", "beta"}, refresh=True)
        self.assertTrue(fresh_snap["ok"], fresh_snap["error"])
        self.assertIn("alpha", fresh_snap["changed"],
                      "refresh=True 时没有 fetch，远端新提交被漏判成「一致」")
        state, _note, _t = repo.classify("alpha", fresh_snap)
        self.assertEqual(state, repo.REPO_OUTDATED)

    def test_fetch_failure_is_not_silently_current(self):
        # 指向一个不存在的远端：fetch 必失败
        _git(self.repo.path, "remote", "add", "origin", "/nonexistent/repo.git")
        _git(self.repo.path, "update-ref", "refs/remotes/origin/master",
             _git(self.repo.path, "rev-parse", "HEAD"))
        snap = repo.snapshot(self.repo.path, {"alpha", "beta"}, refresh=True)
        self.assertTrue(snap.get("stale"), "fetch 失败必须标记 stale，不能静默当 current")
        self.assertIn("远端", snap.get("stale_reason") or "")
        # 有本地基准可比时仍给出结论，但 note 必须说明「基准可能过期」
        _state, note, _t = repo.classify("alpha", snap)
        self.assertIn("过期", note)

    def test_refresh_false_does_not_touch_network(self):
        # 默认路径纯只读：把 fetch 换成本该爆炸的替身，确认根本没被调用
        import unittest.mock as mock

        self.repo.set_upstream_to_head()
        with mock.patch.object(repo, "_git") as fake:
            fake.return_value = (0, "", "")
            repo.snapshot(self.repo.path, {"alpha"}, refresh=False)
        calls = [c.args[1] for c in fake.call_args_list if len(c.args) > 1]
        self.assertNotIn("fetch", calls, "refresh=False 时不该发起 fetch")
