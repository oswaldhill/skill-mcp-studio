"""Well-known 来源的更新检测（2026-11-15 用户需求）。

背景：飞书 `lark-*` 系列来自 `open.feishu.cn/.well-known/skills/`，
不是 GitHub。此前一律落 unknown「无 GitHub 来源信息」，25 个未知里占 22 个。

实测上游 `npx skills update` 自己也把这些归为
「cannot be checked automatically (Well-known skill)」——它不做检测。

但端点本身是公开可读的：
  - `https://<host>/.well-known/skills/index.json` 列出技能与文件清单
  - `https://<host>/.well-known/skills/<name>/SKILL.md` 可直接拉取

**files 清单不可作为判定依据**（实测 lark-doc 本地 44 个文件、远端 index 只报
16 个，远端清单不完整）。判定必须用 SKILL.md 的内容哈希。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_wellknown import (  # noqa: E402
    classify_source,
    compare_skill,
    parse_index,
)


class ClassifyTest(unittest.TestCase):
    def test_wellknown_source_detected(self):
        rec = {
            "source": "open.feishu.cn",
            "sourceType": "well-known",
            "sourceBaseUrl": "https://open.feishu.cn",
        }
        r = classify_source(rec)
        self.assertEqual(r["kind"], "wellknown")
        self.assertEqual(r["base_url"], "https://open.feishu.cn")

    def test_github_source_not_wellknown(self):
        rec = {"source": "vercel-labs/skills", "sourceType": "github"}
        r = classify_source(rec)
        self.assertEqual(r["kind"], "github")

    def test_wellknown_without_base_falls_back_to_source(self):
        rec = {"source": "open.feishu.cn", "sourceType": "well-known"}
        r = classify_source(rec)
        self.assertEqual(r["base_url"], "https://open.feishu.cn")

    def test_unknown_shape_is_other(self):
        r = classify_source({"sourceType": "npm", "source": "x"})
        self.assertEqual(r["kind"], "other")


class ParseIndexTest(unittest.TestCase):
    def test_parses_names(self):
        payload = {"skills": [{"name": "lark-doc", "files": ["SKILL.md"]},
                              {"name": "lark-wiki", "files": ["SKILL.md"]}]}
        got = parse_index(payload)
        self.assertEqual(got, {"lark-doc", "lark-wiki"})

    def test_bad_payload(self):
        self.assertEqual(parse_index({}), set())
        self.assertEqual(parse_index(None), set())
        self.assertEqual(parse_index({"skills": "notalist"}), set())


class CompareTest(unittest.TestCase):
    """远端哈希 vs 本地内容。"""

    def _local(self, tmp, body: bytes) -> Path:
        root = Path(tmp) / "lark-doc"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_bytes(body)
        return root

    def test_identical_is_current(self):
        body = b"---\nname: lark-doc\n---\nhello\n"
        with tempfile.TemporaryDirectory() as tmp:
            local = self._local(tmp, body)
            r = compare_skill("lark-doc", local, fetch=lambda u: body,
                              base_url="https://open.feishu.cn")
        self.assertEqual(r["state"], "current")

    def test_different_is_outdated(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = self._local(tmp, b"old body")
            r = compare_skill("lark-doc", local, fetch=lambda u: b"new body",
                              base_url="https://open.feishu.cn")
        self.assertEqual(r["state"], "outdated")
        self.assertTrue(r["detail"])

    def test_fetch_failure_is_unknown_not_current(self):
        """拉不到远端时必须是 unknown —— 绝不能当「已最新」。"""
        with tempfile.TemporaryDirectory() as tmp:
            local = self._local(tmp, b"body")
            def boom(url):
                raise OSError("network down")
            r = compare_skill("lark-doc", local, fetch=boom,
                              base_url="https://open.feishu.cn")
        self.assertEqual(r["state"], "unknown")
        self.assertIn("失败", r["detail"])

    def test_missing_local_skill_md_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "x"
            root.mkdir()
            r = compare_skill("x", root, fetch=lambda u: b"body")
        self.assertEqual(r["state"], "unknown")

    def test_fetch_none_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = self._local(tmp, b"body")
            r = compare_skill("lark-doc", local, fetch=lambda u: None)
        self.assertEqual(r["state"], "unknown")

    def test_uses_expected_url(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            local = self._local(tmp, b"body")
            compare_skill("lark-doc", local, fetch=lambda u: seen.append(u) or b"body",
                          base_url="https://open.feishu.cn")
        self.assertEqual(seen, ["https://open.feishu.cn/.well-known/skills/lark-doc/SKILL.md"])
