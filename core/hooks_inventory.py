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
from typing import Any, Dict, List, Optional

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


def event_name_for_client(canonical: str, event_format: Optional[str]) -> str:
    """把**标准事件名**转成某客户端的事件名规范。

    为什么需要它：各客户端的 hook 事件名大小写规范不同（Claude Code / Codex /
    WorkBuddy 用 PascalCase，Cursor / TRAE 用 camelCase），而 `settings.hook_events`
    里存的是**标准名**（与 `hooks.events` 一致）。此前这套映射靠每个客户端手写
    `template` 的 key 实现 —— 于是「要写哪些事件」散落在 6 份 template 里，
    既无法统一管理，也会与 `events` 声明不一致（实测 Codex 声明支持
    UserPromptSubmit 但 template 没有它，审计报缺而写入永远补不上）。

    未知规范（空/None）按原样返回。
    """
    if not canonical:
        return canonical
    if event_format == "camel_case":
        return canonical[0].lower() + canonical[1:]
    if event_format == "pascal_case":
        return canonical[0].upper() + canonical[1:]
    return canonical


def client_supported_events(hc: Dict[str, Any]) -> List[str]:
    """客户端**声明支持**的事件集（该客户端配置里的实际键名）。

    与 ``config['hooks']['events']``（规范词表）的区别：词表是**可勾选的全集**，
    而这里存的是该客户端自己的命名（Cursor/TRAE 为 camelCase、Claude Code/Codex
    为 PascalCase）。写入时用它做**能力校验** —— 只写该客户端真正认的事件，
    避免把 Cursor 独有的 ``beforeTabFileRead`` 之类写进不认识它的客户端。

    兼容两种写法：字符串 ``- sessionStart`` 与对象
    ``- {name: sessionStart, description: ...}``。
    """
    out: List[str] = []
    for entry in hc.get("events") or []:
        name = entry.get("name") if isinstance(entry, dict) else entry
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def client_scopes(hc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """客户端 hook 配置的**分层作用域**（user / project / local …）。

    每个元素 ``{id, label, config_path}``；用于 GUI 的 IDE/Agent 详情展示
    「该客户端的 hook 配置可能落在哪些层级」，与安装证据的 APP/CLI/CONFIG
    路径口径一致。未声明 ``scopes`` 时回退为单一 ``config_path``。
    """
    scopes = hc.get("scopes")
    if isinstance(scopes, list) and scopes:
        return [
            {
                "id": s.get("id", ""),
                "label": s.get("label", s.get("id", "")),
                "config_path": s.get("config_path", ""),
            }
            for s in scopes
            if isinstance(s, dict) and s.get("config_path")
        ]
    primary = hc.get("config_path")
    if primary:
        return [{"id": "primary", "label": "默认", "config_path": primary}]
    return []


def _intended_events(hc: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    """该客户端**本次打算写入**的事件（该客户端命名）。

    与 ``client_supported_events``（能力全集）区分：能力全集回答「能不能写」，
    意图回答「这次要写哪些」—— 后者才是「缺关键事件」审计的基准。
    取法与 ``hooks_fixer`` 保持一致（同一份 ``settings.hook_events``、同一套
    ``event_format`` 转换、同一道能力过滤），避免「写入端写 A、审计端查 B」的漂移。
    """
    settings = config.get("settings") or {}
    if "hook_events" not in settings:
        return sorted((hc.get("template") or {}).keys())
    event_format = hc.get("event_format")
    supported = client_supported_events(hc)
    # 审计基准再收一道：只在 ai-memory **有命令模板**的事件里算「缺关键事件」。
    # 为什么（2026-10-12 二次修正）：`settings.hook_events` 的默认值已改为**全选**
    # （47 项）。若意图直接取「选中 ∩ 能力」，Claude Code 会一次报出 33 个「缺失」
    # —— 那是「默认状态」而不是异常，页面会被假警报淹没，等于没有审计。
    # 取「选中 ∩ 能力 ∩ 模板键」后：默认全选时基准就是模板那几个核心事件（每个
    # 客户端 5~7 个），与「是否接上 ai-memory 生命周期 hook」这个真问题对齐。
    templated = set((hc.get("template") or {}).keys())
    out: List[str] = []
    for canonical in settings.get("hook_events") or []:
        native = event_name_for_client(canonical, event_format)
        if supported and native not in supported:
            continue
        if templated and native not in templated:
            continue
        if native not in out:
            out.append(native)
    return out


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
            "hooks_scopes": [],
            "hooks_supported_events": [],
            "hooks_event_format": "",
            "hooks_inventory": [],
        }

    entries = list_client_hook_entries(tool, config)
    ai_events = sorted({e.event for e in entries if e.is_ai_memory})
    supported_events = client_supported_events(hc)
    # 「缺关键事件」审计由**写入意图**推导，而不是由能力全集推导。
    # 为什么必须改（2026-10-12）：``events`` 从「关注的小集合」升级为「该客户端支持的
    # 全部事件」后（Claude Code 33 项、WorkBuddy 29 项），若仍拿它算缺失，审计会把
    # 二十多个「支持、但本次并没打算写」的事件全报成「缺关键事件」—— 语义被撑爆且全是
    # 假警报。意图的取法与 ``hooks_fixer`` 同源（同一份 settings.hook_events、同一套
    # event_format 转换、同一道能力过滤），避免「写入端写 A、审计端查 B」的漂移。
    missing_key = [e for e in _intended_events(hc, config) if e not in ai_events]

    return {
        "hooks_config_path": hc.get("config_path", ""),
        "hooks_configured": bool(ai_events),
        "hook_events": ai_events,
        "hooks_fix_supported": hc.get("fix_supported", False),
        # 能力域：供 GUI 的 IDE/Agent 详情展示「支持哪些事件 / 配置落在哪些层级」，
        # 也是写入端做能力校验的事实来源（见 hooks_fixer）。
        "hooks_scopes": client_scopes(hc),
        "hooks_supported_events": supported_events,
        "hooks_event_format": hc.get("event_format") or "",
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
