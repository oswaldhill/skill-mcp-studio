"""工具路径覆盖：用户修正内置注册表的默认路径。

背景（2026-11-10 用户反馈）：「路径识别不正确，比如默认获取的路径是这个，
但实际上可能是另外一个，我该怎么进行修改？这个功能是否缺失了？」

内置注册表（``mainstream_registry_data`` / ``mainstream_registry_extra``）里
APP / CLI / CONFIG / SKILLS / MCP / RULES 都是**厂商默认值**。本机装到别处、
或者厂商改了落盘位置时，此前没有任何修正入口——这确实是缺失。

覆盖层落在 ``data/local_overrides.yaml`` 的 ``tool_paths`` 段（该目录已
gitignore，机器本地路径不进版本库）：

```yaml
tool_paths:
  TRAE:
    config_paths: ["~/custom/mcp.json"]
    skills_path: "~/custom/skills"
```

只覆盖**路径类字段**；工具名、类型、别名一律不动，避免覆盖层变成第二个注册表。
"""

import copy
import os
from typing import Any, Dict, List, Optional

import yaml


# 可覆盖字段 → (嵌套在 install 下?, 注册表里的键名)
_FIELDS: Dict[str, tuple] = {
    "app_bundles": ("install", "app_bundles"),
    "commands": ("install", "commands"),
    "config_paths": ("install", "config_paths"),
    "skills_path": (None, "skills_path"),
    "mcp_config_path": (None, "config_path"),
    "rules_paths": (None, "rules_paths"),
}

FIELD_NAMES: List[str] = list(_FIELDS)


def _overrides_file() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "local_overrides.yaml")
    )


def _read_file() -> Dict[str, Any]:
    path = _overrides_file()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_file(data: Dict[str, Any]) -> None:
    path = _overrides_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    os.replace(tmp, path)


def load_tool_paths() -> Dict[str, Dict[str, Any]]:
    """读出 ``tool_paths`` 段；结构非法时返回空字典（不让坏 YAML 炸掉启动）。"""
    raw = _read_file().get("tool_paths")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for tool, fields in raw.items():
        if not isinstance(tool, str) or not isinstance(fields, dict):
            continue
        clean = {k: v for k, v in fields.items() if k in _FIELDS}
        if clean:
            out[tool] = clean
    return out


def _as_list(value: Any) -> List[str]:
    """把单值 / 列表 / 换行分隔的字符串统一成列表。

    GUI 的多值字段（一个字段可能有多条路径）用换行拼接后作为一个参数传进来，
    这里按行拆开；**不拆逗号**——路径里出现逗号比换行常见得多。
    """
    if value is None:
        return []
    if isinstance(value, str):
        if "\n" in value:
            return [x.strip() for x in value.splitlines() if x.strip()]
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value if str(x).strip()]
    return [str(value)]


def apply_overrides(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把覆盖层合并进工具清单（**深拷贝**，不污染模块级注册表）。"""
    overrides = load_tool_paths()
    if not overrides:
        return tools
    out: List[Dict[str, Any]] = []
    for tool in tools:
        item = copy.deepcopy(tool)
        patch = overrides.get(item.get("name"))
        if patch:
            for field, value in patch.items():
                nested, key = _FIELDS[field]
                target = item.setdefault("install", {}) if nested else item
                if field == "mcp_config_path":
                    target["config_path"] = _as_list(value)[0] if _as_list(value) else ""
                else:
                    target[key] = _as_list(value)
        out.append(item)
    return out


def set_tool_path(tool: str, field: str, value: Any) -> Dict[str, Any]:
    """写入一条覆盖。返回 ``{"ok": bool, "reason": str, ...}``。"""
    if field not in _FIELDS:
        return {"ok": False, "reason": f"不支持的字段 {field}；可用：{', '.join(FIELD_NAMES)}"}
    data = _read_file()
    tool_paths = data.get("tool_paths")
    if not isinstance(tool_paths, dict):
        tool_paths = {}
    entry = tool_paths.get(tool)
    if not isinstance(entry, dict):
        entry = {}
    if field == "mcp_config_path":
        values = _as_list(value)
        entry[field] = values[0] if values else ""
    else:
        entry[field] = _as_list(value)
    if not entry.get(field) and field != "mcp_config_path":
        entry.pop(field, None)
    if entry:
        tool_paths[tool] = entry
    else:
        tool_paths.pop(tool, None)
    if tool_paths:
        data["tool_paths"] = tool_paths
    else:
        data.pop("tool_paths", None)
    _write_file(data)
    return {"ok": True, "tool": tool, "field": field, "value": entry.get(field, "")}


def reset_tool_path(tool: str, field: Optional[str] = None) -> Dict[str, Any]:
    """清除覆盖：给 field 只清该字段，不给则清整个工具。"""
    data = _read_file()
    tool_paths = data.get("tool_paths")
    if not isinstance(tool_paths, dict) or tool not in tool_paths:
        return {"ok": False, "reason": f"{tool} 没有覆盖记录"}
    if field:
        if field not in _FIELDS:
            return {"ok": False, "reason": f"不支持的字段 {field}"}
        entry = tool_paths.get(tool) or {}
        entry.pop(field, None)
        if entry:
            tool_paths[tool] = entry
        else:
            tool_paths.pop(tool, None)
    else:
        tool_paths.pop(tool, None)
    if tool_paths:
        data["tool_paths"] = tool_paths
    else:
        data.pop("tool_paths", None)
    _write_file(data)
    return {"ok": True, "tool": tool, "field": field or "*"}
