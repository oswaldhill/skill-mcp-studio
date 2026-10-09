"""回归：把「MCP 修复结果」与「变更报告」在语义上分开（2026-10-08 实测事故）。

背景
----
``--fix-mcp`` 的输出顺序是：先逐条打印 MCP 修复结果，紧接着由 Phase 4 打印
``format_change_report(compute_changes(scan_result))``。问题在于后者统计的是
**skills 扫描**维度（工具新增/移除/状态、统计摘要），与 MCP 写入毫无关系 ——
它照例输出「✅ 无变化」，紧跟在 ``updated``/``created`` 之后，极易被读成
「刚才的修复什么都没做」。实测运维时确实这样被误导：配置已经写盘、备份也在，
却被那句「无变化」判成空跑（也正是用户这次报上来的现象之一）。

因此有两处约束需要长期守住：

1. ``format_change_report`` 的标题必须自带适用范围，不能只写「变更报告」；
2. MCP 修复段必须给出**自身**的计数汇总，且 dry-run 下的待写数要取
   ``"dry-run"`` 状态 —— ``fix_mcp_tool`` 在 dry_run 时返回的是 ``"dry-run"``
   （见 ``core/mcp_fixer.py``），若只累加 ``updated``/``created``，真实存在的
   待写项会被算成 0，提示再次失真。
"""

import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from change_tracker import format_change_report  # noqa: E402


class ChangeReportScopeTest(unittest.TestCase):
    """变更报告必须显式声明自己只覆盖 Skills 扫描维度。"""

    def _report(self, has_changes=False, first_run=False):
        return format_change_report({
            "has_changes": has_changes,
            "first_run": first_run,
            "last_scan_time": "2026-10-08 16:50:00",
            "tools_added": [],
            "tools_removed": [],
            "tools_status_changed": [],
            "summary_changes": {},
            "new_count": 0,
            "removed_count": 0,
            "changed_count": 0,
        })

    def test_title_declares_skills_scope(self):
        text = self._report()
        self.assertIn("变更报告（Skills 扫描维度）", text)
        # 反向：不得再出现孤立的「变更报告」标题
        self.assertNotIn('  变更报告\n', text)

    def test_no_change_message_still_present(self):
        """「无变化」本身是正确结论，不能因为改名而丢掉。"""
        self.assertIn("✅ 无变化", self._report())

    def test_first_run_branch_also_scoped(self):
        text = self._report(first_run=True)
        self.assertIn("变更报告（Skills 扫描维度）", text)
        self.assertIn("首次运行", text)


class McpSummaryCountingTest(unittest.TestCase):
    """MCP 修复段的计数汇总：dry-run 与实写两条路径都要取对应状态。"""

    def _summarize(self, statuses, dry_run):
        """复刻 scan.py 中新增的汇总逻辑，锁定计数口径。"""
        counts = Counter(statuses)
        if dry_run:
            written = counts.get("dry-run", 0)
            summary = [f"待写入 {written}"]
        else:
            written = counts.get("updated", 0) + counts.get("created", 0)
            summary = [f"已写入 {written}"]
        for key in ("unchanged", "dry-run", "not-installed", "missing", "unsupported", "error"):
            if counts.get(key):
                summary.append(f"{key} {counts[key]}")
        return f"MCP 修复结果：{'，'.join(summary)}（共 {len(statuses)} 项）"

    def test_dry_run_counts_pending_writes(self):
        """核心回归：dry-run 下待写数必须取 "dry-run"，不能是 0。"""
        text = self._summarize(["dry-run", "dry-run", "unchanged"], dry_run=True)
        self.assertIn("待写入 2", text)
        self.assertNotIn("待写入 0", text)
        self.assertIn("unchanged 1", text)

    def test_real_run_counts_written(self):
        text = self._summarize(["updated", "created", "unchanged"], dry_run=False)
        self.assertIn("已写入 2", text)

    def test_dry_run_never_claims_written(self):
        text = self._summarize(["dry-run"], dry_run=True)
        self.assertNotIn("已写入", text)

    def test_real_run_never_claims_pending(self):
        text = self._summarize(["updated"], dry_run=False)
        self.assertNotIn("待写入", text)

    def test_all_unchanged_reports_zero(self):
        """已经全部配置好时，待写/已写都应如实为 0（不许虚报）。"""
        self.assertIn("待写入 0", self._summarize(["unchanged", "unchanged"], dry_run=True))
        self.assertIn("已写入 0", self._summarize(["unchanged", "unchanged"], dry_run=False))


class ScanSourceContractTest(unittest.TestCase):
    """源码级契约：scan.py 里的实现必须与上面的口径一致。

    这不是形式主义 —— 该段逻辑内联在 ``scan.main()`` 里，抽函数改动面过大，
    用源码断言把「取 dry-run 而非 updated+created」这一关键点钉住。
    """

    def _scan_source(self):
        return (ROOT / "scan.py").read_text(encoding="utf-8")

    def test_dry_run_branch_uses_dry_run_status(self):
        src = self._scan_source()
        # 从汇总计数开始切，而不是从打印语句开始 —— 后者会把计数逻辑排除在外。
        start = src.index("_counts: Dict[str, int] = {}")
        block = src[start:]
        block = block[: block.index("except Exception as e:")]
        self.assertIn('_counts.get("dry-run", 0)', block)
        # 关键：dry-run 分支不得复用 updated+created 的求和
        dry_part = block[: block.index("else:")]
        self.assertNotIn('_counts.get("updated", 0)', dry_part)
        # 且实写分支必须仍然是 updated+created
        self.assertIn('_counts.get("updated", 0) + _counts.get("created", 0)', block)

    def test_note_line_points_at_skills_dimension(self):
        src = self._scan_source()
        self.assertIn("统计 Skills 扫描维度", src)


if __name__ == "__main__":
    unittest.main()
