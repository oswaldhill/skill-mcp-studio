"""FEAT-9 GUI 护栏：市场入口、逐技能进度、安装二次确认、CLI 白名单。"""

import re
import unittest
from pathlib import Path
from tests._gui_source import page_source

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
RS = ROOT / "src-tauri" / "src" / "lib.rs"


def _src() -> str:
    # S10 前置：取源统一到 tests/_gui_source.page_source()，
    # 使断言不再依赖「脚本内联在 HTML 里」这一布局细节。
    return page_source()


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


class MarketUiTest(unittest.TestCase):
    def test_skills_page_has_market_entry(self):
        self.assertIn('data-action="open-market"', _section("page-skills"))

    def test_market_actions_are_wired(self):
        src = _src()
        for action in ("open-market", "market-search", "market-check",
                       "market-install", "market-upgrade"):
            self.assertIn(f'a === "{action}"', src, f"{action} 未接线")

    def test_panel_containers_exist(self):
        sect = _section("page-skills")
        for el in ("market-panel", "market-sources", "market-progress",
                   "market-results", "market-query"):
            self.assertIn(f'id="{el}"', sect, f"缺少容器 {el}")

    def test_progress_renders_per_skill(self):
        """逐技能进度：必须逐行追加，而不是只写一行汇总。"""
        body = _fn("renderMarketProgress")
        self.assertIn("forEach", body)
        self.assertIn("appendChild", body)

    def test_updates_rendered_per_skill(self):
        """检查结果也必须逐技能成行，含三态文案。"""
        body = _fn("renderMarketUpdates")
        self.assertIn("forEach", body)
        for word in ("有更新", "已最新", "无法检测"):
            self.assertIn(word, body, f"缺少状态文案 {word}")

    def test_install_requires_confirmation(self):
        src = _src()
        self.assertIn("function confirmMarketInstall", src)
        body = _fn("confirmMarketInstall")
        self.assertRegex(body, r"confirm|showModal|openModal",
                         "安装确认必须走确认弹窗，不能直接执行")

    def test_upgrade_requires_confirmation(self):
        body = _fn("confirmMarketUpgrade")
        self.assertRegex(body, r"confirm|showModal|openModal",
                         "升级确认必须走确认弹窗")

    def test_uses_market_cli_flag(self):
        self.assertIn('"--market"', _src())

    def test_check_is_labelled_read_only(self):
        """检查更新必须向用户说明是只读的（它确实是，但用户需要知道）。"""
        self.assertIn("只读", _src())


class UpgradeListConsistencyTest(unittest.TestCase):
    """v0.31.1 回归：一键升级的条目必须限定在技能列表里真实可见的技能。

    用户实测 bug：技能列表只显示 2 个「有更新」，点「一键升级」弹框却有 4 个。
    根因是 lock 里残留「目录已删除」的登记，被检查结果当成可升级技能。后端
    已单列 missing；这里断言 GUI 侧还有第二道口径过滤，防止后端再变时界面
    又出现「弹框里有 N 个、列表里一个都看不到」的自相矛盾。
    """

    def test_upgrade_all_filters_by_visible_skill_list(self):
        body = _fn("runSkillUpgradeAll")
        self.assertIn("SNAP", body, "必须按快照里的技能列表过滤")
        # 关键：送进弹框的必须是过滤后的数组。只断言「函数里出现过 filter」
        # 抓不住回归——排除幽灵技能那行也含 filter，还原成 outdated 照样通过
        # （实测过：这个断言必须盯住「传给 runSkillUpgradeModal 的实参」）。
        self.assertRegex(
            body, r"const upgradable = outdated\.filter\(\(n\) => listNames\.has\(n\)\)",
            "可升级清单必须是 outdated 与技能列表的交集")
        self.assertIn("runSkillUpgradeModal(upgradable)", body,
                      "弹框必须接收过滤后的清单")
        self.assertNotIn("runSkillUpgradeModal(outdated)", body,
                         "不得把未过滤的 outdated 直接交给弹框（这就是原 bug）")

    def test_upgrade_all_mentions_invalid_registration(self):
        """被排除的条目要说明原因，不能静默少升几个。"""
        body = _fn("runSkillUpgradeAll")
        self.assertRegex(body, r"登记|目录不存在|失效",
                         "排除项必须给出可解释的提示")
        self.assertIn("ghost", body, "排除项要单独收集以便提示")

    def test_missing_state_rendered_separately(self):
        """检查结果里 missing 要有独立文案，不能混进「无法检测」。"""
        body = _fn("renderMarketUpdates")
        self.assertIn("missing", body)
        self.assertIn("登记失效", body)

    def test_missing_state_never_offers_upgrade_action(self):
        """missing 无本地内容可覆盖，不给「升级」按钮（点了只会得到失败）。"""
        body = _fn("renderMarketUpdates")
        self.assertRegex(
            body, r'u\.state === "outdated" \? "升级" : ""',
            "只有 outdated 才提供升级动作")


class DashboardForbiddenGlyphTest(unittest.TestCase):
    """与既有 taste 护栏一致：新 UI 不用 em-dash / ⚠ / ✓。"""

    def test_market_block_has_no_em_dash_or_warning_glyph(self):
        src = _src()
        for name in ("renderMarketProgress", "renderMarketUpdates",
                     "confirmMarketInstall", "confirmMarketUpgrade",
                     "runMarketCheck", "runMarketSearch"):
            body = _fn(name)
            self.assertNotIn("—", body, f"{name} 含 em-dash")
            self.assertNotIn("⚠", body, f"{name} 含 ⚠")
            self.assertNotIn("✓", body, f"{name} 含 ✓")


class RustAllowlistTest(unittest.TestCase):
    """--market 必须进 Rust 侧白名单，否则 GUI 调用被安全边界拒绝。"""

    def test_market_is_allowlisted(self):
        src = RS.read_text(encoding="utf-8")
        m = re.search(r"const ALLOWED: &\[&str\] = &\[(.*?)\];", src, re.S)
        self.assertIsNotNone(m, "未找到 ALLOWED 白名单")
        allowed = re.findall(r'"([^"]+)"', m.group(1))
        self.assertIn("--market", allowed,
                      "--market 不在 run_cli 白名单内，GUI 会被拒绝")


if __name__ == "__main__":
    unittest.main()
