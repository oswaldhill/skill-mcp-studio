"""整理建议弹窗的排版契约。

原先是整片等宽文本流（纯 usageLine 拼接），信息本身有列结构却读不出列。
这组测试把"排版必须是结构化的"钉住，防止退回文本 dump。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")


def _advice_js() -> str:
    """renderAdvice 及其排版辅助函数的源码。"""
    i = HTML.index("function memberRow")
    j = HTML.index("// ---------------- 技能市场")
    return HTML[i:j]


class AdviceLayoutTest(unittest.TestCase):
    """整理建议必须是结构化排版，不能是文本流。"""

    def test_uses_sectioned_layout(self):
        body = _advice_js()
        for token in ("adv-sec", "adv-sec-head", "adv-sec-title", "adv-sec-note"):
            assert token in body, f"缺少分节排版元素 {token}"

    def test_actionable_groups_are_cards_with_tables(self):
        body = _advice_js()
        # 每组一张卡，成员落进表格（这是本次排版优化的核心）
        for token in ("adv-card", "adv-card-head", "adv-rule", "adv-keep", "adv-fold",
                      "adv-evidence", "adv-members", "memberRow"):
            assert token in body, f"可合并组缺少 {token}"
        assert "createElement(\"tbody\")" in body, "成员未放进 tbody"

    def test_member_table_has_all_columns(self):
        body = _advice_js()
        # 加载/会话/最近/状态四列必须都在，且数字列右对齐
        for token in ("加载", "会话", "最近", "状态", "adv-num", "adv-name", "adv-when"):
            assert token in body, f"成员表缺少列 {token}"
        assert "tabular-nums" in HTML, "数字列未用等宽数字对齐"

    def test_rejected_is_collapsed_by_default(self):
        """已否决是整理的中间过程（判据依据），不该占主视图：默认收起，点击才展开。"""
        body = _advice_js()
        for token in ("adv-rej-fold", "adv-rej-fold-head", "判据已否决"):
            assert token in body, f"已否决收起段缺少 {token}"
        # 用原生 details/summary 承载折叠状态，不另造 JS 开关变量
        assert 'advEl("details"' in body, "折叠容器应为 details"
        assert 'advEl("summary"' in body, "折叠标题应为 summary"
        # 默认收起：渲染时不得预置 open
        assert "det.open" not in body, "不得在渲染时强制展开已否决段"
        # 明细仍在 DOM 内，展开后可见
        for token in ("adv-rej-row", "adv-pair", "adv-verdict", "adv-gate"):
            assert token in body, f"展开后的明细缺少 {token}"
        assert "adv-card" not in body.split("判据已否决")[1].split("adv-foot")[0], \
            "已否决段不应使用卡片"

    def test_rejected_count_not_in_metric_strip(self):
        """指标条只留需要动作的口径；已否决条数是中间过程，不进指标条。"""
        strip = _advice_js().split("adv-strip")[1].split("out.appendChild(strip)")[0]
        assert "已否决" not in strip, "指标条不应再出现「已否决」格"
        assert "rejected_entries" not in strip, "指标条不应再读 rejected_entries"

    def test_css_rules_exist_for_every_class(self):
        """用到 class 就必须有对应规则，否则等于没排版。"""
        body = _advice_js()
        used = set(re.findall(r'advEl\(\s*"[a-z]+"\s*,\s*"([a-z-]+)"', body))
        used |= {"adv-name", "adv-num", "adv-when", "adv-tag", "adv-keep-row",
                 "adv-pair", "adv-verdict", "adv-gate"}
        missing = [c for c in sorted(used) if f".{c}" not in HTML]
        assert not missing, f"这些 class 没有 CSS 规则: {missing}"

    def test_marks_surface_as_tags_not_prose(self):
        """含脚本/零触达等证据用标签呈现，不再是括号里的散文。"""
        body = _advice_js()
        assert "adv-tag" in body
        for token in ("零触达", "含脚本", "保留"):
            assert token in body, f"缺少状态标签 {token}"

    def test_judgement_still_stays_in_backend(self):
        """排版改造不得把判据搬到前端（沿用原本的边界约束）。"""
        body = _advice_js()
        for token in ("jaccard", "archived_sessions", ".jsonl", "host_skills"):
            assert token not in body, f"前端越界实现判据片段 {token}"

    def test_no_forbidden_glyphs(self):
        body = _advice_js()
        for glyph in ("\u2014", "\u26a0", "\u2713"):
            assert glyph not in body, f"含禁用字形 {glyph!r}"


if __name__ == "__main__":
    unittest.main()
