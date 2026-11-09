"""自动接管统一目录为 Git 源（``--adopt-git-source``）的门禁断言。

背景（2026-11-09 用户反馈）：统一技能目录早就在 ``config.yaml`` 里配好、
磁盘上也确实是 git 工作区（有远端、有分支、技能列表扫得到 170+ 个），但
``data/git_sources.yaml`` 是空的——设置页于是同时显示「统一技能目录已设置」
和「尚未登记 Git 技能源」，四个同步按钮全在空转。用户无法判断到底配没配好，
只能把同一个路径手输一遍。``adopt_unified_dir()`` 把这一步自动化。

这批断言守 6 类事实：

1. 登记表为空 + 统一目录是 git 工作区 → 登记为主源（``primary: true``）；
2. 已有任何登记 → ``already-configured``，**绝不覆盖**用户源列表；
3. 统一目录不是 git 工作区 / 不存在 → ``not-git-repo``，不写任何文件；
4. ``dry-run`` 不落盘、不生成登记表；
5. 接管后 ``unified_dir_from_sources()`` 能派生出该目录（主源语义闭环）；
6. CLI 端到端：JSON 字段与退出码，GUI 契约（自动接管调用、Rust 白名单、
   DESIGN.md 已登记）。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import git_sources as gs  # noqa: E402


def _git(cwd, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if check:
        assert proc.returncode == 0, f"git {' '.join(args)} 失败: {proc.stderr}"
    return proc


def _make_repo(path: Path) -> None:
    """一个带一次提交的真实 git 工作区。"""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "test")
    (path / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "init")


class _Fixture:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = self.root / "config.yaml"
        self.config.write_text("unified_skills_dir: ~/.skills-manager/skills\n", encoding="utf-8")
        self.ledger = self.root / "data" / "git_sources.yaml"
        self.unified = self.root / "unified"

    def cleanup(self) -> None:
        self._tmp.cleanup()


class TestAdoptUnifiedDir(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_adopts_git_workdir_as_primary(self):
        _make_repo(self.fx.unified)

        res = gs.adopt_unified_dir(str(self.fx.config), unified_dir=str(self.fx.unified))

        self.assertEqual(res["status"], "adopted", res)
        self.assertEqual(res["id"], "unified")
        self.assertEqual(res["path"], str(self.fx.unified))
        self.assertTrue(res["branch"], "应报告分支")
        self.assertTrue(res["backup"] or self.fx.ledger.exists())

        sources = gs.load_sources(str(self.fx.ledger))
        self.assertEqual(len(sources), 1)
        self.assertTrue(sources[0]["primary"], "接管后必须直接是主源")
        self.assertTrue(sources[0]["enabled"])
        # 主源语义闭环：统一目录由登记表派生，不再依赖 config.yaml 的旧值。
        derived, primary = gs.unified_dir_from_sources(sources)
        self.assertEqual(derived, str(self.fx.unified))
        self.assertIsNotNone(primary)

    def test_already_configured_is_never_overwritten(self):
        _make_repo(self.fx.unified)
        other = self.fx.root / "other"
        _make_repo(other)
        gs.save_sources(
            [{"id": "other", "label": "other", "path": str(other), "enabled": True, "primary": True}],
            str(self.fx.ledger),
        )
        before = self.fx.ledger.read_bytes()

        res = gs.adopt_unified_dir(str(self.fx.config), unified_dir=str(self.fx.unified))

        self.assertEqual(res["status"], "already-configured")
        self.assertEqual(self.fx.ledger.read_bytes(), before,
                         "已有登记时一个字节都不能改")

    def test_non_git_dir_is_rejected_without_writing(self):
        self.fx.unified.mkdir(parents=True, exist_ok=True)  # 存在但没 .git

        res = gs.adopt_unified_dir(str(self.fx.config), unified_dir=str(self.fx.unified))

        self.assertEqual(res["status"], "not-git-repo")
        self.assertIn("Git 工作区", res["message"])
        self.assertFalse(self.fx.ledger.exists(), "拒绝时不得创建登记表")

    def test_missing_dir_is_rejected(self):
        res = gs.adopt_unified_dir(
            str(self.fx.config), unified_dir=str(self.fx.root / "nope"))

        self.assertEqual(res["status"], "not-git-repo")
        self.assertIn("不存在", res["message"])
        self.assertFalse(self.fx.ledger.exists())

    def test_dry_run_writes_nothing(self):
        _make_repo(self.fx.unified)

        res = gs.adopt_unified_dir(
            str(self.fx.config), unified_dir=str(self.fx.unified), dry_run=True)

        self.assertEqual(res["status"], "dry-run")
        self.assertEqual(res["branch"], res["branch"])  # 报告了分支
        self.assertFalse(self.fx.ledger.exists(), "dry-run 不得创建登记表")
        self.assertEqual(res["backup"], "")

    def test_fallback_dir_used_when_unified_dir_omitted(self):
        # 不传 unified_dir 时退到 FALLBACK_UNIFIED_DIR；这里用显式参数覆盖
        # 到临时仓库，验证「不传路径也能工作」的调用形态（GUI 不传路径）。
        _make_repo(self.fx.unified)
        res = gs.adopt_unified_dir(str(self.fx.config), unified_dir=str(self.fx.unified))
        self.assertEqual(res["status"], "adopted")


class TestAdoptCli(unittest.TestCase):
    """端到端：GUI 直接 JSON.parse 这条命令的 stdout。"""

    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)
        _make_repo(self.fx.unified)
        self.env = dict(os.environ)
        # 让 scan.py 用临时 config.yaml：--config 指向它，data/ 随之派生。
        self.config = self.fx.config
        self.config.write_text(
            f"unified_skills_dir: {self.fx.unified}\n", encoding="utf-8")

    def _run(self, *args: str):
        return subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), "--config", str(self.config), *args],
            cwd=str(ROOT), env=self.env, capture_output=True, text=True, timeout=120,
        )

    def test_json_dry_run_then_adopt(self):
        dry = self._run("--adopt-git-source", "--dry-run", "--format", "json")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        payload = json.loads(dry.stdout)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["path"], str(self.fx.unified))
        self.assertFalse(self.fx.ledger.exists(), "dry-run 不得落盘")

        done = self._run("--adopt-git-source", "--format", "json")
        self.assertEqual(done.returncode, 0, done.stderr)
        adopted = json.loads(done.stdout)
        self.assertEqual(adopted["status"], "adopted")
        self.assertTrue(self.fx.ledger.exists())
        sources = gs.load_sources(str(self.fx.ledger))
        self.assertTrue(sources[0]["primary"])

    def test_second_run_is_already_configured(self):
        self._run("--adopt-git-source", "--format", "json")
        again = self._run("--adopt-git-source", "--format", "json")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["status"], "already-configured")


class TestAdoptGuiContract(unittest.TestCase):
    """界面可达性：自动接管调用、Rust 白名单、规范文档必须同时在。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")
        cls.scan = (ROOT / "scan.py").read_text(encoding="utf-8")
        cls.lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        cls.design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")

    def test_gui_auto_adopts_when_no_source(self):
        self.assertIn("function autoAdoptUnifiedDir", self.dashboard,
                      "缺少自动接管实现")
        self.assertIn('"--adopt-git-source"', self.dashboard,
                      "GUI 必须调用 --adopt-git-source")
        # 只定义函数不算：必须真的在「无源」分支里被调用。反向验证发现，
        # 仅断言函数名与命令名时，把调用点删掉测试仍然通过——那正是
        # 「永远通过的测试等于没有测试」的典型。
        self.assertIn("if (await autoAdoptUnifiedDir()) return;", self.dashboard,
                      "自动接管必须真的被调用（只定义函数不算）")
        # 只在「从未配置过」时触发：已有登记就永不覆盖。
        self.assertIn("!GIT_SOURCES.items.length && !GIT_SOURCES.adoptTried",
                      self.dashboard,
                      "自动接管必须限定在登记表为空时")
        # 接管成功后必须重载，否则界面停在空态、用户仍看不到源。而重载前
        # 必须先解锁 loading —— 否则 loadGitSources() 会因自身防重入直接返回，
        # 表现为「接管了但列表还是空的」。断言必须精确到这两行的相邻关系：
        # 只查 `GIT_SOURCES.loading = false;` 会命中 finally 里的同一句而恒真。
        self.assertIn(
            "GIT_SOURCES.autoAdopted = d;\n      GIT_SOURCES.loading = false;",
            self.dashboard,
            "接管成功后必须先解锁 loading 再重载，否则重载被自己挡住",
        )

    def test_cli_flag_and_rust_whitelist(self):
        self.assertIn('"--adopt-git-source"', self.scan, "scan.py 缺少参数定义")
        self.assertIn('"--adopt-git-source"', self.lib_rs,
                      "Rust run_cli 白名单缺少 --adopt-git-source（GUI 调用会被拒）")

    def test_design_spec_registers_the_behavior(self):
        self.assertIn("自动接管", self.design,
                      "docs/DESIGN.md 未登记自动接管行为")


if __name__ == "__main__":
    unittest.main()
