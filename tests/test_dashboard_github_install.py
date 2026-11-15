"""GUI 护栏：Skills 页的「从 GitHub 安装」独立入口（2026-11-15）。

为什么要有这个文件（实测教训）：GitHub 安装功能第一版做成了「技能市场弹窗
搜索框的第二种输入」——功能是全的，但**入口不可发现**：用户打开技能市场、
输入关键词，看不到任何与 GitHub 有关的痕迹，自然认为功能没做。

所以入口本身要成为一个被测试锁定的契约：Skills 页必须有独立按钮、
必须打开独立弹窗、必须能走通「填地址 → 读取 → 勾选 → 安装」这条链。
"""

import re
import unittest
from pathlib import Path

from tests._gui_source import page_source
from tests._js_fn import extract_function

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
RS = ROOT / "src-tauri" / "src" / "lib.rs"


def _src() -> str:
    return page_source()


def _section(page_id: str) -> str:
    m = re.search(r'<section id="' + page_id + r'".*?</section>', _src(), re.S)
    if not m:
        raise AssertionError(f"未找到页面区块 {page_id}")
    return m.group(0)


def _fn(name: str) -> str:
    return extract_function(_src(), name)


class GithubInstallEntryTest(unittest.TestCase):
    """入口本身：按钮 + 弹窗 + 接线。"""

    def test_skills_page_has_dedicated_github_entry(self):
        """Skills 页必须有独立的「从 GitHub 安装」按钮，不能只藏在市场弹窗里。"""
        section = _section("page-skills")
        self.assertIn('data-action="open-github-install"', section)

    def test_github_entry_is_visually_distinct_from_market(self):
        """两个入口并存：技能市场（搜索）与从 GitHub 安装（贴地址）不是同一个按钮。"""
        section = _section("page-skills")
        self.assertIn('data-action="open-market"', section)
        self.assertIn('data-action="open-github-install"', section)

    def test_dedicated_dialog_exists(self):
        """必须有独立弹窗，不能复用市场弹窗。"""
        self.assertIn('id="github-install-panel"', _src())

    def test_dialog_has_url_input(self):
        src = _src()
        m = re.search(r'<dialog id="github-install-panel".*?</dialog>', src, re.S)
        self.assertIsNotNone(m, "未找到 github-install-panel 弹窗")
        panel = m.group(0)
        self.assertIn('id="github-install-url"', panel)
        self.assertIn('data-action="github-install-fetch"', panel)

    def test_open_action_is_wired(self):
        src = _src()
        self.assertIn('a === "open-github-install"', src)
        self.assertIn('a === "github-install-fetch"', src)
        self.assertIn('a === "github-install-close"', src)

    def test_placeholder_mentions_github(self):
        src = _src()
        m = re.search(r'<dialog id="github-install-panel".*?</dialog>', src, re.S)
        panel = m.group(0)
        self.assertIn("GitHub", panel)


class GithubInstallFlowTest(unittest.TestCase):
    """流程函数：读取 → 勾选 → 安装，且复用同一套安全形状。"""

    def test_fetch_function_exists(self):
        body = _fn("runGithubInstallFetch")
        # 必须调 --market-preview（只读预览）
        self.assertIn("--market-preview", body)

    def test_fetch_does_not_install(self):
        """读取按钮绝不能触发安装 —— 只读语义。"""
        body = _fn("runGithubInstallFetch")
        self.assertNotIn("--market-install", body)

    def test_install_requires_selection(self):
        """没勾选就安装时必须拦截。"""
        body = _fn("confirmGithubInstall")
        self.assertIn("selectedGithubRepoNames", body)

    def test_install_pass_skills_list(self):
        body = _fn("executeGithubInstall")
        self.assertIn("--market-skills", body)
        self.assertIn("--yes", body)

    def test_install_pins_url(self):
        """安装命令必须带上用户填的地址。"""
        body = _fn("executeGithubInstall")
        self.assertIn("--market-install", body)

    def test_checkbox_class_is_scoped(self):
        """新弹窗的复选框用独立 class，避免与市场弹窗的勾选互相串。"""
        src = _src()
        self.assertIn("github-install-cb", src)
        self.assertNotIn('class="market-repo-cb github-install-cb"', src)


class RunCliWhitelistTest(unittest.TestCase):
    """新入口走的是既有 CLI 出口，白名单必须已覆盖。"""

    def test_whitelist_covers_preview_and_skils(self):
        rs = RS.read_text(encoding="utf-8")
        for flag in ("--market-preview", "--market-skills"):
            self.assertIn(f'"{flag}"', rs, f"{flag} 未登记进 run_cli 白名单")


if __name__ == "__main__":
    unittest.main()

class NoSkillRepoMessageTest(unittest.TestCase):
    """仓库里没有技能时，界面必须说清「原因」，不能只吐一个 '}'。

    实测（2026-11-15）：给一个不含 SKILL.md 的仓库（Goblinmine/homelab-diagram），
    `scan.py --market-preview --format json` 输出**完整 JSON** 但退出码为 2
    （2 表示「没有技能」，不是崩溃）。GUI 曾把非零退出码一律当失败，并把
    stdout 的最后一行（那是 JSON 的收尾 `}`）当错误信息显示，界面上只剩一个 `}`。
    """

    def test_parses_json_even_on_nonzero_exit(self):
        """退出码非 0 时仍要先尝试解析 stdout 里的 JSON。"""
        body = _fn("runGithubInstallFetch")
        # 关键：解析必须发生在「按退出码判定失败」之前，或至少对非 0 也解析
        self.assertIn("JSON.parse", body)
        # 不应把 stdout 末行直接当错误文案
        self.assertNotIn("split(\"\\n\").filter(Boolean).pop()", body)

    def test_no_skill_reason_is_surfaced(self):
        """reason 字段（如「未能从仓库输出中解析出技能名」）必须被展示。"""
        body = _fn("runGithubInstallFetch")
        self.assertIn("plan.reason", body)

    def test_empty_skills_message_mentions_skill_md(self):
        """空清单的提示应说明「需要 SKILL.md」，用户才知道为什么没东西可装。"""
        body = _fn("renderGithubInstallList")
        self.assertIn("SKILL.md", body)
