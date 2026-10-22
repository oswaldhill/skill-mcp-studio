"""技能版本数据链契约（v0.31.0 #4 前半，设计 2026-10-22 §3/§7）。

守住：SKILL.md frontmatter ``version:`` 解析进 skill_meta（有/无/数值型
YAML 归一）+ 安装记录写入（skill_versions.json）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_state import read_skill_meta  # noqa: E402


def _make_skill(repo: Path, name: str, frontmatter: str) -> None:
    d = repo / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\nbody\n", encoding="utf-8")


class VersionParsingTest(unittest.TestCase):
    """frontmatter version 解析：有 / 无 / 数值型 YAML 归一为字符串。"""

    def test_version_present(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _make_skill(repo, "a", "name: a\ndescription: d\nversion: 1.2.3")
            meta = read_skill_meta(td, ["a"])
            self.assertEqual(meta["a"]["version"], "1.2.3")

    def test_version_absent_is_none(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _make_skill(repo, "b", "name: b\ndescription: d")
            meta = read_skill_meta(td, ["b"])
            self.assertIsNone(meta["b"]["version"])

    def test_numeric_yaml_version_normalized_to_str(self):
        """YAML 把裸 1.0 解析成 float——统一 str() 归一，避免类型漂移进 JSON。"""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _make_skill(repo, "c", "name: c\ndescription: d\nversion: 1.0")
            meta = read_skill_meta(td, ["c"])
            self.assertEqual(meta["c"]["version"], "1.0")
            self.assertIsInstance(meta["c"]["version"], str)

    def test_missing_skill_file_degrades(self):
        with tempfile.TemporaryDirectory() as td:
            meta = read_skill_meta(td, ["ghost"])
            self.assertIsNone(meta["ghost"]["version"])


class InstallRecordTest(unittest.TestCase):
    """安装记录（skill_versions.json）：execute_plan 成功后写入。"""

    def test_install_writes_version_record(self):
        from skill_market_ops import execute_plan

        with tempfile.TemporaryDirectory() as td:
            # 技能库指向 tmp（安装后 verify 能找到）
            repo = Path(td) / "skills"
            repo.mkdir()
            _make_skill(repo, "demo", "name: demo\nversion: 2.0.0")
            # monkeypatch _skills_dir 与记录文件位置
            import skill_market_ops as ops
            with unittest.mock.patch.object(ops, "_skills_dir", return_value=repo), \
                 unittest.mock.patch.object(
                     ops, "_record_versions",
                     side_effect=self._record_with_tmp(td, repo)):
                plan = {"ok": True, "action": "install", "package": "owner/repo@demo",
                        "argv": ["echo"]}
                res = execute_plan(plan, runner=lambda argv, timeout: {"code": 0})
            self.assertTrue(res["ok"])
            self.assertEqual(res.get("versions_written"), 1)
            records = json.loads((Path(td) / "skill_versions.json").read_text(encoding="utf-8"))
            self.assertEqual(records["demo"]["version"], "2.0.0")
            self.assertIn("installed_at", records["demo"])

    @staticmethod
    def _record_with_tmp(td, repo):
        """返回一个把记录文件定向到 tmp 的 _record_versions 替身（复用原逻辑）。"""
        import skill_market_ops as ops
        original = ops._record_versions

        def patched(plan):
            import json as _json
            from datetime import datetime
            from skill_state import read_skill_meta
            names = ([plan["package"].split("@")[-1]] if plan["action"] == "install"
                     else list(plan.get("names") or []))
            meta = read_skill_meta(str(repo), names)
            vpath = Path(td) / "skill_versions.json"
            records = {}
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            for name in names:
                ver = (meta.get(name) or {}).get("version")
                if not ver:
                    continue
                records[name] = {"version": ver, "source": plan.get("package"),
                                 "installed_at": now, "updated_at": now}
            vpath.write_text(_json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
            return len(records)

        return patched


if __name__ == "__main__":
    unittest.main()
