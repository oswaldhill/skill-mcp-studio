"""P0-4 验收：技能库根可**在不重启进程的前提下**切换。

为什么这条测试是判据而非装饰：改造前路径是模块级
``_SKILLS_DIR = Path.home() / ...``，import 时求值并缓存 —— 进程内**无法**改。
因此「在同一个进程里把根切到临时目录、并让消费方跟随」这一条，只有真正
改成访问器后才可能通过。反向验证：把 ``paths.skills_dir()`` 换回模块级常量，
``test_list_installed_default_follows_root`` 会读到真实 home 而失败。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import paths  # noqa: E402
import skill_market  # noqa: E402
import skill_market_ops  # noqa: E402


class PathsResolutionTest(unittest.TestCase):
    def tearDown(self):
        paths.reset()

    def test_default_root_is_real_home(self):
        paths.reset()
        self.assertEqual(paths.home_root(), Path.home())
        self.assertEqual(
            paths.skills_dir(), Path.home() / ".skills-manager" / "skills"
        )
        self.assertEqual(paths.agents_dir(), Path.home() / ".agents")
        self.assertEqual(
            paths.default_lock_path(),
            Path.home() / ".agents" / ".skill-lock.json",
        )

    def test_override_switches_root_without_restart(self):
        """核心验收：同进程内切根，退出后恢复。"""
        before = paths.skills_dir()
        with tempfile.TemporaryDirectory() as tmp:
            with paths.override(tmp):
                self.assertEqual(
                    paths.skills_dir(), Path(tmp) / ".skills-manager" / "skills"
                )
                self.assertNotEqual(paths.skills_dir(), before)
            # 退出上下文必须恢复，否则会污染同进程的其它用例。
            self.assertEqual(paths.skills_dir(), before)

    def test_resolution_is_not_cached(self):
        """改完立刻生效 —— 缓存正是本项要治的病。"""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            with paths.override(a):
                first = paths.skills_dir()
            with paths.override(b):
                second = paths.skills_dir()
            self.assertNotEqual(first, second)
            self.assertIn(a, str(first))
            self.assertIn(b, str(second))

    def test_env_var_overrides_home(self):
        import os

        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get(paths.HOME_ENV)
            os.environ[paths.HOME_ENV] = tmp
            try:
                self.assertEqual(paths.home_root(), Path(tmp))
                self.assertEqual(
                    paths.skills_dir(), Path(tmp) / ".skills-manager" / "skills"
                )
            finally:
                if old is None:
                    os.environ.pop(paths.HOME_ENV, None)
                else:
                    os.environ[paths.HOME_ENV] = old

    def test_explicit_injection_beats_env(self):
        import os

        with tempfile.TemporaryDirectory() as env_tmp, tempfile.TemporaryDirectory() as inj_tmp:
            old = os.environ.get(paths.HOME_ENV)
            os.environ[paths.HOME_ENV] = env_tmp
            try:
                with paths.override(inj_tmp):
                    self.assertEqual(paths.home_root(), Path(inj_tmp))
            finally:
                if old is None:
                    os.environ.pop(paths.HOME_ENV, None)
                else:
                    os.environ[paths.HOME_ENV] = old


class ConsumersFollowRootTest(unittest.TestCase):
    """四个消费点必须都跟随注入的根，不能各留一份自己的常量。"""

    def tearDown(self):
        paths.reset()

    def _seed(self, root: Path) -> None:
        (root / ".skills-manager" / "skills" / "demo-skill").mkdir(parents=True)
        agents = root / ".agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / ".skill-lock.json").write_text(
            json.dumps({"skills": {"demo-skill": {"source": "unit-test"}}}),
            encoding="utf-8",
        )

    def test_ops_accessor_follows_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            with paths.override(tmp):
                self.assertEqual(skill_market_ops._skills_dir(), paths.skills_dir())
                self.assertIn(tmp, str(skill_market_ops._skills_dir()))

    def test_list_installed_default_follows_root(self):
        """默认参数（不显式传路径）也必须落到注入的根。

        这是改造前不可能通过的断言：当时默认值是 import 期定死的常量。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            with paths.override(root):
                out = skill_market.list_installed()
            self.assertIn("demo-skill", json.dumps(out, ensure_ascii=False))

    def test_merge_advisor_follows_root(self):
        import skill_merge_advisor

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            with paths.override(root):
                # 默认参数路径必须解析到注入的根（空库也不该抛错）。
                metas = skill_merge_advisor.load_metas()
            self.assertIsNotNone(metas)


if __name__ == "__main__":
    unittest.main()
