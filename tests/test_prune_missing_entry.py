"""清理登记残留的入口可达性（2026-11-15 用户反馈）。

现象：检查完成弹框写「有 5 个技能已卸载但登记残留，可在技能行删除」，
但那 5 个技能的目录已经不在了——技能行里根本没有它们，无法删除。
真正的清理按钮藏在「设置」页，用户不可能从这条提示找到它。

约定：检查完成弹框必须**直接提供可点的清理入口**，而不是让用户自己去猜。
"""

import unittest
from pathlib import Path

from tests._gui_source import page_source
from tests._js_fn import extract_function

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui" / "dashboard.html"


def _src() -> str:
    return page_source()


def _fn(name: str) -> str:
    return extract_function(_src(), name)


class PruneEntryTest(unittest.TestCase):
    def test_backend_prune_exists(self):
        """后端清理能力必须存在（带 dry-run 与备份）。"""
        import sys
        sys.path.insert(0, str(ROOT / "core"))
        from skill_market import prune_missing_registrations
        import inspect
        sig = inspect.signature(prune_missing_registrations)
        self.assertIn("dry_run", sig.parameters)

    def test_gui_has_prune_action(self):
        self.assertIn('data-action="prune-skill-lock"', _src())

    def test_check_result_offers_clickable_prune(self):
        """「检查完成」弹框里要达到可点的清理按钮，而不是只有一行字。"""
        body = _fn("runSkillCheckUpdates")
        # 必须出现 prune-skill-lock，说明弹框内提供了入口
        self.assertIn("prune-skill-lock", body,
                      "检查完成弹框没有提供可点的「清理登记残留」入口")

    def test_lead_text_no_longer_misleads(self):
        """不能再写「可在技能行删除」——那些技能行已经不存在。"""
        body = _fn("runSkillCheckUpdates")
        self.assertNotIn("可在技能行删除", body)

    def test_prune_requires_confirmation(self):
        """清理是写操作，必须二次确认。"""
        body = _fn("openPruneSkillLockModal")
        self.assertIn("confirmModal", body)

    def test_prune_dry_run_first(self):
        """先 dry-run 展示将删哪些，再执行。"""
        body = _fn("openPruneSkillLockModal")
        self.assertIn("--dry-run", body)
