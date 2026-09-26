"""事件委托契约：能被委托处理的按钮必须带 data-action。

回归背景：面板里的 tab 按钮只写了 data-insight-tab、漏了 data-action，
而委托入口是 `e.target.closest("[data-action]")`，于是点击被静默丢弃
（不报错、不告警，用户只看到"点了没反应"）。

规律：委托链里读 `act.dataset.X`，则该字段所在按钮必须带 data-action。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _delegation_block() -> str:
    s = _src()
    i = s.index('e.target.closest("[data-action]")')
    return s[i:i + 9000]


def _read_fields() -> list:
    return sorted(set(re.findall(r"act\.dataset\.([a-zA-Z]+)", _delegation_block())))


def _kebab(camel: str) -> str:
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), camel)


class DelegationContractTest(unittest.TestCase):
    """按钮要能进委托链，就必须带 data-action。"""

    def test_html_exists(self):
        self.assertTrue(HTML.exists(), "缺少 gui/dashboard.html")

    def test_delegation_entry_requires_data_action(self):
        """委托入口确实以 data-action 为门（这是本测试的前提）。"""
        self.assertIn('closest("[data-action]")', _src(),
                      "委托入口不再要求 data-action，本契约需重新审视")
        self.assertTrue(_read_fields(), "委托链里没有读到任何 dataset 字段")

    def test_insight_tab_buttons_are_reachable(self):
        """面板 tab 必须同时带 data-action 与 data-insight-tab。"""
        s = _src()
        btns = re.findall(r"<button[^>]*data-insight-tab=[^>]*>", s)
        self.assertEqual(len(btns), 2, f"应有 2 个 tab 按钮，实得 {len(btns)}")
        for b in btns:
            self.assertIn("data-action=", b,
                          f"tab 按钮缺 data-action，点击会被委托入口丢弃：{b}")
            self.assertIn('data-action="insight-tab"', b,
                          f"tab 按钮的 action 名不对：{b}")

    # 这些字段虽在委托链里被读，但对应按钮由 class 选择器单独绑定
    # （.kebab / .pm-item / .btn-agent-detail / .btn-mt-settings / data-popkind），
    # 不走委托入口，故允许不带 data-action。新增字段若不在清单内却缺
    # data-action，就会被下面的断言拦下。
    CLASS_BOUND_FIELDS = {"name", "skill"}

    def test_delegated_fields_on_buttons_carry_data_action(self):
        """委托链读取的字段若出现在按钮上，该按钮必须带 data-action。

        这是"整理建议 tab 点击无效"的通用化：漏了 data-action 的按钮会被
        委托入口静默丢弃，不报错、不告警，只有用户点不出来。
        """
        s = _src()
        offenders = []
        for field in _read_fields():
            if field == "action" or field in self.CLASS_BOUND_FIELDS:
                continue
            attr = "data-" + _kebab(field)
            for b in re.findall(r"<button[^>]*%s=[^>]*>" % re.escape(attr), s):
                if "data-action=" not in b:
                    offenders.append((attr, b[:100]))
        self.assertFalse(
            offenders,
            "以下按钮会被委托入口丢弃（既无 data-action，也不在 class 绑定清单内）："
            + repr(offenders),
        )

    def test_class_bound_exceptions_still_bound(self):
        """例外清单里的字段，其按钮确实由 class 选择器绑定（防止清单失实）。"""
        s = _src()
        for cls in (".kebab", ".pm-item", ".btn-agent-detail", ".btn-mt-settings"):
            self.assertIn(cls, s, f"{cls} 已不再被引用，例外清单需更新")


if __name__ == "__main__":
    unittest.main()
