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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui" / "dashboard.html"


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