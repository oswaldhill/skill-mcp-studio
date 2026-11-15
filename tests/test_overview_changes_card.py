"""概览页的「最近变更」卡片（2026-11-15 用户选择方案 2）。

问题：变更详情原本只挂在左侧「系统 → 变更详情」。这是一个**低频但关键时刻
很重要**的功能（排查「我什么都没动，为什么行为变了」），而那个位置不会让人
联想到「排查环境变化」。用户只有在出问题时才需要它，却找不到。

方案：在概览页（用户每次都会先看的地方）放一张「最近变更」卡片，
把对比结果直接摊在首屏；点卡片再进详情页。
"""

import re
import unittest
from pathlib import Path

from tests._gui_source import page_source
from tests._js_fn import extract_function

ROOT = Path(__file__).resolve().parents[1]


def _src() -> str:
    return page_source()


def _section(page_id: str) -> str:
    m = re.search(r'<section id="' + page_id + r'".*?</section>', _src(), re.S)
    if not m:
        raise AssertionError(f"未找到页面区块 {page_id}")
    return m.group(0)


class OverviewChangesCardTest(unittest.TestCase):
    def test_overview_has_changes_card(self):
        """概览页要有独立的「最近变更」卡片容器。"""
        self.assertIn('id="overview-changes"', _section("page-overview"))

    def test_card_has_refresh_action(self):
        """卡片内要能就地跑一次对比，不必先跳页。"""
        sec = _section("page-overview")
        self.assertRegex(sec, r'data-action="[^"]*snapshot[^"]*"')

    def test_card_links_to_full_page(self):
        """卡片能跳到完整的变更详情页。"""
        sec = _section("page-overview")
        self.assertIn("change-detail", sec)

    def test_render_function_exists(self):
        """需要一个渲染函数把 diff 结果写进卡片。"""
        body = _fn_ok("renderOverviewChanges")
        self.assertIn("summary", body)

    def test_change_detail_action_wired(self):
        src = _src()
        self.assertIn('a === "change-detail"', src)

    def test_render_shows_no_change_state(self):
        """没有变更时也要有信息量，不能只显示一片空。"""
        body = _fn_ok("renderOverviewChanges")
        # 无变更分支应显示「无变更」类文案，而不是留白
        self.assertTrue(
            "无变更" in body or "没有变更" in body or "未发现" in body,
            "无变更分支缺少说明文案")


def _fn_ok(name: str) -> str:
    return extract_function(_src(), name)
