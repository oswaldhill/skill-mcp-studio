"""仓库形态更新（第五态 repo_outdated）的 GUI 与规范门禁断言（v0.31.3）。

为什么要有这批断言：这类技能一旦被混进 `outdated`，「一键升级」就会拿 npx
去重装一个「整仓库来源」的技能并得到假失败，同时「可升级 N」与技能列表重新
开始对不上——正是 v0.31.1 那个用户实缺陷的同一类回归。断言直接盯**实际渲染
分支与计数口径**，不做模糊的 `filter(state)` 匹配。
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui" / "dashboard.html"
MD = ROOT / "docs" / "DESIGN.md"
HTML = ROOT / "docs" / "DESIGN.html"


class RepoFormGuiTest(unittest.TestCase):
    def setUp(self):
        self.body = GUI.read_text(encoding="utf-8")

    def test_market_row_has_repo_branch_and_no_upgrade_button(self):
        # 市场页：repo_outdated 有自己的 tag 文案，且升级按钮判据只认 outdated
        self.assertIn('u.state === "repo_outdated" ? "仓库待同步"', self.body)
        self.assertIn('u.state === "outdated" ? "升级" : ""', self.body)

    def test_skill_table_remote_cell_marks_repo_pending(self):
        # 技能表远端列：待同步 tag 必须是 warn 且不带 data-skill-upgrade
        self.assertIn('待同步', self.body)
        seg = self.body.split('upd.state === "repo_outdated"', 1)
        self.assertEqual(len(seg), 2, "技能表远端列缺少 repo_outdated 分支")
        window = seg[1][:400]
        self.assertIn('class="tag warn"', window)
        self.assertNotIn("data-skill-upgrade", window,
                         "仓库形态的技能不能给可点击升级入口")

    def test_summary_and_toast_report_repo_pending_separately(self):
        # 汇总行与 toast 都要单独报这个数，且不能并入「有更新」
        self.assertIn("仓库待同步 ${repoPending}", self.body)
        self.assertIn('const repoPending = s.repo_outdated || 0;', self.body)
        self.assertIn("const repoPending = s.repo_outdated ? ` · 仓库待同步", self.body)

    def test_updatable_segment_excludes_repo_pending(self):
        # 「可升级」筛选段只认 outdated —— repo_outdated 不属于可升级
        self.assertIn(
            'return !!(SKILL_UPDATES && (SKILL_UPDATES[s] || {}).state === "outdated");',
            self.body,
        )


class RepoFormSpecTest(unittest.TestCase):
    def test_markdown_documents_the_fifth_state(self):
        body = MD.read_text(encoding="utf-8")
        for token in ("repo_outdated", "仓库待同步", "skill_repo_source",
                      "origin/<branch>", "只读", "不发网络请求"):
            self.assertIn(token, body, f"DESIGN.md 缺少 {token}")

    def test_html_mirrors_markdown(self):
        body = HTML.read_text(encoding="utf-8")
        for token in ("repo_outdated", "仓库待同步", "skill_repo_source",
                      "origin/&lt;branch&gt;"):
            self.assertIn(token, body, f"DESIGN.html 缺少 {token}")

    def test_spec_states_why_not_merged_into_outdated(self):
        # 这条是本次设计的核心论据，缺了后来者一定会想「为什么不合并」
        md = MD.read_text(encoding="utf-8")
        self.assertIn("为什么必须是独立状态而不是并进", md)
        self.assertIn("独立状态", md)


if __name__ == "__main__":
    unittest.main()
