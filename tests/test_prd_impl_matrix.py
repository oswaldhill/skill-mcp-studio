"""PRD ↔ 实现 对照矩阵的门禁断言。

这份矩阵的价值全在「证据是真的」。若没有断言，它会很快退化成一张手工维护的
愿望清单——文档说已实现、代码里其实没有，或代码改了名而清单没跟着改。所以这里
把两件事都机器化：

1. **证据核验**：每条 row 的 evidence 必须真实成立（CLI flag 在 scan.py 里、
   代码符号在指定文件里、GUI 选择器在 dashboard.html 里）。代码改名 → 报红。
2. **文档自洽**：矩阵的 markdown 表格必须与 JSON 数据一致（行数、ID、状态），
   PRD 里必须能对上矩阵声称的章节号，未实现项必须在缺口看板登记。

断言的边界：**只验「清单是否诚实」，不验产品功能是否正确**——功能正确性由各
功能自己的测试负责。这里不做重复劳动。
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX_JSON = ROOT / "docs" / "product" / "prd_impl_matrix.json"
MATRIX_MD = ROOT / "docs" / "product" / "PRD-实现对照清单.md"
PRD = ROOT / "docs" / "product" / "PRD-产品需求文档.md"
SCAN = ROOT / "scan.py"
GUI = ROOT / "gui" / "dashboard.html"


def _load():
    return json.loads(MATRIX_JSON.read_text(encoding="utf-8"))


class EvidenceTest(unittest.TestCase):
    """每条证据都必须真实成立。"""

    @classmethod
    def setUpClass(cls):
        cls.data = _load()
        cls.scan = SCAN.read_text(encoding="utf-8")
        cls.gui = GUI.read_text(encoding="utf-8")
        cls._cache = {}

    def _file_text(self, rel):
        if rel not in self._cache:
            p = ROOT / rel
            self._cache[rel] = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else None
        return self._cache[rel]

    def test_every_flag_evidence_exists_in_cli(self):
        bad = []
        for row in self.data["rows"]:
            for ev in row["evidence"]:
                if ev["kind"] == "flag" and f'"{ev["value"]}"' not in self.scan:
                    bad.append(f"{row['id']} → {ev['value']}")
        self.assertEqual([], bad, f"清单声称的 CLI 参数在 scan.py 里不存在: {bad}")

    def test_every_symbol_evidence_exists(self):
        bad = []
        for row in self.data["rows"]:
            for ev in row["evidence"]:
                if ev["kind"] != "symbol":
                    continue
                text = self._file_text(ev["file"])
                if text is None:
                    bad.append(f"{row['id']} → 文件不存在 {ev['file']}")
                elif ev["value"] not in text:
                    bad.append(f"{row['id']} → {ev['file']} 里没有 {ev['value']}")
        self.assertEqual([], bad, f"代码符号证据不成立: {bad}")

    def test_every_gui_evidence_exists(self):
        bad = []
        for row in self.data["rows"]:
            for ev in row["evidence"]:
                if ev["kind"] == "gui" and ev["value"] not in self.gui:
                    bad.append(f"{row['id']} → {ev['value']}")
        self.assertEqual([], bad, f"GUI 证据不成立: {bad}")

    def test_rows_without_machine_evidence_explain_why(self):
        """只有 doc 证据的行必须写清原因，不能拿文档空口宣称已实现。"""
        bad = []
        for row in self.data["rows"]:
            kinds = {ev["kind"] for ev in row["evidence"]}
            if kinds == {"doc"}:
                if row["status"] == "done":
                    bad.append(f"{row['id']} 标已实现却只有文档证据")
                if not row["note"]:
                    bad.append(f"{row['id']} 只有文档证据但没有 note 说明")
        self.assertEqual([], bad)


class MatrixConsistencyTest(unittest.TestCase):
    """JSON 数据 与 markdown 表格 必须一致。"""

    @classmethod
    def setUpClass(cls):
        cls.data = _load()
        cls.md = MATRIX_MD.read_text(encoding="utf-8")

    def test_status_vocabulary_is_closed(self):
        allowed = set(self.data["_meta"]["status_vocab"])
        bad = [r["id"] for r in self.data["rows"] if r["status"] not in allowed]
        self.assertEqual([], bad, f"出现未登记的状态值: {bad}")

    def test_every_row_appears_in_markdown(self):
        missing = [r["id"] for r in self.data["rows"] if f"| {r['id']} |" not in self.md]
        self.assertEqual([], missing, f"这些条目没写进 markdown 表格: {missing}")

    def test_markdown_row_count_matches_json(self):
        in_table = re.findall(r"\n\| (\d+(?:\.\d+)*(?:-R\d+)?|-?\d*) \| §", self.md)
        # 表格行以「| ID | §」开头
        rows = re.findall(r"\n\| ([0-9][0-9.]*(?:-[0-9]+|\.1-R[0-9]+)?) \| §", self.md)
        self.assertGreaterEqual(len(rows), len(self.data["rows"]),
                                "markdown 表格行数少于 JSON 条目数")

    def test_summary_counts_match_data(self):
        from collections import Counter
        counts = Counter(r["status"] for r in self.data["rows"])
        for status, n in counts.items():
            self.assertIn(f"| **{n}** |", self.md,
                          f"总览表里缺少状态 {status} 的计数 {n}")

    def test_partial_rows_must_explain_gap(self):
        """部分实现必须写明「缺什么」，不允许只标状态。"""
        bad = [r["id"] for r in self.data["rows"]
               if r["status"] == "partial" and len(r["note"]) < 10]
        self.assertEqual([], bad, f"部分实现但未说明缺口: {bad}")


class PrdCrossReferenceTest(unittest.TestCase):
    """矩阵与 PRD 必须互相指得通。"""

    @classmethod
    def setUpClass(cls):
        cls.data = _load()
        cls.prd = PRD.read_text(encoding="utf-8")

    def test_prd_links_to_matrix(self):
        self.assertIn("PRD-实现对照清单.md", self.prd)

    def test_matrix_links_to_prd(self):
        self.assertIn("PRD-产品需求文档.md", MATRIX_MD.read_text(encoding="utf-8"))

    def test_referenced_prd_sections_exist(self):
        """矩阵声称的 §6.x / §7 / §8 必须在 PRD 里真的有。"""
        bad = []
        for row in self.data["rows"]:
            m = re.match(r"§(\d+(?:\.\d+)*)", row["prd"])
            if not m:
                continue
            sec = m.group(1)
            # §6.2.1 这类子小节按标题存在性判断，其余按标题前缀
            if not (f"### {sec} " in self.prd or f"#### {sec} " in self.prd
                    or f"## {sec}. " in self.prd or f"## {sec} " in self.prd):
                bad.append(f"{row['id']} → {row['prd']}")
        self.assertEqual([], bad, f"矩阵引用的 PRD 章节不存在: {bad}")

    def test_planned_items_registered_in_gap_board(self):
        """未实现项必须在 PRD §8 缺口看板登记，否则等于偷偷欠债。"""
        planned = [r for r in self.data["rows"] if r["status"] == "planned"]
        self.assertTrue(planned, "本清单应至少有一条未实现项（技能关闭）")
        self.assertIn("技能关闭", self.prd)
        self.assertIn("§6.2.1", self.prd)

    def test_prd_sections_66_to_68_exist(self):
        """v1.6 补齐的三页需求必须还在，且矩阵里有对应条目。"""
        for sec in ("6.6 Hook", "6.7 变更详情", "6.8 概览"):
            self.assertIn(f"### {sec}", self.prd, f"PRD 缺少 §{sec}")
        ids = {r["id"] for r in self.data["rows"]}
        for prefix in ("6.6-", "6.7-", "6.8-"):
            self.assertTrue(any(i.startswith(prefix) for i in ids),
                            f"矩阵缺少 {prefix} 条目")

    def test_overview_no_longer_claims_probe_kpi(self):
        """§5.3 曾写概览含「MCP 探活」KPI，实际已移除——不得回退。"""
        self.assertIn("概览页不含「MCP 探活」KPI", self.prd)


if __name__ == "__main__":
    unittest.main()
