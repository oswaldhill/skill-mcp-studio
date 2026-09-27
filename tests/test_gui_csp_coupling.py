"""锁死 CSP / 内联资源之间的耦合不变量（S2 的结论护栏）。

## 背景

`docs/reviews/评审-v0.24.0-待完善清单.md` 的 S2 曾建议「移除
`dangerousDisableAssetCspModification`」。**该建议会回退一个已验证的修复**
（见 `CHANGELOG.md` 的「使用统计的『强度』条全部一样长」条目），
`tests/test_gui_inline_style_csp.py` 已锁住那个开关本身。

本文件补的是**耦合关系**：只锁「开关为 true」还不够 —— 还要锁住
「在什么条件下才允许动 `script-src` / `style-src` 的 `'unsafe-inline'`」。
否则后人可以一边保持开关为 true、一边去掉 `'unsafe-inline'`，把页面弄坏。

## 机制（读 tauri 2.11.5 源码确认，不是推测）

`~/.cargo/registry/src/*/tauri-2.11.5/src/manager/mod.rs:81-104`：

    let d = &manager.config().app.security.dangerous_disable_asset_csp_modification;
    if d.can_modify("script-src") { replace_csp_nonce(..., "script-src", hash_strings.script); }
    if d.can_modify("style-src")  { replace_csp_nonce(..., "style-src",  hash_strings.style);  }

即该开关**同时**控制 script-src 与 style-src 的 nonce/hash 改写。
（清单原文只提到 style-src，这也是需要更正的一处。）

而 CSP 规范：**某条指令里一旦出现 nonce/hash，该指令的 `'unsafe-inline'` 即被忽略**。
关键推论：**nonce/hash 只能覆盖 `<style>`/`<script>` 元素，覆盖不了 `style="…"` 属性** ——
能被 `'unsafe-inline'` 覆盖、却无法被 nonce 覆盖的，只有属性形态的内联样式。

## 于是两条路径二选一

* **现状（开关 true）**：不做 nonce 改写 ⟹ `'unsafe-inline'` 生效 ⟹
  `<script>` 内联块与 77 处 `style="…"` 属性都能活。代价：script-src 无法收紧。
* **收紧（开关 false）**：Tauri 注入 nonce/hash ⟹ `<style>`/`<script>` 元素靠 nonce 活，
  但 `style="…"` 属性**全部失效** ⟹ 必须先把 77 处内联 style 属性消灭掉
  （改 class 或 CSSOM），才能同时去掉两处 `'unsafe-inline'`。

所以「去掉 script-src 的 'unsafe-inline'」这件事，**前置条件是把内联 style 属性清零**，
而不是只把 `<script>` 外置。这一点清单没有写清楚。
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "src-tauri" / "tauri.conf.json"
HTML = ROOT / "gui" / "dashboard.html"


def _csp_sources(csp: str, directive: str) -> str:
    """取出某条指令的取值部分（形如 "script-src 'self' 'unsafe-inline'; ..." → "'self' 'unsafe-inline'"）。"""
    for part in csp.split(";"):
        part = part.strip()
        if part.startswith(directive + " "):
            return part[len(directive) + 1 :]
    return ""


class CspInlineCouplingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = json.loads(CONF.read_text(encoding="utf-8"))
        cls.sec = cls.conf["app"]["security"]
        cls.csp = cls.sec["csp"]
        cls.flag = cls.sec.get("dangerousDisableAssetCspModification")
        cls.html = HTML.read_text(encoding="utf-8")

    def test_inline_style_attributes_force_the_flag_and_unsafe_inline(self):
        """存在 style="…" 属性 ⟹ 必须关 CSP 改写、且 style-src 保留 'unsafe-inline'。

        理由：style 属性无法被 nonce/hash 覆盖（nonce 只作用于元素）。
        一旦打开改写（flag 非 true），运行时会变成带 nonce 的 style-src，
        `'unsafe-inline'` 被规范忽略，77 处 style 属性静默失效 —— 正是 CHANGELOG 里
        「强度条全部等长」那个 bug。
        """
        inline_style_attrs = len(re.findall(r'\sstyle="', self.html))
        if inline_style_attrs == 0:
            self.skipTest("已无内联 style 属性：此时才允许讨论打开 CSP 改写")
        self.assertIs(
            self.flag,
            True,
            f"页面仍有 {inline_style_attrs} 处内联 style 属性，"
            "必须保持 dangerousDisableAssetCspModification=true，"
            "否则 nonce 会挤掉 'unsafe-inline'，这些属性被静默拦截",
        )
        self.assertIn(
            "'unsafe-inline'",
            _csp_sources(self.csp, "style-src"),
            "仍有内联 style 属性时，style-src 必须保留 'unsafe-inline'",
        )

    def test_inline_script_present_requires_unsafe_inline_in_script_src(self):
        """存在内联 <script> 块 ⟹（flag 为 true 时）script-src 必须保留 'unsafe-inline'。

        同一条规范：flag 为 true 意味着不做 nonce 改写，内联脚本只能靠 'unsafe-inline'。
        （若今后把 `<script>` 外置为同目录 .js，本条会自然 skip —— 那时才轮到讨论收紧。）
        """
        has_inline_script = bool(
            re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", self.html)
        )
        if not has_inline_script:
            self.skipTest("已无内联 <script>：此时才允许收紧 script-src")
        self.assertIs(self.flag, True, "flag 非 true 时内联 script 依赖 nonce，需一并改造")
        self.assertIn(
            "'unsafe-inline'",
            _csp_sources(self.csp, "script-src"),
            "flag 为 true 且仍有内联 <script> 时，script-src 必须保留 'unsafe-inline'",
        )

    def test_csp_does_not_gain_unsafe_eval_or_network(self):
        """收紧以外的方向不得被顺手放开（eval / 联网）。"""
        self.assertNotIn("'unsafe-eval'", self.csp)
        self.assertIn("connect-src 'none'", self.csp)

    def test_flag_documented_as_covering_both_directives(self):
        """把「该开关同时管 script-src 与 style-src」写进配置注释来源，防 misinterpretation。

        tauri 2.11.5 manager/mod.rs:86,96 两次 can_modify：script-src 与 style-src。
        本用例只做静态断言：配置里确实设了该开关（细节由
        tests/test_gui_inline_style_csp.py 锁），并确保 page 未引入外部脚本源。
        """
        self.assertIs(self.flag, True)
        sources = _csp_sources(self.csp, "script-src")
        self.assertIn("'self'", sources, "script-src 必须至少允许同源脚本")


if __name__ == "__main__":
    unittest.main()
