"""变更忽略清单（``core/ignored_changes.py``）的回归测试。

背景：方案文档 5.4 要求「被『保持』的变更记入忽略清单，直到该变更消失或
用户主动清除」。若没有这个出口，同一条变更会在每轮巡检里反复弹通知，通知
最终被无视 —— 等于失效。

实测暴露过一个关键陷阱：如果在同一轮里「先过滤、再 prune」，因为过滤后的
集合恰好不含被忽略的变更，prune 会把用户刚「保持」的条目**全部误清**。
因此 prune 改为显式命令，且必须用未过滤的原始 diff 判断。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import ignored_changes as ic  # noqa: E402


def _diff(hooks=None, agents=None):
    hooks = hooks if hooks is not None else []
    agents = agents if agents is not None else []
    return {
        "has_changes": bool(hooks or agents),
        "is_first": False,
        "dimensions": {"agents": agents, "mcp": [], "skills": [], "hooks": hooks},
        "summary": {"agents": len(agents), "mcp": 0, "skills": 0, "hooks": len(hooks)},
    }


HOOK_CHANGE = {
    "type": "hooks_configured_changed",
    "name": "Cursor",
    "old": True,
    "new": False,
    "detail": "Hook 接入 True -> False",
}


class FingerprintTest(unittest.TestCase):
    def test_fingerprint_uses_dim_name_type_only(self):
        fp = ic.change_fingerprint("hooks", HOOK_CHANGE)
        self.assertEqual(
            fp,
            {"dim": "hooks", "name": "Cursor", "type": "hooks_configured_changed"},
        )

    def test_fingerprint_ignores_values(self):
        """同一处配置反复改值仍算同一条变更，用户「保持」一次应长期有效。"""
        a = dict(HOOK_CHANGE, old=True, new=False)
        b = dict(HOOK_CHANGE, old=False, new=True)
        self.assertEqual(
            ic.change_fingerprint("hooks", a),
            ic.change_fingerprint("hooks", b),
        )


class FilterTest(unittest.TestCase):
    def test_filter_removes_ignored_and_recomputes(self):
        diff = _diff(hooks=[HOOK_CHANGE, dict(HOOK_CHANGE, type="hook_events_removed")])
        items = [{"dim": "hooks", "name": "Cursor", "type": "hooks_configured_changed"}]
        out = ic.filter_changes(diff, items)
        self.assertEqual(out["summary"]["hooks"], 1)
        self.assertEqual(out["ignored_count"], 1)
        self.assertTrue(out["has_changes"])
        types = [c["type"] for c in out["dimensions"]["hooks"]]
        self.assertNotIn("hooks_configured_changed", types)

    def test_filter_all_clears_has_changes(self):
        diff = _diff(hooks=[HOOK_CHANGE])
        items = [{"dim": "hooks", "name": "Cursor", "type": "hooks_configured_changed"}]
        out = ic.filter_changes(diff, items)
        self.assertFalse(out["has_changes"])
        self.assertEqual(out["summary"]["hooks"], 0)
        self.assertEqual(out["ignored_count"], 1)

    def test_filter_with_empty_list_is_identity(self):
        diff = _diff(hooks=[HOOK_CHANGE])
        out = ic.filter_changes(diff, [])
        self.assertEqual(out["summary"]["hooks"], 1)
        self.assertEqual(out["ignored_count"], 0)

    def test_filter_does_not_mutate_input(self):
        diff = _diff(hooks=[HOOK_CHANGE])
        ic.filter_changes(diff, [{"dim": "hooks", "name": "Cursor", "type": "hooks_configured_changed"}])
        self.assertEqual(len(diff["dimensions"]["hooks"]), 1, "原 diff 不应被改动")

    def test_filter_matches_dimension_too(self):
        """同名的不同维度不应互相误伤。"""
        agents = [{"type": "hooks_configured_changed", "name": "Cursor"}]
        diff = _diff(hooks=[HOOK_CHANGE], agents=agents)
        items = [{"dim": "hooks", "name": "Cursor", "type": "hooks_configured_changed"}]
        out = ic.filter_changes(diff, items)
        self.assertEqual(out["summary"]["hooks"], 0)
        self.assertEqual(out["summary"]["agents"], 1, "agents 维度的同名变更不应被忽略")


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "ignored_changes.yaml")

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_is_empty_not_error(self):
        self.assertEqual(ic.load_ignored(self.path), [])

    def test_corrupt_file_is_empty_not_error(self):
        Path(self.path).write_text("这不是: [合法的 yaml", encoding="utf-8")
        self.assertEqual(ic.load_ignored(self.path), [])

    def test_add_is_idempotent(self):
        ic.add_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        items = ic.add_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        self.assertEqual(len(items), 1)

    def test_add_then_load_roundtrip(self):
        ic.add_ignored("hooks", "Cursor", "hook_events_removed", self.path)
        items = ic.load_ignored(self.path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["dim"], "hooks")
        self.assertEqual(items[0]["name"], "Cursor")
        self.assertEqual(items[0]["type"], "hook_events_removed")
        self.assertIn("ignored_at", items[0])

    def test_remove_is_idempotent(self):
        ic.add_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        ic.remove_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        items = ic.remove_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        self.assertEqual(items, [])

    def test_written_file_ends_with_single_newline(self):
        ic.add_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        raw = Path(self.path).read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))


class PruneTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "ignored_changes.yaml")

    def tearDown(self):
        self._tmp.cleanup()

    def test_prune_keeps_entries_still_present(self):
        ic.add_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        kept = ic.prune_ignored(_diff(hooks=[HOOK_CHANGE]), self.path)
        self.assertEqual(len(kept), 1)

    def test_prune_drops_entries_no_longer_present(self):
        ic.add_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        kept = ic.prune_ignored(_diff(), self.path)
        self.assertEqual(kept, [])

    def test_prune_must_use_unfiltered_diff(self):
        """核心陷阱：拿过滤后的 diff 去 prune 会误清全部条目。

        过滤后的集合里恰好不含被忽略的变更，若用它判断「变更是否还在」，
        结论必然是「已消失」，于是用户刚「保持」的条目被清空。这里把该
        行为钉成断言：只要传未过滤 diff，条目就必须保留。
        """
        ic.add_ignored("hooks", "Cursor", "hooks_configured_changed", self.path)
        raw = _diff(hooks=[HOOK_CHANGE])
        filtered = ic.filter_changes(raw, ic.load_ignored(self.path))
        # 过滤后确实不含该变更 —— 这正是不能用它做判据的原因
        self.assertEqual(filtered["summary"]["hooks"], 0)
        # 用未过滤的原始 diff → 条目保留
        kept = ic.prune_ignored(raw, self.path)
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()
