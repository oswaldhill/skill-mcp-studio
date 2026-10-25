"""PRD「技能关闭（长期未使用清理）」需求的门禁断言（v0.31.x 待实现项）。

为什么给一份需求写断言：这条需求的价值全在**口径**上——「从未使用」和「N 天未
使用」是两个数、关闭不等于删除、`root` 形态必须先迁移、不得与 MCP 混成一个
数字。这些句子一旦在后续编辑中被顺手抹平，实现阶段就会照着模糊描述做出用户
可见的错误结论（v0.31.1 的「列表 2 个、弹框 4 个」就是这么来的）。所以把口径
钉成断言，删改即红。

只断言「需求文档说了什么」，不断言实现——功能尚未实现，测试不能替它先绿。
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs" / "product" / "PRD-产品需求文档.md"


class SkillDisableRequirementTest(unittest.TestCase):
    def setUp(self):
        self.body = PRD.read_text(encoding="utf-8")

    def test_requirement_section_exists(self):
        self.assertIn("#### 6.2.1 技能关闭（长期未使用清理）", self.body)

    def test_records_why_it_was_raised(self):
        # 需求来源要可追溯：用户 2026-10-25 提出，不是凭空加的
        self.assertIn("背景（用户提出，2026-10-25）", self.body)
        self.assertIn("占用上下文", self.body)

    def test_two_counts_must_stay_separate(self):
        # 「从未使用」与「N 天未使用」不得混成一个数
        self.assertIn("「从未使用」与「N 天未使用」分开呈现", self.body)

    def test_close_is_not_delete(self):
        self.assertIn("技能本体与共享库内容**不删除**", self.body)

    def test_root_form_must_be_blocked_before_batch_close(self):
        self.assertIn("`root` 形态", self.body)
        self.assertIn("--migrate-skill-links", self.body)
        self.assertIn("skill_link_form", self.body)

    def test_must_not_be_merged_with_mcp(self):
        self.assertIn("不得合并成一个数字", self.body)

    def test_reuses_existing_read_and_write_paths(self):
        # 需求不得暗示要新造写路径：判定复用 --skill-insight，写入复用 --disable-skill
        self.assertIn("--skill-insight", self.body)
        self.assertIn("--disable-skill", self.body)
        self.assertIn("不需要新的写路径", self.body)

    def test_snooze_state_goes_to_overlay_not_config(self):
        self.assertIn("不写 `config.yaml`", self.body)

    def test_gap_board_lists_it_as_pending(self):
        self.assertIn("⬜ **待实现**", self.body)
        self.assertIn("§6.2.1", self.body)


if __name__ == "__main__":
    unittest.main()
