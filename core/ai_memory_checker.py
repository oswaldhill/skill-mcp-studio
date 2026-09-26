"""
ai-memory 生命周期 hooks 与修复模块（会话交接层）。

MCP 接入检测（是否已配置 ai-memory MCP server / server_url / token）已并入
``legacy_checker`` 的声明式检测块（``AI_MEMORY_DETECTION``）；本模块仅保留
ai-memory 特有的两项职责：

1. 生命周期 hooks（SessionStart/SessionEnd 等）检查 —— 自动交接
   （handoff 注入 / 观察提交）依赖 hooks，MCP 接入 ≠ 自动交接；
2. 自动修复（写入各 IDE 配置，带备份）。

ai-memory hooks 识别依据：hooks 命令包含 "ai-memory" + "hook --event"。
"""

import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

from file_atomic import atomic_write, backup_path
from legacy_checker import (
    AI_MEMORY_DETECTION,
    MCP_CAPABLE_TOOLS,
    _check_legacy_server,
    _get_mcp_config_for_tool,
    _load_json_file,
    _norm_tool_name,
)


def _python3_command() -> str:
    """Resolve a portable ``python3`` interpreter path for writing MCP commands.

    Cross-platform priority:

    1. ``sys.executable`` — the running interpreter (Windows ``python.exe``,
       venv/pipx path on all OSes), guaranteed to exist when the CLI runs;
    2. ``shutil.which("python3")`` — a PATH ``python3`` on POSIX (also matches
       ``python3.exe`` on Windows);
    3. bare ``"python3"`` as a last resort, delegated to PATH resolution when the
       target client later spawns the command.
    """
    exe = getattr(sys, "executable", "") or ""
    if exe and os.path.exists(exe):
        return exe
    found = shutil.which("python3")
    return found or "python3"


def _bridge_path() -> str:
    """Portable ai-memory bridge path (``~/.local/bin`` on all platforms)."""
    return os.path.join(os.path.expanduser("~"), ".local", "bin", "ai-memory-bridge.py")


# ai-memory 生命周期 hooks 的配置路径与事件签名
# key: 工具名（与 MCP_CAPABLE_TOOLS 对齐）
# value: {
#   "config_path": hooks 配置文件（Claude 在 settings.json 而非 ~/.claude.json）,
#   "format": json | toml,
#   "hook_keys": 配置中定位 hooks 段的路径,
#   "events": 关键事件列表,
# }
AI_MEMORY_HOOKS_PATHS = {
    "Claude Code": {
        "config_path": "~/.claude/settings.json",
        "hook_keys": ["hooks"],
        "events": ["SessionStart", "UserPromptSubmit", "SessionEnd", "Stop"],
        "note": "Claude Code 生命周期 hooks（settings.json）",
    },
    "Cursor": {
        "config_path": "~/.cursor/hooks.json",
        "hook_keys": ["hooks"],
        "events": ["sessionStart", "sessionEnd", "stop"],
        "note": "Cursor 生命周期 hooks（hooks.json；事件名为小写 camelCase）",
    },
    "WorkBuddy": {
        "config_path": "~/.workbuddy/settings.json",
        "hook_keys": ["hooks"],
        "events": ["PreToolUse", "UserPromptSubmit", "PostToolUse", "SessionStart",
                   "Notification", "SubagentStop", "PreCompact", "SubagentStart",
                   "SessionEnd", "Stop"],
        "note": "WorkBuddy 生命周期 hooks（settings.json；Claude 派生架构，PascalCase 事件名）",
    },
    "Codex": {
        "config_path": "~/.codex/hooks.json",
        "hook_keys": ["hooks"],
        "events": ["SessionStart", "UserPromptSubmit", "Stop"],
        "note": "Codex 生命周期 hooks（hooks.json；无 true SessionEnd，结束用 finalize-session）",
    },
    "OpenCode": {
        "config_path": "~/.config/opencode/plugins/ai-memory.ts",
        "hook_keys": [],
        "events": [],
        "plugin": True,
        "note": "OpenCode 用 TS 插件（plugins/ai-memory.ts）而非 JSON hooks",
    },
}

# hook 命令中的 ai-memory 签名
AI_MEMORY_HOOK_SIGNATURE = ["ai-memory", "hook --event"]


# ── hooks（自动交接）检查 ───────────────────────────────────────────

def _load_toml_file(filepath: str) -> Optional[Dict[str, Any]]:
    """读取 TOML 配置文件（尽力而为，失败返回 None）。"""
    try:
        import tomllib as _toml_mod
    except ImportError:  # Python < 3.11
        import tomli as _toml_mod
    expanded = os.path.expanduser(filepath)
    if not os.path.isfile(expanded):
        return None
    try:
        with open(expanded, "rb") as f:
            return _toml_mod.load(f)
    except (OSError, _toml_mod.TOMLDecodeError):
        return None


