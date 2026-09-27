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
    """页面源码，重建为 S10 之前的「单文件」形态（脚本内联在 <script> 里）。

    实测教训：测试里有两类取源写法 ——
      · 直接抽 `function xxx` 的函数体；
      · 用 <script> 标记**切片/正则匹配脚本块**
        （re.search(r"<script>(.*?)</script>")、s.index("<script>")、re.findall(...)）。

    若只是把 HTML 与外置 JS 简单拼接，第二类写法会抓到空串，表现为
    「未找到 <script> 区块」/「substring not found」/「str 无 group 属性」，
    实测一次性打掉约 30 个用例。

    所以这里做「形态还原」：把 <script src="dashboard.js" defer></script>
    换回 <script> …外置脚本全文… </script>。于是两类写法都无需感知脚本放在哪个文件，
    绝大多数测试文件一个字都不用改。

    脚本仍内联时（S10 生效前），本函数与直接读 HTML 逐字节等价。
    """
    key = "source"
    if key not in _cache:
        # 直接读文件，不回绕 page_html()：两者互相调用会无限递归。
        html = HTML.read_text(encoding="utf-8")
        if JS.is_file():
            js = JS.read_text(encoding="utf-8")
            for tag in (
                '<script src="dashboard.js" defer></script>',
                '<script src="dashboard.js"></script>',
            ):
                if tag in html:
                    html = html.replace(tag, "<script>" + chr(10) + js + chr(10) + "</script>", 1)
                    break
        _cache[key] = html
    return _cache[key]
