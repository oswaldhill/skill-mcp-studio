"""验收：技能库根目录下的保留目录（``_backup`` / ``_trash``）不得被当成技能。

为什么需要这组用例：这两个目录是 ``skill_ops`` 的**操作落地目录** ——
``_backup/`` 存技能备份副本（导出还会产生同名 ``.zip``），``_trash/`` 存软删除
后的目录。它们内部带着 ``SKILL.md``（备份的是真实技能），所以凡是「是不是目录 /
有没有 SKILL.md」这类筛选都会把它们漏进来：实测修复前 ``_backup``、``_trash``
出现在 209 个技能清单里，各自的 4 个备份副本还被算成嵌套技能。

反向验证：把 5 处枚举点的 ``is_reserved_skill_dir`` 判据去掉，本文件的
``ReservedDirsExcludedTest`` 会立即失败 —— 说明用例真的钉在缺陷上。

同时钉住**不误伤**：``_core`` 名字同样以下划线开头，但它是真实技能（带规范前言的
``SKILL.md``），必须保留。这条正是「用精确名单而不是下划线前缀」的判据。
"""

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import paths  # noqa: E402
import skill_market  # noqa: E402
import skills_analyser  # noqa: E402


def _make_skill(root: Path, name: str, description: str = "test skill") -> Path:
    """在 ``root`` 下造一个最小可用技能目录（含带前言的 SKILL.md）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return d


class ReservedDirPredicateTest(unittest.TestCase):
    """判据本身：精确名单，且不靠下划线前缀这类宽规则。"""

    def test_backup_and_trash_are_reserved(self):
        self.assertTrue(paths.is_reserved_skill_dir("_backup"))
        self.assertTrue(paths.is_reserved_skill_dir("_trash"))

    def test_real_skill_with_underscore_prefix_is_not_reserved(self):
        # _core 是真实技能，不能因为下划线开头就被排除
        self.assertFalse(paths.is_reserved_skill_dir("_core"))

    def test_ordinary_names_are_not_reserved(self):
        for name in ("grafana", "lark-doc", "pdf", "skills-mcp-unifier", ""):
            with self.subTest(name=name):
                self.assertFalse(paths.is_reserved_skill_dir(name))

    def test_predicate_is_pure_name_lookup(self):
        # 只判名字、不碰文件系统：不存在的名字也照样按名单返回
        self.assertFalse(paths.is_reserved_skill_dir("_backup_missing"))


class ReservedDirsExcludedTest(unittest.TestCase):
    """端到端：在真实目录结构上枚举，保留目录必须消失、真实技能必须留下。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self):
        """造一棵与真实技能库同形的树：技能 + _backup + _trash + _core。

        ``_backup``/``_trash`` 里放带 SKILL.md 的副本 —— 这正是它们会被误判成
        技能的原因，也是必须复现的触发条件。
        """
        _make_skill(self.root, "grafana")
        _make_skill(self.root, "lark-doc")
        # _core：真实技能，下划线开头但必须保留
        _make_skill(self.root, "_core", "Core conventions and standards")
        # 备份副本（模仿 <name>-<ts> 命名）
        _make_skill(self.root / "_backup", "grafana-20260924-163842-278955")
        _make_skill(self.root / "_backup", "ima-skill-20260924-163842-281037")
        # 回收站副本
        _make_skill(self.root / "_trash", "grafana-20260924-163842-279008")

    def test_scan_skills_distribution_excludes_reserved(self):
        self._seed()
        result = skills_analyser.scan_skills_distribution(str(self.root))
        subdirs = result.get("subdirectories") or []
        self.assertIn("grafana", subdirs)
        self.assertIn("lark-doc", subdirs)
        self.assertIn("_core", subdirs)          # 真实技能保留
        self.assertNotIn("_backup", subdirs)     # 保留目录排除
        self.assertNotIn("_trash", subdirs)

    def test_missing_skill_md_scan_excludes_reserved(self):
        # 保留目录若缺 SKILL.md 也不该被算进「缺前言」清单
        self._seed()
        (self.root / "_backup").mkdir(exist_ok=True)
        missing = skills_analyser.find_skills_without_skillmd(str(self.root))
        self.assertNotIn("_backup", missing)
        self.assertNotIn("_trash", missing)

    def test_market_hash_set_excludes_reserved(self):
        """技能市场的实体目录扫描同样不得把保留目录算成已装技能。"""
        self._seed()
        lock_path = self.root / "_test_lock.json"
        lock_path.write_text('{"skills": {}}', encoding="utf-8")
        result = skill_market.list_installed(lock_path=lock_path, skills_dir=self.root)
        # 返回结构为 {"installed": [...]}；容错兼容直接给 list 的实现
        entries = result.get("installed") if isinstance(result, dict) else result
        names = {i.get("name") for i in (entries or [])}
        self.assertIn("grafana", names)
        self.assertIn("_core", names)
        self.assertNotIn("_backup", names)
        self.assertNotIn("_trash", names)

    def test_nested_scan_excludes_reserved(self):
        """嵌套技能枚举（按目录折叠）同样不得暴露备份副本。

        注意 ``scan_skill_nesting`` 只收录**确实含嵌套技能**的目录，所以这里为
        备份副本再造一层子技能 —— 否则即使判据没生效，空结果也会让用例假通过。
        """
        import skill_state

        self._seed()
        # 在备份副本里再放一层嵌套技能，制造「若判据失效就会暴露」的条件
        _make_skill(self.root / "_backup" / "grafana-20260924-163842-278955" / "nested-thing", "deep")
        _make_skill(self.root / "_trash" / "grafana-20260924-163842-279008" / "nested-thing", "deep2")

        nested = skill_state.scan_skill_nesting(str(self.root))
        self.assertNotIn("_backup", nested)
        self.assertNotIn("_trash", nested)
        # 作为对照：真实技能带嵌套项时**应当**出现
        _make_skill(self.root / "grafana" / "sub-skill", "sub")
        nested2 = skill_state.scan_skill_nesting(str(self.root))
        self.assertIn("grafana", nested2)
        self.assertNotIn("_backup", nested2)
        self.assertNotIn("_trash", nested2)


class RealRepoShapeTest(unittest.TestCase):
    """对真实技能库（若存在）做一次只读检查：保留目录不得出现在清单里。"""

    def test_live_skills_dir_has_no_reserved_entries(self):
        real = paths.skills_dir()
        if not real.is_dir():
            self.skipTest("本机无技能库，跳过")
        result = skills_analyser.scan_skills_distribution(str(real))
        subdirs = set(result.get("subdirectories") or [])
        if "_backup" not in subdirs and "_trash" not in subdirs:
            # 目录不存在时也算通过：判据的意义是「存在也不出现」
            pass
        self.assertNotIn("_backup", subdirs)
        self.assertNotIn("_trash", subdirs)


if __name__ == "__main__":
    unittest.main()