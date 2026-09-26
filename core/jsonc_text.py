"""JSONC 文本级操作：注释屏蔽 + 按字节范围定点删除对象成员（纯函数、无 I/O）。

设计约束（不要改成「解析后再序列化」）：删除**不做** ``json.loads`` → 改 dict →
``json.dumps``——那会丢注释、丢缩进、丢键序。这里只按字节范围删掉目标成员自身与
一个分隔逗号，其余每一个字节（注释、空白、缩进、键序、其他成员）原样保留；与
``core/mcp_fixer.py`` 的 TOML 分支（``_toml_section_tree_ranges`` + 文本切片）同一思路。

对外 API：

* :func:`mask_jsonc_comments` —— 注释逐字符替换为空格（保留换行），长度与偏移和原文
  一一对应；用于「按 JSON 解析做校验」时屏蔽注释。正确处理字符串字面量与转义，
  ``"https://x"`` 里的 ``//`` 不会被误判为注释。
* :func:`remove_object_members` —— 在 ``key_path`` 指向的对象内删除指定名字的成员；
  未命中任何 key 时返回**字节相同**的原文。
* :func:`member_ranges` / :func:`locate_object` —— 便于测试定位的内部可见函数。

扫描器只在能安全定位时动手：结构异常（根不是对象、括号未闭合、key 不是字符串、
``key_path`` 指向的值存在但不是对象）一律抛 :class:`JsoncStructureError`
（``ValueError`` 子类），由调用方走既有的 ``error`` 路径，绝不静默降级成别种语义。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

_WHITESPACE = " \t\r\n"
_VALUE_END = ",}]"


class JsoncStructureError(ValueError):
    """JSONC 文本结构异常，无法安全定位目标成员。"""


def _skip_string(text: str, index: int) -> int:
    """``index`` 指向开引号；返回闭引号之后的下标。未闭合则抛错。"""
    quote = text[index]
    i = index + 1
    length = len(text)
    while i < length:
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == quote:
            return i + 1
        i += 1
    raise JsoncStructureError("unterminated string literal")


def _comment_end(text: str, index: int) -> Optional[int]:
    """``index`` 指向 ``/``；是注释则返回注释结束下标（行注释不含换行），否则 None。"""
    if text.startswith("//", index):
        newline = text.find("\n", index)
        return len(text) if newline < 0 else newline
    if text.startswith("/*", index):
        end = text.find("*/", index + 2)
        if end < 0:
            raise JsoncStructureError("unterminated block comment")
        return end + 2
    return None


def _skip_trivia(text: str, index: int) -> int:
    """跳过空白与注释，返回首个有语义字符的下标（可能等于 ``len(text)``）。"""
    i = index
    length = len(text)
    while i < length:
        char = text[i]
        if char in _WHITESPACE:
            i += 1
            continue
        if char == "/":
            end = _comment_end(text, i)
            if end is not None:
                i = end
                continue
        break
    return i


def _skip_value(text: str, index: int) -> int:
    """``index`` 指向值的首字符；返回值结束（不含尾随空白/注释）的下标。"""
    if index >= len(text):
        raise JsoncStructureError("unexpected end of input")
    char = text[index]
    if char == '"':
        return _skip_string(text, index)
    if char == "{":
        _, end = _parse_object(text, index)
        return end
    if char == "[":
        return _skip_array(text, index)
    # 数字 / true / false / null：读到分隔符或注释起始为止。
    i = index
    length = len(text)
    while i < length:
        char = text[i]
        if char in _WHITESPACE or char in _VALUE_END:
            break
        if char == "/" and _comment_end(text, i) is not None:
            break
        i += 1
    if i == index:
        raise JsoncStructureError(f"unexpected character {text[index]!r}")
    return i


def _decode_key(raw: str) -> str:
    """把对象的键字面量（含引号）解码为 Python 字符串。"""
    try:
        value = json.loads(raw)
    except ValueError:
        return raw[1:-1]
    return value if isinstance(value, str) else raw[1:-1]


def _parse_object(text: str, index: int) -> Tuple[List[Dict[str, Any]], int]:
    """``index`` 指向 ``{``；返回 ``(members, end)``，``end`` 为闭括号之后的下标。

    member 字典字段：``name`` / ``name_start`` / ``name_end`` / ``value_start`` /
    ``value_end`` / ``comma_before`` / ``comma_after``（无逗号则为 None）。逗号偏移
    在扫描时顺带记录，删除时据此精确定位分隔符。
    """
    if index >= len(text) or text[index] != "{":
        raise JsoncStructureError("expected object")
    members: List[Dict[str, Any]] = []
    previous_comma: Optional[int] = None
    i = index + 1
    while True:
        i = _skip_trivia(text, i)
        if i >= len(text):
            raise JsoncStructureError("unterminated object")
        if text[i] == "}":
            return members, i + 1
        if text[i] != '"':
            raise JsoncStructureError(
                f"object key must be a string literal, found {text[i]!r}"
            )
        name_start = i
        name_end = _skip_string(text, i)
        name = _decode_key(text[name_start:name_end])
        i = _skip_trivia(text, name_end)
        if i >= len(text) or text[i] != ":":
            raise JsoncStructureError("expected ':' after object key")
        i = _skip_trivia(text, i + 1)
        value_start = i
        value_end = _skip_value(text, i)
        member: Dict[str, Any] = {
            "name": name,
            "name_start": name_start,
            "name_end": name_end,
            "value_start": value_start,
            "value_end": value_end,
            "comma_before": previous_comma,
            "comma_after": None,
        }
        members.append(member)
        i = _skip_trivia(text, value_end)
        if i >= len(text):
            raise JsoncStructureError("unterminated object")
        if text[i] == ",":
            member["comma_after"] = i
            previous_comma = i
            i += 1
            continue
        if text[i] == "}":
            return members, i + 1
        raise JsoncStructureError(f"expected ',' or '}}', found {text[i]!r}")


def _skip_array(text: str, index: int) -> int:
    """``index`` 指向 ``[``；返回闭方括号之后的下标。"""
    if index >= len(text) or text[index] != "[":
        raise JsoncStructureError("expected array")
    i = index + 1
    while True:
        i = _skip_trivia(text, i)
        if i >= len(text):
            raise JsoncStructureError("unterminated array")
        if text[i] == "]":
            return i + 1
        i = _skip_value(text, i)
        i = _skip_trivia(text, i)
        if i >= len(text):
            raise JsoncStructureError("unterminated array")
        if text[i] == ",":
            i += 1
            continue
        if text[i] == "]":
            return i + 1
        raise JsoncStructureError(f"expected ',' or ']', found {text[i]!r}")


def mask_jsonc_comments(text: str) -> str:
    """把 JSONC 注释的每个字符替换为空格，保留换行；字符串字面量原样保留。

    结果与原文**长度完全一致、偏移一一对应**，因此可以直接交给 ``json.loads``
    做校验。行注释掩到行尾（不含 ``\\n``）；块注释掩到 ``*/``（含），其中的换行
    保持不动。字符串内的 ``//`` / ``/*`` 以及 ``\\"`` 转义不会误判。
    """
    out = list(text)
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        if char == '"':
            # 字符串内部逐字保留；未闭合的字符串不抛错（交给 json.loads 报错）。
            i += 1
            while i < length:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if char == "/":
            if text.startswith("//", i):
                end = text.find("\n", i)
                end = length if end < 0 else end
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                end = length if end < 0 else end + 2
            else:
                i += 1
                continue
            for offset in range(i, end):
                if out[offset] != "\n":
                    out[offset] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def locate_object(text: str, key_path: Sequence[str]) -> Optional[int]:
    """定位 ``key_path`` 指向的对象，返回其 ``{`` 下标。

    * ``key_path`` 为空 → 根对象。
    * 路径中某个 key 不存在，或值为 JSON ``null`` → 返回 ``None``（调用方原样返回）。
    * 结构异常 → 抛 :class:`JsoncStructureError`。
    """
    i = _skip_trivia(text, 0)
    if i >= len(text):
        raise JsoncStructureError("empty document")
    if text[i] != "{":
        raise JsoncStructureError("document root is not an object")
    for key in key_path:
        members, _ = _parse_object(text, i)
        found = None
        for member in members:
            if member["name"] == key:
                found = member
        if found is None:
            return None
        i = _skip_trivia(text, found["value_start"])
        if i >= len(text):
            raise JsoncStructureError("unexpected end of input")
        if text[i] == "n" and text[found["value_start"]:found["value_end"]] == "null":
            return None
        if text[i] != "{":
            raise JsoncStructureError("configured MCP key is not an object")
    return i


def _selected_members(
    text: str, key_path: Sequence[str], keys: Set[str]
) -> Optional[Tuple[List[Dict[str, Any]], List[int]]]:
    """返回 ``(全部成员, 命中成员的序号)``；目标对象缺失时返回 None。"""
    container = locate_object(text, key_path)
    if container is None:
        return None
    members, _ = _parse_object(text, container)
    selected = [index for index, member in enumerate(members) if member["name"] in keys]
    return members, selected


def member_ranges(
    text: str, key_path: Sequence[str], keys: Sequence[str]
) -> List[Tuple[int, int]]:
    """命中成员的 ``(name_start, value_end)`` 字节范围（不含分隔逗号），升序。"""
    targets = {key for key in keys if isinstance(key, str)}
    if not targets:
        return []
    located = _selected_members(text, list(key_path or []), targets)
    if located is None:
        return []
    members, selected = located
    return [
        (members[index]["name_start"], members[index]["value_end"])
        for index in selected
    ]


def _merge_ranges(ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    merged: List[Tuple[int, int]] = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _deletion_ranges(
    members: List[Dict[str, Any]], selected: List[int]
) -> List[Tuple[int, int]]:
    """把命中成员切成**连续段**，为每段算删除范围（成员自身 + 分隔逗号）。

    逗号规则（段 = 相邻命中成员 ``[start, end]``）：

    * 段内每个成员删掉**自己的后随逗号**——对段内成员是段内分隔符，对段末成员
      则是连接下一个保留成员的逗号（整段在对象头部 / 中间时都成立，且单成员删除
      与「删成员 + 它的尾随逗号」的朴素写法逐字节一致）；
    * 段**收尾于对象末成员**（``end`` 为末成员）时，还要删掉段首成员**前面的**
      那个逗号——它连接上一个保留成员，不删就会悬挂成尾随逗号
      （``json.loads``: Illegal trailing comma）。末成员的尾随逗号也一并删。
    * 整对象全删时没有保留成员，只需额外删尾随逗号。

    单独删一个尾成员时 ``start == end``，此规则退化成「删前置逗号 + 尾随逗号」，
    与朴素写法一致。
    """
    ranges: List[Tuple[int, int]] = []
    last_index = len(members) - 1
    selected_set = set(selected)
    index = 0
    while index < len(members):
        if index not in selected_set:
            index += 1
            continue
        run_start = index
        while index + 1 < len(members) and index + 1 in selected_set:
            index += 1
        run_end = index

        for position in range(run_start, run_end + 1):
            member = members[position]
            ranges.append((member["name_start"], member["value_end"]))
            comma = member["comma_after"]
            if comma is not None:
                ranges.append((comma, comma + 1))
        if run_end == last_index and run_start > 0:
            before = members[run_start]["comma_before"]
            if before is not None:
                ranges.append((before, before + 1))
        index += 1
    return ranges


def remove_object_members(
    text: str, key_path: Sequence[str], keys: Sequence[str]
) -> str:
    """在 ``key_path`` 指向的对象内删除名字在 ``keys`` 中的成员。

    删除范围 = 命中成员自身 + 必要的分隔逗号（首/中/尾成员与连续多成员成组，
    含尾随逗号），见 :func:`_deletion_ranges`。除此以外的每一个字节都保持原样；
    **未命中任何 key 时返回输入本身**（字节相同）。结构异常抛
    :class:`JsoncStructureError`；删除后还会重新扫描整个文档做结构自检，不自洽则
    抛错（不返回损坏文本）。
    """
    targets = {key for key in keys if isinstance(key, str)}
    if not targets:
        return text
    located = _selected_members(text, list(key_path or []), targets)
    if located is None:
        return text
    members, selected = located
    if not selected:
        return text

    rendered = text
    for start, end in reversed(_merge_ranges(_deletion_ranges(members, selected))):
        rendered = rendered[:start] + rendered[end:]

    # 结构自检：确认删除没有破坏嵌套结构（括号/引号仍自洽）。
    check = _skip_trivia(rendered, 0)
    if check >= len(rendered) or rendered[check] != "{":
        raise JsoncStructureError("document root is not an object")
    _parse_object(rendered, check)
    return rendered
