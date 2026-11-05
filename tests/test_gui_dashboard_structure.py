"""T-3（JS 侧）结构护栏：GUI 内联 JS 的完整性守护。

行为测试已由 ``tests/gui_helpers.test.mjs``（node:test，真实执行纯函数并断言输出）
承担；本测试作为 Python 侧可离线跑的结构性补充，锁定「无 node 也能验证」的不变量：

1. 内联 ``<script>`` 的花/圆/方括号三者平衡——任何编辑导致的括号失配立即失败；
2. 无 ``eval`` / ``new Function`` / ``document.write``——内联脚本靠 CSP
   ``'unsafe-inline'`` 放行，任何动态求值都会放大注入面，禁止新增；
3. 关键纯函数/交互函数定义仍在（防无意删除导致 GUI 静默失效）。

Rust 侧单元测试见 ``src-tauri/src/lib.rs`` 的 ``#[cfg(test)]``（由 CI
``cargo test`` 执行，见 ``.github/workflows/test.yml`` 的 ``test-rust`` job）。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui" / "dashboard.html"
sys.path.insert(0, str(ROOT))

from tests._gui_source import page_html  # noqa: E402


def _main_script() -> str:
    html = GUI.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    # 主应用逻辑是最后一个 <script>；前面若有 helper 脚本也一并纳入检查。
    return "\n".join(scripts)


class GuiJsStructureTest(unittest.TestCase):
    def _body(self) -> str:
        return _main_script()

    def test_braces_parens_brackets_balanced(self):
        body = self._body()
        for a, b in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(
                body.count(a), body.count(b),
                f"内联 JS 的 {a}{b} 不匹配（{body.count(a)} vs {body.count(b)}），疑似括号失配",
            )

    def test_no_dynamic_code_injection(self):
        body = self._body()
        for needle in ("eval(", "new Function", "document.write"):
            self.assertNotIn(needle, body, f"内联 JS 不应包含 {needle!r}（动态求值/XSS 放大面）")

    def test_key_functions_present(self):
        body = self._body()
        for name in (
            "escapeHtml", "stripAnsi", "cliFailLines", "dotFor",
            "runCli", "showSkillDetail", "confirmModal", "closeModal",
            "showBanner", "renderOverview", "renderAgents",
        ):
            self.assertIn(name, body, f"关键函数 {name!r} 定义缺失，GUI 可能静默失效")


if __name__ == "__main__":
    unittest.main()


class PageRefreshActionTest(unittest.TestCase):
    """每个内容页都必须有一个「重新拉取」的入口（2026-11-05 用户反馈）。

    现象：MCP 页没有刷新按钮，而它的数据来自快照。用户改完配置后回到该页，
    看到的仍是打开 App 时的缓存 —— 实测出现过「改名后页面仍显示旧条目名」，
    让人误以为是重复配置。

    判据：**数据页**的 `.page-head` 必须带 `.page-actions`，且其中至少有一个
    触发重新拉取的按钮。设置页是配置表单（其控件本身就是即时生效的），
    不在此列 —— 用白名单显式排除，而不是放宽到「任意页都不要求」。
    """

    NO_REFRESH_ALLOWED = {"page-settings"}

    def _pages(self) -> dict:
        html = page_html()
        out = {}
        for m in re.finditer(r'<section id="(page-[a-z]+)"[^>]*>(.*?)</section>', html, re.S):
            out[m.group(1)] = m.group(2)
        return out

    def test_every_data_page_offers_a_refresh_action(self):
        pages = self._pages()
        self.assertGreaterEqual(len(pages), 6, "页面区块没解析到，检查 <section id=page-*> 结构")
        missing = []
        for pid, body in pages.items():
            if pid in self.NO_REFRESH_ALLOWED:
                continue
            # page-head 里要有 page-actions，且至少一个 data-action 按钮
            head = re.search(r'<div class="page-head">(.*?)</div>\s*</div>', body, re.S)
            chunk = body[: body.find("</div>\n      <div")] if "</div>\n      <div" in body else body
            if "page-actions" not in chunk or "data-action=" not in chunk:
                missing.append(pid)
        self.assertEqual(
            missing,
            [],
            "以下页面没有刷新入口：用户改完配置回到该页会看到缓存，"
            "误以为改动没生效或出现重复配置：%r" % missing,
        )

    def test_mcp_page_refresh_is_wired(self):
        html = page_html()
        m = re.search(r'<section id="page-mcp".*?</section>', html, re.S)
        self.assertIsNotNone(m)
        self.assertIn("data-action=", m.group(0), "MCP 页缺少刷新按钮")
