"""市场源模型契约（v0.31.0 #4 前半，设计 2026-10-22 §2/§7）。

守住：默认回落（文件不存在/空/坏）/ CRUD upsert / 未知 type 拒绝 /
删默认源允许 / 备份真实生成。全部 tmp 隔离（不碰仓库真实
data/market_sources.yaml）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from market_sources import (  # noqa: E402
    DEFAULT_SOURCES,
    list_sources,
    remove_source,
    set_source,
)


class ListSourcesTest(unittest.TestCase):
    """读：默认回落 / 坏条目跳过 / 空文件回落。"""

    def test_missing_file_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as td:
            src, fallback, invalid = list_sources(os.path.join(td, "nope.yaml"))
            self.assertTrue(fallback)
            self.assertEqual([s["id"] for s in src], ["skills-sh"])
            self.assertEqual(invalid, [])

    def test_empty_file_means_explicitly_cleared(self):
        """空列表文件 = 用户明确清空（删光默认源后的合法状态），不回落默认。"""
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            Path(p).write_text("[]\n", encoding="utf-8")
            src, fallback, _ = list_sources(p)
            self.assertFalse(fallback)
            self.assertEqual(src, [])

    def test_invalid_entries_skipped_with_reason(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            Path(p).write_text(
                "- id: good\n  label: g\n  type: skills-sh\n"
                "- id: bad\n  label: b\n  type: nonsense\n"
                "- id: norepo\n  label: n\n  type: github-repo\n",  # 缺 url
                encoding="utf-8",
            )
            src, fallback, invalid = list_sources(p)
            self.assertFalse(fallback)
            self.assertEqual([s["id"] for s in src], ["good"])
            self.assertEqual({i["id"] for i in invalid}, {"bad", "norepo"})


class SetSourceTest(unittest.TestCase):
    """upsert：新增 / 更新 / 校验拒绝 / 备份。"""

    def test_add_then_update_same_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            r1 = set_source("my-hub", label="Hub", stype="github-repo",
                            url="https://github.com/o/r", path=p)
            self.assertEqual(r1["status"], "ok")
            self.assertEqual(r1["action"], "added")
            r2 = set_source("my-hub", label="Hub2", stype="github-repo",
                            url="https://github.com/o/r2", path=p)
            self.assertEqual(r2["action"], "updated")
            src, _fb, _inv = list_sources(p)
            # 首次配置会把默认源 skills-sh 一并固化（默认源应在列表里）
            self.assertEqual({s["id"] for s in src}, {"skills-sh", "my-hub"})
            hub = next(s for s in src if s["id"] == "my-hub")
            self.assertEqual(hub["label"], "Hub2")
            self.assertEqual(hub["url"], "https://github.com/o/r2")

    def test_unknown_type_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            with self.assertRaises(ValueError):
                set_source("x", label="x", stype="gitlab", path=p)

    def test_github_repo_requires_url(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            with self.assertRaises(ValueError):
                set_source("x", label="x", stype="github-repo", path=p)

    def test_update_existing_file_creates_backup(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            set_source("a", label="a", stype="skills-sh", path=p)
            r = set_source("a", label="a2", stype="skills-sh", path=p)
            self.assertTrue(r["backup"])
            self.assertTrue(os.path.isfile(r["backup"]), "备份未真实生成")


class RemoveSourceTest(unittest.TestCase):
    """删：默认源允许删 / 不存在 unchanged / 删空提示。"""

    def test_remove_default_source_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            set_source("skills-sh", label="s", stype="skills-sh", path=p)
            r = remove_source("skills-sh", path=p)
            self.assertEqual(r["status"], "ok")
            self.assertIn("已无可用市场源", r["message"])
            src, _fb, _inv = list_sources(p)
            self.assertEqual(src, [])

    def test_remove_nonexistent_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "market_sources.yaml")
            r = remove_source("ghost", path=p)
            self.assertEqual(r["status"], "unchanged")

    def test_default_sources_constant_shape(self):
        """内置默认源形态锁定（id/label/type/enabled 四字段）。"""
        for s in DEFAULT_SOURCES:
            self.assertIn("id", s)
            self.assertIn("label", s)
            self.assertIn("type", s)
            self.assertIn("enabled", s)


if __name__ == "__main__":
    unittest.main()
