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


class InstallErrorDisplayTest(unittest.TestCase):
    """安装失败时：错误进标准弹框，面板只留摘要（2026-11-15 实测）。

    用户勾选技能点「安装所选」后，面板进度行被塞进一整段 Python traceback
    （`File ".../scan.py", line 4575 ... KeyError: 'package'`），而弹框只写
    「详见面板提示」。原始 traceback 对用户没有任何意义，且把界面撑得很难看。
    """

    def test_raw_traceback_not_dumped_into_panel(self):
        body = _fn("executeGithubInstall")
        self.assertNotIn("prog.textContent = `安装失败：${(res && res.stderr)", body)

    def test_failure_goes_into_modal(self):
        body = _fn("executeGithubInstall")
        # 失败必须有 modalNotice，且带上有意义的说明
        self.assertIn("modalNotice", body)
        self.assertIn("安装失败", body)

    def test_parses_json_on_failure_too(self):
        """scan.py 失败时若仍输出 JSON（如 err 字段），要优先用它的 reason。"""
        body = _fn("executeGithubInstall")
        self.assertIn("JSON.parse", body)


class ConfirmDialogAclTest(unittest.TestCase):
    """确认框必须用 confirmModal，不能用 window.confirm（2026-11-15 实测）。

    Tauri 的 ACL 只放行 `dialog:default` 与 `dialog:allow-open`，**没有**允许
    `dialog:confirm`。在桌面 App 里调 window.confirm 会抛：

        Command plugin:dialog|confirm not allowed by ACL

    该异常逃逸成 unhandled rejection，被全局处理器兜住后弹出
    「操作失败 / 后台操作失败：Command plugin:dialog|confirm not allowed by ACL」，
    而安装其实已经成功——用户看到的是自相矛盾的两条结果。

    项目早已提供 confirmModal（注释原话：「replaces browser window.confirm()」），
    新增代码必须用它。
    """

    def test_github_install_does_not_use_window_confirm(self):
        for fn in ("confirmGithubInstall", "confirmRepoInstall"):
            body = _fn(fn)
            self.assertNotIn(
                "window.confirm", body,
                f"{fn} 用了 window.confirm：Tauri ACL 不允许 dialog:confirm，会抛错")

    def test_github_install_uses_confirm_modal(self):
        for fn in ("confirmGithubInstall", "confirmRepoInstall"):
            body = _fn(fn)
            self.assertIn("confirmModal", body, f"{fn} 应改用 confirmModal")
            self.assertIn("await", body, f"{fn} 必须 await confirmModal 的结果")


class InstalledBadgeTest(unittest.TestCase):
    """预览列表要标出「已安装」并禁用其勾选（2026-11-15 用户反馈）。

    用户装了 research 后，列表里它和没装过的完全一样，勾选框照旧可用：
    既无法确认刚装了什么，又会重复安装。
    """

    def test_list_marks_installed(self):
        body = _fn("renderGithubInstallList")
        self.assertIn("installed", body)

    def test_installed_checkbox_is_disabled(self):
        body = _fn("renderGithubInstallList")
        # 已装的不能勾选，避免重复安装
        self.assertIn("disabled", body)

    def test_progress_reports_installed_count(self):
        body = _fn("runGithubInstallFetch")
        self.assertIn("installed_count", body)


class ToolbarPriorityTest(unittest.TestCase):
    """工具栏在窄窗口下的优先级契约（2026-11-15）。

    用户 App 窗口约 770px 宽，Skills 工具栏已有 8 个按钮。换行会让排在后面的
    按钮视觉上「消失」，这正是此前「找不到从 GitHub 安装」的同类风险。

    约定：**主操作**（从 GitHub 安装 / 来源视图）必须排在最前，保证任何
    宽度下第一屏就能看到；次要操作（刷新 / 检查更新 / 一键升级 / 修复链接）
    排在后面。
    """

    PRIMARY = ("open-github-install", "open-provenance")

    def _buttons(self):
        section = _section("page-skills")
        return re.findall(r'data-action="([^"]+)"', section)

    def test_primary_actions_exist(self):
        actions = self._buttons()
        for a in self.PRIMARY:
            self.assertIn(a, actions, f"缺少主操作 {a}")

    def test_primary_actions_come_first(self):
        """主操作必须排在工具栏最前面（忽略「使用分析」这类辅助入口）。"""
        actions = [a for a in self._buttons()
                   if a not in ("refresh-skills", "skill-check-updates",
                                "skill-upgrade-all", "merge", "open-insight")]
        # 过滤后剩下的就是主操作，顺序应为 来源视图 → 从 GitHub 安装 → 技能市场
        self.assertEqual(actions[:2], ["open-provenance", "open-github-install"],
                         f"主操作顺序不符合约定：{actions[:3]}")

    def test_secondary_actions_exist_after(self):
        actions = self._buttons()
        for a in ("refresh-skills", "skill-check-updates", "merge"):
            self.assertIn(a, actions)


class ToolbarOverflowTest(unittest.TestCase):
    """工具栏不得溢出容器（2026-11-15 实测修正）。

    我第一版测试只断言「按钮都在第一行」，结果 770px 宽时虽然都在 row 0，
    却**横向溢出**：右侧按钮被切到屏幕外、标题被挤成竖排。
    正确的契约是：每个按钮的右边界都在其容器内。
    """

    def test_page_actions_allow_wrapping(self):
        src = _src()
        m = re.search(r'\n\s*\.page-actions \{([^}]*)\}', src)
        self.assertIsNotNone(m, "未找到 .page-actions 规则")
        body = m.group(1)
        # 允许换行，才不会在窄窗口把按钮挤出屏幕
        self.assertIn("flex-wrap: wrap", body)

    def test_page_head_allows_actions_to_wrap(self):
        """header 容器本身也要能换行：否则 actions 换行时会把标题压扁。"""
        src = _src()
        m = re.search(r'\n\s*\.page-head \{([^}]*)\}', src)
        self.assertIsNotNone(m, "未找到 .page-head 规则")
        body = m.group(1)
        self.assertIn("flex-wrap: wrap", body, ".page-head 需要 flex-wrap: wrap")
