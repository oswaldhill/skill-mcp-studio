"""FEAT-8 护栏：每个业务页都要有就地刷新入口。

背景：快照原先只在启动时通过 ``loadManagement()`` 拉一次，而 ``switchPage()``
只切换 CSS 可见性、并不重新取数（见 dashboard.html 的 ``switchPage``）。因此用户
改完后端数据后，切到某个页面看到的仍是启动时的旧快照——若该页没有刷新按钮，就只能
重启应用，是明确的交互缺陷。

实测当时的状态：概览与 IDE/Agent 页有「刷新审计」，而 **Skills 页只有「一键合并技能」、
没有任何刷新入口**（MCP/设置页也没有，但这两页读取的是随快照一并刷新的数据，入口
统一放在承载取数的业务页即可）。

本护栏锁定两条：
1. Skills 页保留刷新按钮，且接到 ``refreshWithBtn``（复用整份快照重取，不是只重渲染）；
2. 刷新 toast 文案不写死「审计」，否则在 Skills 页会说出对不上的措辞。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

HTML = ROOT / "gui" / "dashboard.html"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _section(page_id: str) -> str:
    m = re.search(r'<section id="' + page_id + r'".*?</section>', _src(), re.S)
    if not m:
        raise AssertionError(f"未找到页面区块 {page_id}")
    return m.group(0)


def _fn(name: str) -> str:
    m = re.search(r"function " + name + r"\(.*?\n\}", _src(), re.S)
    if not m:
        raise AssertionError(f"未找到函数 {name}")
    return m.group(0)


class RefreshEntryTest(unittest.TestCase):
    def test_skills_page_has_refresh_button(self):
        body = _section("page-skills")
        self.assertIn(
            'data-action="refresh-skills"',
            body,
            "Skills 页缺少刷新入口：切页不重取数，用户只能重启应用",
        )

    def test_refresh_action_is_wired(self):
        src = _src()
        self.assertIn(
            'a === "refresh-skills"',
            src,
            "刷新按钮未接线，点了没反应",
        )
        # 必须复用整份快照重取，而不是仅重新渲染内存里的旧数据
        m = re.search(r'a === "refresh-skills"\)\s*(\w+)\(act\)', src)
        self.assertIsNotNone(m, "刷新处理未传按钮元素（无法进入 loading 态）")
        self.assertEqual(m.group(1), "refreshWithBtn")

    def test_refresh_rescans_snapshot(self):
        """刷新必须真的重跑取数，否则只是把旧数据重画一遍。"""
        body = _fn("refreshWithBtn")
        self.assertIn(
            "loadManagement()",
            body,
            "刷新未调用 loadManagement()，数据不会更新",
        )

    def test_toast_text_not_hardcoded_to_audit(self):
        """按钮在 Skills 页也叫「刷新技能」，toast 不能写死「审计」。"""
        body = _fn("refreshWithBtn")
        self.assertNotIn("刷新审计", body, "toast 写死了「审计」，在 Skills 页措辞不符")
        self.assertNotIn("审计已刷新", body)
        # 应复用按钮标签本身
        self.assertIn("btn.textContent", body)

    def test_label_derivation_avoids_double_prefix(self):
        """不许把「刷新」拼在标签前——否则「重新扫描」会变成病句。"""
        body = _fn("refreshWithBtn")
        self.assertNotIn(
            '`正在刷新${orig}',
            body,
            "直接用原标签会得到「正在刷新刷新审计…」",
        )


class NoStaleOnSwitchTest(unittest.TestCase):
    def test_switch_page_does_not_pretend_to_refresh(self):
        """switchPage 目前只切可见性——本护栏记录这一事实，防止误以为它取数。

        若将来给 switchPage 加了自动取数，此断言会失败，提示同步更新本文件的
        说明与 Skills 页是否需要保留按钮。
        """
        body = _fn("switchPage")
        self.assertNotIn(
            "loadManagement",
            body,
            "switchPage 已开始自动取数，请复核各页刷新按钮的必要性与本文档说明",
        )


if __name__ == "__main__":
    unittest.main()