"""技能来源（provenance）：按仓库分组展示已安装技能（2026-11-15）。

用户需求（1/2/3）：
  1. 安装弹窗里标出哪些已安装  ← 已完成
  2. 已安装技能在 Skills 主页可见
  3. 按来源仓库分组展示，便于统一管理与卸载

数据源是 `npx skills` 自己的 lock（`~/.agents/.skill-lock.json`），它记录了
source / sourceUrl / installedAt；不自造第二份来源表，避免两边漂移。
"""

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "core"))

from skill_provenance import (  # noqa: E402
    group_by_source,
    read_skills,
    summarize,
)

LOCK_SAMPLE = {
    "version": 1,
    "skills": {
        "research": {
            "source": "mattpocock/skills",
            "sourceType": "github",
            "sourceUrl": "https://github.com/mattpocock/skills.git",
            "installedAt": "2026-11-15T10:00:00.000Z",
            "updatedAt": "2026-11-15T10:00:00.000Z",
        },
        "wayfinder": {
            "source": "mattpocock/skills",
            "sourceType": "github",
            "sourceUrl": "https://github.com/mattpocock/skills.git",
            "installedAt": "2026-11-15T10:10:00.000Z",
            "updatedAt": "2026-11-15T10:10:00.000Z",
        },
        "figma": {
            "source": "nextlevelbuilder/ui-ux-pro-max-skill",
            "sourceType": "github",
            "sourceUrl": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git",
            "installedAt": "2026-02-21T12:00:00.000Z",
            "updatedAt": "2026-11-08T12:00:00.000Z",
        },
    },
}


class ReadTest(unittest.TestCase):
    def _write(self, tmp, payload):
        p = Path(tmp) / ".skill-lock.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_reads_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, LOCK_SAMPLE)
            rows = read_skills(lock_path=p)
        self.assertEqual(len(rows), 3)
        by = {r["name"]: r for r in rows}
        self.assertEqual(by["research"]["source"], "mattpocock/skills")
        self.assertEqual(by["research"]["source_url"],
                         "https://github.com/mattpocock/skills.git")

    def test_missing_lock_returns_empty(self):
        rows = read_skills(lock_path=Path("/nonexistent/xx/.skill-lock.json"))
        self.assertEqual(rows, [])

    def test_bad_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text("{ not json", encoding="utf-8")
            rows = read_skills(lock_path=p)
        self.assertEqual(rows, [])


class GroupTest(unittest.TestCase):
    def test_groups_by_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "l.json"
            p.write_text(json.dumps(LOCK_SAMPLE), encoding="utf-8")
            rows = read_skills(lock_path=p)
        groups = group_by_source(rows)
        by_src = {g["source"]: g for g in groups}
        self.assertEqual(len(by_src), 2)
        self.assertEqual(len(by_src["mattpocock/skills"]["skills"]), 2)
        self.assertEqual(by_src["mattpocock/skills"]["count"], 2)
        # 组内按安装时间倒序：后装的在前
        self.assertEqual(by_src["mattpocock/skills"]["skills"][0]["name"], "wayfinder")

    def test_groups_sorted_by_count_desc(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "l.json"
            p.write_text(json.dumps(LOCK_SAMPLE), encoding="utf-8")
            rows = read_skills(lock_path=p)
        groups = group_by_source(rows)
        self.assertEqual(groups[0]["source"], "mattpocock/skills")

    def test_unknown_source_bucketed(self):
        rows = [{"name": "x", "source": "", "source_url": "",
                 "installed_at": "", "updated_at": ""}]
        groups = group_by_source(rows)
        self.assertEqual(groups[0]["source"], "(未记录来源)")


class SummarizeTest(unittest.TestCase):
    def test_counts(self):
        rows = [
            {"name": "a", "source": "s1", "source_url": "", "installed_at": "",
             "updated_at": ""},
            {"name": "b", "source": "s1", "source_url": "", "installed_at": "",
             "updated_at": ""},
            {"name": "c", "source": "s2", "source_url": "", "installed_at": "",
             "updated_at": ""},
        ]
        s = summarize(rows)
        self.assertEqual(s["recorded"], 3)
        self.assertEqual(s["sources"], 2)

    def test_reports_unrecorded(self):
        """库里有 164 个技能、lock 只记 47 个时，必须说清缺口而不是假装全覆盖。"""
        rows = [{"name": "a", "source": "s1", "source_url": "",
                 "installed_at": "", "updated_at": ""}]
        s = summarize(rows, installed_total=10)
        self.assertEqual(s["recorded"], 1)
        self.assertEqual(s["unrecorded"], 9)
        self.assertFalse(s["complete"])


class CliTest(unittest.TestCase):
    """CLI 出口 `--skill-provenance`。"""

    ROOT = Path(__file__).resolve().parents[1]

    def _run(self, *args):
        import os
        import subprocess
        import sys as _sys
        env = dict(os.environ)
        return subprocess.run(
            [_sys.executable, str(self.ROOT / "scan.py"), *args],
            capture_output=True, text=True, timeout=180,
            cwd=str(self.ROOT), env=env)

    def test_json_shape(self):
        r = self._run("--skill-provenance", "--format", "json")
        self.assertEqual(r.returncode, 0, r.stderr[:400])
        payload = json.loads(r.stdout)
        self.assertEqual(payload["kind"], "skill-provenance")
        self.assertIn("groups", payload)
        self.assertIn("summary", payload)
        for key in ("recorded", "sources", "unrecorded", "complete"):
            self.assertIn(key, payload["summary"])

    def test_text_output(self):
        r = self._run("--skill-provenance")
        self.assertEqual(r.returncode, 0, r.stderr[:400])
        self.assertIn("来源", r.stdout)
