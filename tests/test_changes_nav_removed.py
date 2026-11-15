"""移除「变更详情」的左侧导航项（2026-11-15 用户决定）。

用户判断：这个功能此前就在导航里，但**没有形成使用习惯**，留着反而是
「一个没人点的入口 + 一个已经能干的概览卡片」双重表达。

处置边界（重要）：
- 删掉**左侧导航项**，用户改从概览页「最近变更」卡片点「查看详情」进入。
- **保留 page-changes 页面本身**：它承载独有能力「保持」（把某条变更加入
  忽略清单，避免巡检反复打扰），概览卡片头最多只展示 5 条，完整清单也只能
  在这里看。删页面会让这两个能力无处安放。
"""

import unittest
from pathlib import Path

from tests._gui_source import page_source

ROOT = Path(__file__).resolve().parents[1]


def _src() -> str:
    return page_source()


class ChangesNavRemovedTest(unittest.TestCase):
    def test_no_nav_item_for_changes(self):
        """左侧导航不应再有指向 changes 的项。"""
        src = _src()
        self.assertNotIn('data-page="changes"', src,
                         "左侧导航仍有「变更详情」项，应按用户决定移除")
        self.assertNotIn('id="nav-changes"', src)

    def test_page_still_exists(self):
        """页面本体必须保留：承载「保持」与完整清单。"""
        self.assertIn('id="page-changes"', _src())

    def test_still_mapped_in_pages(self):
        """PAGES 映射保留，否则 switchPage('changes') 找不到元素。"""
        self.assertIn('changes: "page-changes"', _src())

    def test_reachable_from_overview(self):
        """概览卡片的「查看详情」是唯一入口，必须存在且接线。"""
        src = _src()
        self.assertIn('data-action="change-detail"', src)
        self.assertIn('a === "change-detail"', src)

    def test_ignore_capability_intact(self):
        """「保持」能力不能因移除入口而丢失。"""
        src = _src()
        self.assertIn('data-action="ignore-change"', src)
        self.assertIn('a === "ignore-change"', src)

    def test_system_group_still_has_settings(self):
        """「系统」分组不能因为少了一项而变成空的。"""
        src = _src()
        self.assertIn('data-page="settings"', src)
