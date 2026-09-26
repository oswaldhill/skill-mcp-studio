"""页面源码的统一取源口（S10 前置重构）。

## 为什么需要它

此前有约 20 个测试文件各自写 `Path("gui/dashboard.html").read_text()` 再从里面
**正则抽 JS 函数体**来断言。这使测试与「页面脚本放在哪个文件」这个**纯布局细节**耦合：
S10 一旦把内联 `<script>` 外置到 `gui/dashboard.js`，15 个文件的 114 条断言立刻失败
（实测过，随后回退）。

本模块把取源收敛到一处，两种形态都支持：

* **现在**：脚本内联在 `dashboard.html` 里 → 返回 HTML 全文（含脚本），与旧行为一致；
* **外置后**：`dashboard.html` 用 `<script src="dashboard.js">` 引用 →
  返回 `HTML + 外置 .js 内容`，于是所有「抽函数体」的断言**照旧可用**。

也就是说：先落地本模块（此时行为与旧写法逐字节等价），S10 再外置脚本时就不会打断任何断言。

## 用法

    from tests._gui_source import page_source, page_html

    page_html()    # 纯 HTML（断言 DOM/CSS/结构时用这个）
    page_source()  # HTML + 页面脚本（断言 JS 函数体时用这个）
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
JS = ROOT / "gui" / "dashboard.js"

_cache: dict[str, str] = {}


def page_html() -> str:
    """页面 HTML 原文（不含外置脚本）。"""
    key = "html"
    if key not in _cache:
        _cache[key] = HTML.read_text(encoding="utf-8")
    return _cache[key]


def page_source() -> str:
    """HTML + 页面脚本（内联或外置，两者都覆盖）。

    取源顺序：先 HTML 全文；若 HTML 里已有内联 `<script>`（无 src），它已包含脚本；
    若脚本已外置（存在 `gui/dashboard.js` 且 HTML 用 src 引用），则把外置内容一并接上。
    """
    key = "source"
    if key not in _cache:
        html = page_html()
        parts = [html]
        if JS.is_file():
            parts.append(JS.read_text(encoding="utf-8"))
        _cache[key] = "\n".join(parts)
    return _cache[key]
