import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from fixer import fix_all, fix_path  # noqa: E402


class SkillsFixerTest(unittest.TestCase):
    def test_missing_path_is_created_only_for_installed_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            unified = root / "unified"
            unified.mkdir()
            installed_path = root / "installed" / "skills"
            absent_path = root / "absent" / "skills"
            scan = {
                "results": [
                    {
                        "path": str(installed_path),
                        "expanded_path": str(installed_path),
                        "unified_dir": str(unified),
                        "status": "missing",
                        "is_installed": True,
                    },
                    {
                        "path": str(absent_path),
                        "expanded_path": str(absent_path),
                        "unified_dir": str(unified),
                        "status": "missing",
                        "is_installed": False,
                    },
                ]
            }

            result = fix_all(scan)

            self.assertEqual(result["total"], 1)
            self.assertTrue(installed_path.is_symlink())
            self.assertEqual(installed_path.resolve(), unified.resolve())
            self.assertFalse(os.path.lexists(absent_path))

    def test_real_directory_is_restored_when_symlink_creation_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            unified = root / "unified"
            unified.mkdir()
            path = root / "client" / "skills"
            path.mkdir(parents=True)
            marker = path / "local-skill.txt"
            marker.write_text("preserve", encoding="utf-8")
            row = {
                "path": str(path),
                "expanded_path": str(path),
                "unified_dir": str(unified),
                "status": "real_dir",
                "is_installed": True,
            }

            with patch("fixer.os.symlink", side_effect=OSError("link failed")):
                result = fix_path(row)

            self.assertFalse(result["fixed"])
            self.assertIn("原目录已自动恢复", result["error"])
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_wrong_link_is_restored_when_replacement_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            unified = root / "unified"
            old_target = root / "old"
            unified.mkdir()
            old_target.mkdir()
            path = root / "client" / "skills"
            path.parent.mkdir()
            path.symlink_to(old_target)
            row = {
                "path": str(path),
                "expanded_path": str(path),
                "unified_dir": str(unified),
                "status": "wrong_link",
                "is_installed": True,
            }
            real_symlink = os.symlink
            calls = 0

            def fail_once(target, link_name):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("link failed")
                return real_symlink(target, link_name)

            with patch("fixer.os.symlink", side_effect=fail_once):
                result = fix_path(row)

            self.assertFalse(result["fixed"])
            self.assertIn("原符号链接已自动恢复", result["error"])
            self.assertEqual(path.resolve(), old_target.resolve())

    def test_broken_symlink_parent_reports_clear_error(self):
        """父目录是失效符号链接（如 ~/.vscode 指向未挂载磁盘）时，应给出
        明确的「失效符号链接」提示，而非底层 FileExistsError。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            unified = root / "unified"
            unified.mkdir()
            # 失效符号链接父目录：指向不存在的目标
            broken_parent = root / "vscode"
            broken_parent.symlink_to(root / "no-such-volume")
            skills = broken_parent / "skills"
            row = {
                "path": str(skills),
                "expanded_path": str(skills),
                "unified_dir": str(unified),
                "status": "missing",
                "is_installed": True,
            }
            result = fix_path(row)
            self.assertFalse(result["fixed"])
            self.assertIn("失效符号链接", result["error"])
            # 原失效符号链接的父目录不能被破坏
            self.assertTrue(broken_parent.is_symlink())


if __name__ == "__main__":
    unittest.main()
