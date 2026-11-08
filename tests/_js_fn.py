"""从管理台脚本里**精确**抽出一个函数的源码。

## 为什么需要这个模块（2026-11-08）

各 GUI 测试此前各自写了一个 `_fn()`，两种写法都不可靠：

1. `re.search(r"function X\\(.*?\\n\\}", src, re.S)` —— `\\n\\}` 只匹配**零缩进**的
   右花括号。而管理台里绝大多数函数是 `  function X(...)`（缩进两格），收尾是
   `\\n  }`，于是匹配不到，正则一路吃到**下一个零缩进函数**的末尾。
   实测 `renderMarketProgress` 真实 221 字节，被抽成 43,723 字节（198 倍），
   顺带把二十几个无关函数裹进了断言范围。

2. `s.index("function X(")` + `s.index("\\n  }")` —— 会切在**第一个**同缩进的
   内部块（`if` / `for` 的收尾）上，抽出来的函数体是残缺的。

两种错法都**不会报错**，只会让断言静默地检查错东西：前者的断言可能因为别的
函数里恰好有某个字符串而"通过"，后者的断言可能永远看不到真正要查的代码。

## 做法

按**大括号配平**抽取，并先剥离字符串与注释 —— 否则字符串里的 `}`（比如
`"${a}"`、`'{'`）会把深度算错。剥离复用 `test_dashboard_usage_ui` 里同一份
实现，保证两处对"什么是字符串/注释"的理解一致。

## 行为

- 找不到函数 → 抛 `KeyError`（带函数名），不让调用方拿到空串后静默断言；
- 支持 `function X(` 与 `async function X(`；
- 返回**含** `function` 关键字到配对右花括号的整段源码。
"""

from __future__ import annotations

import re
from typing import Optional


def _strip_strings_and_comments(code: str) -> str:
    """抹掉字符串/模板串/注释，但保留 `${...}` 里的真实代码。

    与 `test_dashboard_usage_ui` 里的同名函数保持同一语义（含对 `${}` 内
    引号的感知，见那里的说明）。这里独立实现一份，避免测试模块之间互相 import
    造成的循环与脆弱耦合。
    """
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            i += 2
            while i < n - 1 and not (code[i] == "*" and code[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            while i < n:
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == quote:
                    i += 1
                    break
                if code[i] == "\n":
                    break
                i += 1
            out.append(" ")
            continue
        if c == "`":
            i += 1
            while i < n:
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == "`":
                    i += 1
                    break
                if code[i] == "$" and i + 1 < n and code[i + 1] == "{":
                    depth, start = 1, i + 2
                    j = start
                    in_str: Optional[str] = None
                    while j < n and depth:
                        ch = code[j]
                        if in_str:
                            if ch == "\\":
                                j += 2
                                continue
                            if ch == in_str:
                                in_str = None
                            j += 1
                            continue
                        if ch in ("'", '"', "`"):
                            in_str = ch
                            j += 1
                            continue
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                        j += 1
                    out.append(_strip_strings_and_comments(code[start:j - 1]))
                    i = j
                    continue
                i += 1
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_function_start(src: str, name: str) -> Optional[int]:
    pattern = re.compile(r"^\s*(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", re.M)
    m = pattern.search(src)
    return m.start() if m else None


def _skip_literal_or_comment(src: str, i: int) -> int:
    """若 ``src[i]`` 处是字符串/模板串/注释，返回其**之后**的下标；否则返回 ``i``。

    就地扫描而不预先生成剥离副本：剥离会把多字符的字符串替换成单个空格，
    长度一变，按索引回原文就会错位（实测原文 501187 → 剥离 226675）。
    """
    n = len(src)
    c = src[i]
    nxt = src[i + 1] if i + 1 < n else ""
    if c == "/" and nxt == "/":
        while i < n and src[i] != "\n":
            i += 1
        return i
    if c == "/" and nxt == "*":
        i += 2
        while i < n - 1 and not (src[i] == "*" and src[i + 1] == "/"):
            i += 1
        return min(i + 2, n)
    if c in ("'", '"'):
        quote = c
        i += 1
        while i < n:
            if src[i] == "\\":
                i += 2
                continue
            if src[i] == quote:
                return i + 1
            if src[i] == "\n":      # 未闭合，按行截断
                return i
            i += 1
        return i
    if c == "`":
        i += 1
        while i < n:
            if src[i] == "\\":
                i += 2
                continue
            if src[i] == "`":
                return i + 1
            i += 1
        return i
    return i


def extract_function(src: str, name: str) -> str:
    """按大括号配平抽出 `function name(...) {...}` 的完整源码。

    参数区里也可能有大括号（默认值 `{}`），因此先定位参数表闭合的 `)`，
    再从它之后找函数体的 `{`。字符串与注释在扫描时**跳读**，其中的括号不计数。
    """
    start = _find_function_start(src, name)
    if start is None:
        raise KeyError(f"未找到函数 {name}")

    n = len(src)

    # 1) 跳到参数表左括号
    i = start
    while i < n and src[i] != "(":
        i = _skip_literal_or_comment(src, i)
        if i < n and src[i] != "(":
            i += 1

    # 2) 参数表配平
    depth_p = 0
    while i < n:
        nxt_i = _skip_literal_or_comment(src, i)
        if nxt_i != i:
            i = nxt_i
            continue
        ch = src[i]
        if ch == "(":
            depth_p += 1
        elif ch == ")":
            depth_p -= 1
            if depth_p == 0:
                i += 1
                break
        i += 1

    # 3) 找函数体左花括号
    while i < n and src[i] != "{":
        nxt_i = _skip_literal_or_comment(src, i)
        if nxt_i != i:
            i = nxt_i
            continue
        i += 1

    # 4) 函数体配平
    depth = 0
    while i < n:
        nxt_i = _skip_literal_or_comment(src, i)
        if nxt_i != i:
            i = nxt_i
            continue
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1

    raise ValueError(f"函数 {name} 的大括号未配平（文件可能被截断）")


def make_fn(src_getter):
    """生成一个 `_fn(name)` 便捷函数，供各测试模块直接赋值使用。"""

    def _fn(name: str) -> str:
        return extract_function(src_getter(), name)

    return _fn
