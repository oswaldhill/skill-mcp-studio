"""高风险 MCP 条目判定：识别「疑似客户端自带」的条目。

客户端自带条目（如 Codex 内嵌在 ChatGPT.app 里的 node_repl / computer-use）
删掉会破坏该客户端能力；而用户自建条目（如 image-vision、context7）恰恰是最想
清理的对象。二者都落在 ``unmanaged`` 分类里，只能靠启发式区分。

规则：
- R1 条目的 command / args 中绝对路径落在该客户端 ``app_bundles`` 任一前缀下；
- R2 路径含 ``.app/Contents/``（覆盖 ``./Codex Computer Use.app/...`` 这类相对路径）；
- R3 条目 key 归一化后等于客户端名或其 alias 之一。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from tool_registry import expand_path, normalized_name

_APP_CONTENTS = ".app/contents/"


def _bundle_prefixes(tool: Dict[str, Any]) -> List[str]:
    """客户端 app bundle 路径前缀（归一化、去尾斜杠）。"""
    prefixes: List[str] = []
    for raw in tool.get("app_bundles") or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        prefix = os.path.normpath(expand_path(raw.strip())).replace("\\", "/")
        prefixes.append(prefix.rstrip("/"))
    return prefixes


def _entry_paths(entry: Dict[str, Any]) -> List[str]:
    """条目里可能承载可执行/脚本路径的字符串。"""
    paths: List[str] = []
    command = entry.get("command")
    if isinstance(command, str) and command.strip():
        paths.append(command.strip())
    for arg in entry.get("args") or []:
        if isinstance(arg, str) and arg.strip():
            paths.append(arg.strip())
    return paths


def _matching_bundle(path: str, prefixes: List[str]) -> str:
    """命中的 bundle 前缀；未命中返回空串。仅对绝对路径生效。"""
    if not os.path.isabs(path):
        return ""
    norm = os.path.normpath(path).replace("\\", "/")
    for prefix in prefixes:
        if norm == prefix or norm.startswith(prefix + "/"):
            return prefix
    return ""


def is_high_risk_entry(entry: Dict[str, Any], tool: Dict[str, Any]) -> Tuple[bool, str]:
    """返回 ``(high_risk, reason)``。

    非高风险时 ``reason`` 为空串；高风险时给出可直接展示给用户的中文原因。
    """
    raw_key = entry.get("key")
    key = raw_key if isinstance(raw_key, str) else ""
    norm_key = normalized_name(key)

    if norm_key:
        candidates: List[Any] = [tool.get("name") or ""]
        candidates.extend(tool.get("aliases") or [])
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate:
                continue
            if normalized_name(candidate) == norm_key:
                return True, f"条目名与客户端同名（{key}）"

    prefixes = _bundle_prefixes(tool)
    for path in _entry_paths(entry):
        matched = _matching_bundle(path, prefixes)
        if matched:
            return True, f"命令位于 {matched} 内（客户端自带）"
        if _APP_CONTENTS in path.replace("\\", "/").lower():
            return True, f"命令位于应用包内（{path}）"

    return False, ""