def _find_in_dict(data: Any, key_path: List[str]) -> Any:
    """沿 key_path 深入取 dict 值。"""
    current = data
    for key in key_path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _extract_hook_commands(hook_section: Any) -> List[str]:
    """从 hooks 配置段递归提取所有 command 字符串。

    兼容两种结构：
    - Claude Code: {"hooks": {"SessionStart": [{"matcher": "...", "hooks": [{"type":"command","command":"..."}]}]}}
    - Codex:       {"hooks": {"SessionStart": [{"matcher": "...", "hooks": [{"type":"command","command":"..."}]}]}}
    """
    commands = []

    def walk(node: Any):
        if isinstance(node, dict):
            cmd = node.get("command")
            if isinstance(cmd, str):
                commands.append(cmd)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(hook_section)
    return commands


def check_ai_memory_hooks(
    installed_tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    检查各已安装 IDE/Agent 的 ai-memory 生命周期 hooks 配置状态。

    Returns:
        dict: {
            "hooks_configured": int,       # 已配置 ai-memory hooks 的工具数
            "hooks_missing": int,          # 已安装但缺 ai-memory hooks 的工具数
            "tools": [
                {
                    "name": str,
                    "installed": bool,
                    "has_hooks_config": bool,
                    "ai_memory_hooks": bool,
                    "hook_events": list,    # 命中的 ai-memory hook 事件
                    "config_path": str,
                    "note": str,
                }
            ],
        }
    """
    installed_names = {_norm_tool_name(t.get("name", "")) for t in installed_tools
                       if t.get("is_installed", False)}
    # 补充：有 MCP 配置文件的也视为已安装
    for tool_def in MCP_CAPABLE_TOOLS:
        if _get_mcp_config_for_tool(tool_def) is not None:
            installed_names.add(_norm_tool_name(tool_def["name"]))

    results = []
    configured_count = 0
    missing_count = 0

    for tool_name, hook_def in AI_MEMORY_HOOKS_PATHS.items():
        is_installed = _norm_tool_name(tool_name) in installed_names
        result = {
            "name": tool_name,
            "installed": is_installed,
            "has_hooks_config": False,
            "ai_memory_hooks": False,
            "hook_events": [],
            "config_path": hook_def["config_path"],
            "note": hook_def.get("note", ""),
        }

        config_path = os.path.expanduser(hook_def["config_path"])
        if not os.path.isfile(config_path):
            result["note"] = "hooks 配置文件不存在"
            if not is_installed:
                result["note"] = "工具未安装"
            if is_installed:
                missing_count += 1
            results.append(result)
            continue

        result["has_hooks_config"] = True
        if not is_installed:
            result["installed"] = True  # 有 hooks 配置文件 = 工具确已初始化

        # OpenCode：插件文件形式
        if hook_def.get("plugin"):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "ai-memory" in content and ("hook" in content or "session" in content):
                    result["ai_memory_hooks"] = True
                    result["hook_events"] = ["plugin"]
                    configured_count += 1
                else:
                    missing_count += 1
            except OSError:
                missing_count += 1
            results.append(result)
            continue

        # JSON/TOML hooks 段
        data = _load_json_file(config_path)
        if data is None:
            data = _load_toml_file(config_path)
        if data is None:
            result["note"] = "hooks 配置无法解析"
            missing_count += 1
            results.append(result)
            continue

        hook_section = _find_in_dict(data, hook_def["hook_keys"])
        if hook_section is None:
            # Cursor / Codex 的 hooks.json 顶层即事件名（无 "hooks" 包裹），
            # 且数据是事件映射时，直接用顶层作为 hooks 段。
            if isinstance(data, dict) and data and hook_def.get("hook_keys"):
                top_keys = list(data.keys())
                known_events = set(hook_def.get("events", []))
                if any(k in known_events for k in top_keys):
                    hook_section = data
        if hook_section is None:
            result["note"] = "hooks 段不存在"
            missing_count += 1
            results.append(result)
            continue

        # 找出命中 ai-memory 签名的命令及其事件
        matched_events = []

        def _is_ai_memory_hook_cmd(cmd: str) -> bool:
            """识别 ai-memory hook 命令：标准 CLI（ai-memory hook --event）
            或本机 wrapper（ai-memory-hook <agent> <event>）。"""
            return ("ai-memory" in cmd and "hook --event" in cmd) or "ai-memory-hook" in cmd

        # 遍历顶层事件（SessionStart/UserPromptSubmit/...）
        if isinstance(hook_section, dict):
            for event_name, event_hooks in hook_section.items():
                event_cmds = _extract_hook_commands(event_hooks)
                for cmd in event_cmds:
                    if _is_ai_memory_hook_cmd(cmd):
                        matched_events.append(event_name)
                        break

        if matched_events:
            result["ai_memory_hooks"] = True
            result["hook_events"] = matched_events
            configured_count += 1
            # 关键事件完整性
            key_events = hook_def.get("events", [])
            missing_key = [e for e in key_events if e not in matched_events]
            result["missing_key_events"] = missing_key
            if missing_key:
                result["note"] = f"已配 hooks，但缺关键事件: {', '.join(missing_key)}"
        else:
            missing_count += 1
            result["note"] = "hooks 已配置但未接入 ai-memory"

        results.append(result)

    return {
        "hooks_configured": configured_count,
        "hooks_missing": missing_count,
        "tools": results,
    }


def format_ai_memory_hooks_report(result: Dict[str, Any]) -> str:
    """将 ai-memory hooks 检查结果格式化为可读字符串。"""
    lines = []
    lines.append("  ┌─────────────────────────────────────────────┐")
    lines.append("  │  ai-memory hooks 检查（自动交接）             │")
    lines.append("  └─────────────────────────────────────────────┘")
    lines.append(f"  已配置 ai-memory hooks: {result['hooks_configured']}  ✅")
    lines.append(f"  已安装但缺 hooks: {result['hooks_missing']}")
    lines.append("")

    for t in result["tools"]:
        icon = "🟢" if t["ai_memory_hooks"] else ("⚪" if not t["installed"] else "⚠️")
        lines.append(f"  {icon} {t['name']} ({t['config_path']})")
        if t["ai_memory_hooks"]:
            ev = ", ".join(t.get("hook_events", []))
            lines.append(f"      ✅ 已接入 hooks: {ev}")
            if t.get("missing_key_events"):
                lines.append(f"      ⚠️ 缺关键事件: {', '.join(t['missing_key_events'])}")
        elif t["installed"]:
            lines.append(f"      ⚠️ {t['note']}")
        else:
            lines.append("      未安装，跳过")

    return "\n".join(lines)


def build_ai_memory_fix_template() -> Dict[str, Any]:
    """
    生成 ai-memory MCP 接入配置模板（JSON 结构），供各 IDE 修复参考。
    """
    return {
        "ai-memory": {
            "command": _python3_command(),
            "args": [_bridge_path()],
            "env": {
                "AI_MEMORY_SERVER_URL": "http://127.0.0.1:49374/mcp",
                "AI_MEMORY_AUTH_TOKEN": "<AI_MEMORY_TOKEN>",
            },
        }
    }


# ── 自动修复（写入各 IDE 配置文件，带备份）───────────────────────────

def _backup_file(filepath: str) -> str:
    """备份配置文件，返回备份路径（微秒级时间戳，避免秒级碰撞——D-6）。"""
    backup = backup_path(filepath)
    try:
        shutil.copy2(filepath, backup)
        return backup
    except OSError as e:
        raise RuntimeError(f"备份 {filepath} 失败: {e}")


def _write_json_atomic(data: Dict[str, Any], config_path: str, backup: str) -> None:
    """原子写 JSON（mkstemp+fsync+replace）+ re-parse 校验；失败即回滚（D-6）。

    与 mcp_fixer 的写路径安全链对齐：备份 → 原子写 → 重新解析校验 → 失败回滚。
    """
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    # 权限：配置可能承载 token，新建/改写一律 0o600；若原文件存在则保留其原 mode。
    try:
        mode = os.stat(config_path).st_mode & 0o777
    except OSError:
        mode = 0o600
    try:
        atomic_write(config_path, rendered, mode)
        json.loads(rendered)  # re-parse 校验写入内容可解析
    except Exception:
        # 回滚：用备份覆盖原文件（尽力而为；回滚失败不可吞掉原始异常语义）
        if os.path.isfile(backup):
            try:
                shutil.copy2(backup, config_path)
            except OSError:
                pass
        raise


def _find_json_mcp_section(data: Dict[str, Any], mcp_key_path: List[str]) -> Optional[Dict[str, Any]]:
    """沿 mcp_key_path 深入取 MCP servers 段（若无则创建）。"""
    current = data
    for key in mcp_key_path:
        if not isinstance(current, dict):
            return None
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    return current


def fix_ai_memory_config(
    tool_def: Dict[str, Any],
    server_url: str = "http://127.0.0.1:49374/mcp",
    token: str = "",
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    为单个工具自动写入 ai-memory MCP 配置。

    支持格式：
    - JSON mcpServers dict（Claude/Cursor/WorkBuddy/OpenCode/...）
    - Reasonix 字符串数组格式（mcp: ["name=cmd args", ...]）

    Args:
        tool_def: 工具定义（含 config_path / mcp_key_path / env_key / format）
        server_url: ai-memory 服务器 URL
        token: ai-memory 认证 token（缺失则用占位符）
        dry_run: True=只预览不写入

    Returns:
        dict: {"name", "config_path", "backup", "written", "message"}
    """
    name = tool_def.get("name", "")
    config_path = os.path.expanduser(tool_def.get("config_path", ""))
    fmt = tool_def.get("format", "json")
    mcp_key_path = tool_def.get("mcp_key_path", ["mcpServers"])
    env_key = tool_def.get("env_key", "env")

    result = {
        "name": name,
        "config_path": tool_def.get("config_path", ""),
        "backup": "",
        "written": False,
        "message": "",
    }

    if fmt == "toml":
        result["message"] = "TOML 格式请手动添加（参考 --ai-memory 输出模板）"
        return result

    data = _load_json_file(config_path)
    if data is None:
        result["message"] = "配置文件不存在或非法 JSON，跳过"
        return result

    # ⭐ Reasonix：mcp 是字符串数组格式 ["name=cmd args", ...]
    if fmt == "reasonix-json" or (name.lower() == "reasonix"):
        mcp_arr = data.get("mcp")
        if not isinstance(mcp_arr, list):
            result["message"] = "mcp 不是数组格式，跳过"
            return result
        # 已存在则不重复
        for entry in mcp_arr:
            if isinstance(entry, str) and entry.strip().startswith("ai-memory="):
                result["message"] = "已存在 ai-memory 条目，跳过"
                return result
        bridge = _bridge_path()
        entry = f"ai-memory={_python3_command()} {bridge}"
        if dry_run:
            result["message"] = "[dry-run] 将追加 ai-memory 条目到 mcp 数组"
            return result
        backup = _backup_file(config_path)
        result["backup"] = backup
        mcp_arr.append(entry)
        try:
            _write_json_atomic(data, config_path, backup)
            result["written"] = True
            result["message"] = f"已写入 ai-memory 条目（备份 {backup}）"
        except OSError as e:
            result["message"] = f"写入失败: {e}"
        return result

    section = _find_json_mcp_section(data, mcp_key_path)
    if section is None:
        result["message"] = "MCP 配置段结构异常，跳过"
        return result

    # 已存在则不重复写入
    if "ai-memory" in section:
        result["message"] = "已存在 ai-memory 条目，跳过"
        return result

    entry = {
        "command": _python3_command(),
        "args": [_bridge_path()],
        env_key: {
            "AI_MEMORY_SERVER_URL": server_url,
            "AI_MEMORY_AUTH_TOKEN": token or "<AI_MEMORY_TOKEN>",
        },
    }
    section["ai-memory"] = entry

    if dry_run:
        result["message"] = "[dry-run] 将写入 ai-memory 条目"
        return result

    backup = _backup_file(config_path)
    result["backup"] = backup
    try:
        _write_json_atomic(data, config_path, backup)
        result["written"] = True
        result["message"] = f"已写入 ai-memory 条目（备份 {backup}）"
    except OSError as e:
        result["message"] = f"写入失败: {e}"

    return result


def fix_ai_memory_all(
    installed_tools: List[Dict[str, Any]],
    config: Dict[str, Any] = None,
    server_url: str = "http://127.0.0.1:49374/mcp",
    token: str = "",
    dry_run: bool = True,
) -> List[Dict[str, Any]]:
    """为所有已安装且未接入 ai-memory 的 JSON 工具批量写入配置。"""
    installed_names = {_norm_tool_name(t.get("name", "")) for t in installed_tools
                       if t.get("is_installed", False)}

    mcp_tools = list(MCP_CAPABLE_TOOLS)
    if config and "mcp_tools" in config:
        for tool_def in config["mcp_tools"]:
            if "name" in tool_def and "config_path" in tool_def and "mcp_key_path" in tool_def:
                existing_names = {t["name"] for t in mcp_tools}
                if tool_def["name"] not in existing_names:
                    mcp_tools.append(tool_def)

    results = []
    for tool_def in mcp_tools:
        tool_name = tool_def["name"]
        if _norm_tool_name(tool_name) not in installed_names:
            continue  # 未安装跳过
        # 已接入的跳过
        mcp_servers = _get_mcp_config_for_tool(tool_def)
        already = False
        if mcp_servers:
            env_key = tool_def.get("env_key", "env")
            for srv_name, srv_cfg in mcp_servers.items():
                c = _check_legacy_server(
                    srv_name, srv_cfg, env_key=env_key, detection=AI_MEMORY_DETECTION
                )
                if c["is_legacy"]:
                    already = True
                    break
        if already:
            continue
        results.append(fix_ai_memory_config(tool_def, server_url=server_url,
                                            token=token, dry_run=dry_run))
    return results
