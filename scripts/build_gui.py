#!/usr/bin/env python3
"""把 gui/dashboard.html 拆成 Tauri 实际加载的发布产物（S10：构建期拆分）。

## 为什么是「构建期拆分」而不是「仓库内拆分」

仓库内直接外置脚本（把内联 `<script>` 挪到 `gui/dashboard.js`）会让 20 余个测试文件
失去断言依据 —— 它们靠 `Path("gui/dashboard.html").read_text()` + 正则抽 JS 函数体。
实测过：一次性 114 条断言失败，代价远大于收益（见 `docs/reviews/评审-v0.24.0-待完善清单.md`
的 S10 专节）。

本脚本换个方向：**源文件保持单文件原样**（测试继续测源文件，零改动），
由构建期生成拆分后的发布产物：

    gui/dist/dashboard.html   不含内联 <script>，改为 <script src="app.js" defer></script>
    gui/dist/app.js           原内联脚本全文（逐字节取自源文件）

产物里 HTML 仍叫 `dashboard.html`：`tauri.conf.json` 的 `windows[0].url` 就是
`dashboard.html`，同名可少改一处、少一个出错点。

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

## 在哪被调用

`src-tauri/tauri.conf.json` 的 `build.beforeBuildCommand`：
`tauri build`（三平台发行构建）会先跑本脚本，因此产物不会缺。
`tauri dev` 不会跑它，本地若要 `tauri dev` 且改过源文件，手动跑一次即可。
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "gui" / "dashboard.html"
DIST = ROOT / "gui" / "dist"
INDEX = DIST / "dashboard.html"
APP_JS = DIST / "app.js"
ASSETS = ROOT / "gui" / "assets"

SCRIPT_OPEN = "<script>"
SCRIPT_CLOSE = "</script>"
SCRIPT_TAG = '<script src="app.js" defer></script>'


def build() -> tuple[str, str]:
    """返回 `(dist_html, app_js)`。

    取**最后一个** `</script>`：源文件里内联脚本只有一个，这样写能容忍脚本体内部
    出现字符串 `"</script>"` 的边缘情况。
    """
    html = SRC.read_text(encoding="utf-8")
    i = html.find(SCRIPT_OPEN)
    j = html.rfind(SCRIPT_CLOSE)
    if i < 0 or j < 0 or j < i:
        raise SystemExit(f"源文件里找不到内联 <script> 区块：{SRC}")
    body = html[i + len(SCRIPT_OPEN):j]
    return html[:i] + SCRIPT_TAG + html[j + len(SCRIPT_CLOSE):], body


def missing_assets(dist_html: str) -> list[str]:
    """列出页面引用、但产物目录里缺失的静态资源（相对路径）。

    为什么要查这个：Tauri 只嵌入 `frontendDist` 这一个目录。页面除了 `app.js`，
    还在 `@font-face` 里用 `url('assets/fonts/*.woff2')` 引用字体 ——
    这些不能只留在 `gui/assets/`，必须一并进产物目录，否则打出来的包会缺字体
    （表现为界面回退到系统等宽字体，且控制台有 404）。
    """
    refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", dist_html)
    refs += re.findall(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", dist_html)
    missing = []
    for ref in refs:
        if ref.startswith(("data:", "blob:", "#", "http://", "https://", "//")):
            continue
        rel = ref.split("?", 1)[0].split("#", 1)[0]
        if not rel or rel.startswith("/"):
            continue
        if not (DIST / rel).is_file() and rel not in missing:
            missing.append(rel)
    return missing


def main(argv: list[str]) -> int:
    dist_html, app_js = build()

    if "--check" in argv:
        if not (INDEX.is_file() and APP_JS.is_file()):
            print("✗ gui/dist 尚未生成，请运行：python3 scripts/build_gui.py", file=sys.stderr)
            return 1
        # 按字节比较（不是 read_text）：read_text 走 universal newlines，会把
        # CRLF 归一成 LF —— 那样在 Windows 上生成的 CRLF 产物会被误判为「同步」，
        # 检测不出换行漂移。按字节比才抓得住。
        same = (
            INDEX.read_bytes() == dist_html.encode("utf-8")
            and APP_JS.read_bytes() == app_js.encode("utf-8")
        )
        if not same:
            print(
                "✗ gui/dist 与源文件不同步，请运行：python3 scripts/build_gui.py",
                file=sys.stderr,
            )
            return 1
        missing = missing_assets(dist_html)
        if missing:
            print(
                "✗ 产物缺少页面引用的静态资源：" + "、".join(missing)
                + "（请运行：python3 scripts/build_gui.py）",
                file=sys.stderr,
            )
            return 1
        print("✓ gui/dist 与源文件同步")
        return 0

    DIST.mkdir(parents=True, exist_ok=True)
    # newline="\n" 必须显式指定：默认会做「换行翻译」，在 Windows 上把 \n
    # 写成 \r\n —— 产物与仓库的 LF 约定不一致，且会让下游按字节数断言的地方
    # （tools/dash_crash_harness.js）对不上。
    # 用显式 open(..., newline=) 而非 Path.write_text(newline=)：后者是 3.10+
    # 才有的参数，而 macOS 自带 CLT python3 是 3.9（beforeBuildCommand 里的
    # `python3` 会解析到它），用了会直接 TypeError。
    for path, text in ((INDEX, dist_html), (APP_JS, app_js)):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    print(f"✓ {INDEX.relative_to(ROOT)}  ({dist_html.count(chr(10)) + 1} 行)")
    print(f"✓ {APP_JS.relative_to(ROOT)}  ({app_js.count(chr(10)) + 1} 行)")

    # 字体等静态资源必须一并进产物目录：
    # 页面在 @font-face 里用 url('assets/fonts/*.woff2') 引用它们，
    # 而 Tauri 只嵌入 frontendDist 这一个目录 —— 不复制就会打出「缺字体」的包。
    if ASSETS.is_dir():
        shutil.copytree(ASSETS, DIST / "assets", dirs_exist_ok=True)
        n = sum(1 for p in (DIST / "assets").rglob("*") if p.is_file())
        print(f"✓ {ASSETS.relative_to(ROOT)} → dist/assets  ({n} 个文件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
