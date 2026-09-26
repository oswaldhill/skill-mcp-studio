#!/usr/bin/env python3
"""把 gui/dashboard.html 拆成 Tauri 实际加载的发布产物（S10：构建期拆分）。

## 为什么是「构建期拆分」而不是「仓库内拆分」

仓库内直接外置脚本（把内联 `<script>` 挪到 `gui/dashboard.js`）会让 20 余个测试文件
失去断言依据 —— 它们靠 `Path("gui/dashboard.html").read_text()` + 正则抽 JS 函数体。
实测过：一次性 114 条断言失败，代价远大于收益（见 `docs/reviews/评审-v0.24.0-待完善清单.md`
的 S10 专节）。

本脚本换个方向：**源文件保持单文件原样**（测试继续测源文件，零改动），
由构建期生成拆分后的发布产物：

    gui/dist/index.html   不含内联 <script>，改为 <script src="app.js" defer></script>
    gui/dist/app.js       原内联脚本全文（逐字节取自源文件）

于是「单文件难以模块化 / 难以测试」的诉求在**发布产物**这一层得到满足，
而源文件与既有测试都不受影响。它同时是「关掉 CSP `'unsafe-inline'`」的前置条件之一
（外置脚本后 `script-src` 才有可能不再需要 `'unsafe-inline'`；样式仍受 77 处内联
`style=` 属性约束，见 S2 专节）。

## 用法

    python3 scripts/build_gui.py            # 生成 gui/dist/
    python3 scripts/build_gui.py --check    # 只校验产物与源文件是否同步（CI 用，不改文件）

## 无损性

拆分是**纯字符串切片**：脚本体逐字节照搬，HTML 其余部分原样保留。
因此把 `<script src="app.js" defer></script>` 换回 `<script>脚本体</script>`
即可**逐字节还原**源文件 —— `tests/test_gui_build_split.py` 守住了这条不变量。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "gui" / "dashboard.html"
DIST = ROOT / "gui" / "dist"
INDEX = DIST / "index.html"
APP_JS = DIST / "app.js"

SCRIPT_OPEN = "<script>"
SCRIPT_CLOSE = "</script>"
SCRIPT_TAG = '<script src="app.js" defer></script>'


def build() -> tuple[str, str]:
    """返回 `(index_html, app_js)`。

    取**最后一个** `</script>`：源文件里内联脚本只有一个，这样写能容忍脚本体内部
    出现字符串 `"</script>"` 的边缘情况。
    """
    html = SRC.read_text(encoding="utf-8")
    i = html.find(SCRIPT_OPEN)
    j = html.rfind(SCRIPT_CLOSE)
    if i < 0 or j < 0 or j < i:
        raise SystemExit(f"源文件里找不到内联 <script> 区块：{SRC}")
    body = html[i + len(SCRIPT_OPEN):j]
    index = html[:i] + SCRIPT_TAG + html[j + len(SCRIPT_CLOSE):]
    return index, body


def main(argv: list[str]) -> int:
    index, app_js = build()

    if "--check" in argv:
        if not (INDEX.is_file() and APP_JS.is_file()):
            print("✗ gui/dist 尚未生成，请运行：python3 scripts/build_gui.py", file=sys.stderr)
            return 1
        same = (
            INDEX.read_text(encoding="utf-8") == index
            and APP_JS.read_text(encoding="utf-8") == app_js
        )
        if not same:
            print(
                "✗ gui/dist 与源文件不同步，请运行：python3 scripts/build_gui.py",
                file=sys.stderr,
            )
            return 1
        print("✓ gui/dist 与源文件同步")
        return 0

    DIST.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(index, encoding="utf-8")
    APP_JS.write_text(app_js, encoding="utf-8")
    print(f"✓ {INDEX.relative_to(ROOT)}  ({index.count(chr(10)) + 1} 行)")
    print(f"✓ {APP_JS.relative_to(ROOT)}  ({app_js.count(chr(10)) + 1} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))