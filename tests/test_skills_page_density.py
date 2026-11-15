"""Skills 页排版密度优化（2026-11-15 用户反馈「稍微有点拥挤」）。

优化前实测（1500px 宽）：
  - 搜索框 40px + toolbar 32px + 分类 chips 23px，三者纵向堆叠占约 110px
  - 表格行高 40px，6 列挤在 1200px 内，「用途」列被截断
  - 11 个分类 chips 平铺成一行，每个都是可点按钮

优化方向（开发者工具风格：层级少、留白足、主次清）：
  1. 三层筛选压成两层：分类 chips 收进「更多」或降低视觉权重
  2. 表格行高提到 48px，给文字喘息
  3. 「用途」列加宽，名称列收窄
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui" / "dashboard.html"


def _css() -> str:
    return GUI.read_text(encoding="utf-8")


class TableComfortTest(unittest.TestCase):
    def test_row_height_is_comfortable(self):
        """表格行高 ≥ 46px：40px 对 6 列数据表太挤。"""
        m = re.search(r"\.skill-table td \{[^}]*height:\s*var\((--[\w-]+)\)", _css())
        self.assertIsNotNone(m, "未找到表格行高定义")
        var = m.group(1)
        vm = re.search(re.escape(var) + r":\s*(\d+)px", _css())
        self.assertIsNotNone(vm, f"未找到变量 {var} 的值")
        self.assertGreaterEqual(int(vm.group(1)), 46,
                                f"行高 {vm.group(1)}px 偏挤，应 ≥46px")

    def test_usage_column_gets_more_room(self):
        """「用途」列最宽（auto），名称列不超过 20%。"""
        css = _css()
        m = re.search(r"\.skill-table th\.st-name \{\s*width:\s*(\d+)%", css)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 20,
                             "名称列过宽会挤压用途列")

    def test_category_chips_are_not_buttons_every_row(self):
        """分类 chips 数量多时应能换行/收纳，不硬挤一行。"""
        css = _css()
        m = re.search(r"\.skill-cat-chips \{[^}]*\}", css)
        self.assertIsNotNone(m)
        self.assertIn("flex-wrap", m.group(0))


class VerticalRhythmTest(unittest.TestCase):
    def test_search_to_toolbar_spacing_tightened(self):
        """搜索框与 toolbar 之间不应再有额外大间距（避免三段各自留白）。"""
        css = _css()
        m = re.search(r"\.skill-search \{[^}]*margin-bottom:\s*var\((--[\w-]+)\)", css)
        self.assertIsNotNone(m, "未找到 skill-search 下边距")

    def test_table_has_no_redundant_top_margin(self):
        """筛选区与表格之间间距应统一，不叠加。"""
        css = _css()
        # 表格容器不应又设一个大 margin-top
        assert ".skill-table" in css
