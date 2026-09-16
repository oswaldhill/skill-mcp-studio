"""skill_ops：备份 / 导出 / 元数据重命名 / 软删除 的单元测试。"""

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_ops import (  # noqa: E402
    backup_skill,
    export_skill,
    rename_skill_meta,
    soft_delete_skill,
)


def _make_skill(repo: Path, name: str, frontmatter: str = "") -> None:
    d = repo / name
    d.mkdir()
    (d / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    if not frontmatter:
        (d / "SKILL.md").write_text("---\nname: %s\n---\n\n# %s\n" % (name, name), encoding="utf-8")


class BackupSkillTest(unittest.TestCase):
    def test_copies_dir_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha")
            r = backup_skill(str(repo), "alpha")
            self.assertEqual(r["status"], "ok")
            self.assertTrue((Path(r["backup"]) / "SKILL.md").exists())

    def test_missing_skill_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = backup_skill(tmp, "nope")
            self.assertEqual(r["status"], "error")

    def test_dry_run_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha")
            r = backup_skill(str(repo), "alpha", dry_run=True)
            self.assertEqual(r["status"], "dry-run")
            self.assertFalse(Path(r["backup"]).exists())

    def test_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = backup_skill(tmp, "../etc")
            self.assertEqual(r["status"], "error")


class ExportSkillTest(unittest.TestCase):
    def test_creates_zip_with_top_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha")
            r = export_skill(str(repo), "alpha")
            self.assertEqual(r["status"], "ok")
            with zipfile.ZipFile(r["path"]) as zf:
                names = zf.namelist()
            self.assertIn("alpha/SKILL.md", names)

    def test_dry_run_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha")
            r = export_skill(str(repo), "alpha", dry_run=True)
            self.assertEqual(r["status"], "dry-run")
            self.assertFalse(Path(r["path"]).exists())


class RenameSkillMetaTest(unittest.TestCase):
    def test_renames_name_and_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha", "---\nname: alpha\ndescription: Old\n---\n\n# Body\n")
            r = rename_skill_meta(str(repo), "alpha", new_name="AlphaPlus", new_description="New desc")
            self.assertEqual(r["status"], "ok")
            body = (repo / "alpha" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("name: AlphaPlus", body)
            self.assertIn("description: New desc", body)
            self.assertIn("# Body", body)  # body preserved

    def test_title_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "apple").mkdir()
            (repo / "apple" / "SKILL.md").write_text(
                "---\ntitle: \"apple\"\nsummary: S\n---\n\n# apple\n", encoding="utf-8"
            )
            r = rename_skill_meta(str(repo), "apple", new_name="Apple 平台")
            self.assertEqual(r["status"], "ok")
            body = (repo / "apple" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Apple 平台", body)

    def test_requires_some_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha")
            r = rename_skill_meta(str(repo), "alpha")
            self.assertEqual(r["status"], "error")


class SoftDeleteSkillTest(unittest.TestCase):
    def test_backup_then_move_to_trash(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha")
            r = soft_delete_skill(str(repo), "alpha")
            self.assertEqual(r["status"], "ok")
            self.assertFalse((repo / "alpha").exists())
            self.assertTrue((Path(r["backup"]) / "SKILL.md").exists())
            self.assertTrue((Path(r["path"]) / "SKILL.md").exists())
            # 备份在 _backup、回收在 _trash
            self.assertIn("_backup", r["backup"])
            self.assertIn("_trash", r["path"])

    def test_dry_run_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _make_skill(repo, "alpha")
            r = soft_delete_skill(str(repo), "alpha", dry_run=True)
            self.assertEqual(r["status"], "dry-run")
            self.assertTrue((repo / "alpha").exists())


if __name__ == "__main__":
    unittest.main()