"""Hook 配置 inventory：读取各客户端生命周期 hooks，产出结构化清单。

参照 ``mcp_inventory`` 的 ``McpEntry`` + ``list_client_mcp_entries`` +
``classify_entries`` 范式（配置 → 读取 → 分类 → 清单）。

数据源权威顺序：
1. ``config.yaml`` 的 ``hooks.clients[]`` 段（声明式，含 config_path /
   hook_key_path / events / template / fix_supported）；
2. 回退到 ``mcp_tools[].hooks_config_path``（兼容字段，仅知路径，不知事件签名）。

ai-memory hook 识别依据（与 ``ai_memory_checker.AI_MEMORY_HOOK_SIGNATURE``
对齐）：命令含 ``ai-memory`` + ``hook --event``，或含 ``ai-memory-hook``。
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from legacy_checker import _load_json_file, _norm_tool_name
from ai_memory_checker import (
    _load_toml_file,
    _find_in_dict,
    _extract_hook_commands,
)


@dataclass
class HookEntry:
    """单个 hook 事件的清单条目。

    与 ``mcp_inventory.McpEntry`` 平行：McpEntry 描述 MCP server 条目，
    HookEntry 描述生命周期 hook 事件条目。
    """

    event: str = ""            # 事件名（SessionStart / sessionStart / ...）
    command: str = ""           # hook 命令字符串
    is_ai_memory: bool = False  # 是否 ai-memory hook（命中签名）


def _is_ai_memory_hook_cmd(cmd: str) -> bool:
    """识别 ai-memory hook 命令。

    标准 CLI（``ai-memory hook --event``）或本机 wrapper（``ai-memory-hook``）。
    与 ``ai_memory_checker`` 的判定保持一致，避免两套签名漂移。
    """
    return ("ai-memory" in cmd and "hook --event" in cmd) or "ai-memory-hook" in cmd


def hooks_client_config(config: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    """从 ``config['hooks']['clients']`` 按 name 匹配客户端 hook 配置。

    回退：若 hooks 段无该客户端，从 ``mcp_tools`` 段的 ``hooks_config_path``
    构造最小配置（仅路径，无事件签名 / template，``fix_supported=False``）。
    """
    hooks = config.get("hooks", {}) or {}
    for cl in hooks.get("clients", []) or []:
        if _norm_tool_name(cl.get("name", "")) == _norm_tool_name(tool_name):
            return cl
    # 回退：mcp_tools 段的 hooks_config_path（兼容字段）
    for t in config.get("mcp_tools", []) or []:
        if _norm_tool_name(t.get("name", "")) == _norm_tool_name(tool_name):
            if t.get("hooks_config_path"):
                return {
                    "name": t["name"],
                    "config_path": t["hooks_config_path"],
                    "format": "json",
                    "hook_key_path": ["hooks"],
                    "fix_supported": False,
                }
            break
    return {}


def list_client_hook_entries(tool: Dict[str, Any], config: Dict[str, Any]) -> List[HookEntry]:
    """读取客户端 hooks 配置，产出 ``HookEntry`` 清单。

    复用 ``ai_memory_checker`` 的解析原语（``_load_json_file`` /
    ``_load_toml_file`` / ``_find_in_dict`` / ``_extract_hook_commands``），
    保证与 ``check_ai_memory_hooks`` 的读取语义一致。
    """
    name = tool.get("name", "")
    hc = hooks_client_config(config, name)
    if not hc:
        return []

    config_path = os.path.expanduser(hc.get("config_path", ""))
    if not os.path.isfile(config_path):
        return []

    # OpenCode：TS 插件形式（非 JSON hooks）
    if hc.get("plugin"):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "ai-memory" in content and ("hook" in content or "session" in content):
                return [HookEntry(event="plugin", command="(TS plugin)", is_ai_memory=True)]
        except OSError:
            pass
        return []

    # JSON / TOML hooks 段
    data = _load_json_file(config_path)
    if data is None:
        data = _load_toml_file(config_path)
    if data is None:
        return []

    hook_keys = hc.get("hook_key_path") or hc.get("hook_keys") or ["hooks"]
    hook_section = _find_in_dict(data, hook_keys)

    # 兼容：Cursor / Codex 的 hooks.json 顶层即事件名（无 "hooks" 包裹）
    if hook_section is None and isinstance(data, dict) and data:
        known_events = set(hc.get("events", []))
        if any(k in known_events for k in data.keys()):
            hook_section = data

    if hook_section is None or not isinstance(hook_section, dict):
        return []

    entries: List[HookEntry] = []
    for event_name, event_hooks in hook_section.items():
        for cmd in _extract_hook_commands(event_hooks):
            entries.append(
                HookEntry(
                    event=event_name,
                    command=cmd,
                    is_ai_memory=_is_ai_memory_hook_cmd(cmd),
                )
            )
    return entries


def inventory_for_tool(tool: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """产出单个客户端的 hooks inventory 摘要。

    供 ``management_snapshot._agent_entry`` 透传进 agents 面板，字段命名与
    mcp 系列对齐（``hooks_config_path`` / ``hooks_configured`` /
    ``hook_events`` / ``hooks_fix_supported``）。
    """
    name = tool.get("name", "")
    hc = hooks_client_config(config, name)
    if not hc:
        return {
            "hooks_config_path": "",
            "hooks_configured": False,
            "hook_events": [],
            "hooks_fix_supported": False,
            "hooks_inventory": [],
        }

    entries = list_client_hook_entries(tool, config)
    ai_events = sorted({e.event for e in entries if e.is_ai_memory})
    expected_events = hc.get("events", [])
    missing_key = [e for e in expected_events if e not in ai_events]

    return {
        "hooks_config_path": hc.get("config_path", ""),
        "hooks_configured": bool(ai_events),
        "hook_events": ai_events,
        "hooks_fix_supported": hc.get("fix_supported", False),
        "hooks_inventory": [
            {"event": e.event, "command": e.command, "is_ai_memory": e.is_ai_memory}
            for e in entries
        ],
        "missing_key_events": missing_key,
    }


def inventory_all(config: Dict[str, Any], tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量产出所有客户端的 hooks inventory 摘要。

    供 ``--list-hooks`` CLI 出口使用。
    """
    return [
        {**{"name": t.get("name", "")}, **inventory_for_tool(t, config)}
        for t in tools
        if hooks_client_config(config, t.get("name", ""))
    ]
