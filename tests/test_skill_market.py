"""FEAT-9: 技能市场访问层（只读）契约测试。"""

import json as _json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_market import detect_backend, list_installed, read_sources  # noqa: E402


class DetectBackendTest(unittest.TestCase):
    def test_returns_dict_with_expected_keys(self):
        info = detect_backend()
        for key in ("available", "npx_path", "version", "reason"):
            self.assertIn(key, info)

    def test_missing_npx_degrades_without_raising(self):
        """后端缺失必须降级为 available=False，不得抛异常。"""
        with mock.patch("skill_market.shutil.which", return_value=None):
            info = detect_backend()
        self.assertFalse(info["available"])
        self.assertIsNone(info["npx_path"])
        self.assertTrue(info["reason"])


class ReadSourcesTest(unittest.TestCase):
    def test_three_sources_always_present(self):
        """三个源恒在清单中，缺失的标 unavailable 而非省略。"""
        srcs = read_sources()
        self.assertEqual(set(srcs["sources"]), {"skills.sh", "qwenwork", "enterprise"})

    def test_unavailable_sources_carry_reason(self):
        srcs = read_sources()
        for s in srcs["sources"].values():
            if not s["available"]:
                self.assertTrue(s["reason"], f"{s['id']} 不可用但未给原因")


class ListInstalledTest(unittest.TestCase):
    def _lock(self, tmp, payload):
        p = Path(tmp) / ".skill-lock.json"
        p.write_text(_json.dumps(payload), encoding="utf-8")
        return p

    def test_reads_source_fields_from_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = self._lock(tmp, {
                "version": 3,
                "skills": {
                    "find-skills": {
                        "source": "vercel-labs/skills",
                        "sourceType": "github",
                        "sourceUrl": "https://github.com/vercel-labs/skills.git",
                        "skillPath": "skills/find-skills/SKILL.md",
                        "skillFolderHash": "",
                        "installedAt": "2026-01-27T03:25:42.413Z",
                        "updatedAt": "2026-03-03T06:09:35.044Z",
                    }
                },
            })
            out = list_installed(lock_path=lock, skills_dir=Path(tmp) / "no-skills")
        row = next(r for r in out["installed"] if r["name"] == "find-skills")
        self.assertEqual(row["source"], "vercel-labs/skills")
        self.assertEqual(row["source_url"], "https://github.com/vercel-labs/skills.git")
        self.assertEqual(row["skill_path"], "skills/find-skills/SKILL.md")
        self.assertEqual(row["updated_at"], "2026-03-03T06:09:35.044Z")

    def test_empty_folder_hash_is_not_treated_as_version(self):
        """skillFolderHash 恒为空，不得据此判断版本。"""
        with tempfile.TemporaryDirectory() as tmp:
            lock = self._lock(tmp, {
                "version": 3,
                "skills": {"x": {"source": "a/b", "skillFolderHash": ""}},
            })
            out = list_installed(lock_path=lock, skills_dir=Path(tmp) / "no-skills")
        row = next(r for r in out["installed"] if r["name"] == "x")
        self.assertIsNone(row["folder_hash"])

    def test_missing_lock_degrades(self):
        """lock 与技能目录都不存在时降级为空清单，并给出原因。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = list_installed(
                lock_path=Path(tmp) / "nope.json",
                skills_dir=Path(tmp) / "no-skills",
            )
        self.assertEqual(out["installed"], [])
        self.assertTrue(out["reason"])

    def test_hidden_dirs_are_not_skills(self):
        """技能库根有 .git，它不是技能，不得进入清单。"""
        with tempfile.TemporaryDirectory() as tmp:
            skills = Path(tmp) / "skills"
            (skills / ".git").mkdir(parents=True)
            (skills / "real-skill").mkdir()
            lock = self._lock(tmp, {"version": 3, "skills": {}})
            out = list_installed(lock_path=lock, skills_dir=skills)
        names = [r["name"] for r in out["installed"]]
        self.assertEqual(names, ["real-skill"])


if __name__ == "__main__":
    unittest.main()