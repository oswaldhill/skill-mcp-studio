"""
Legacy-channel connectivity checker (generalized from the former hermes_checker).

A profile may declare ``legacy_detection`` so the four heuristics and the channel
completeness check are data-driven instead of hardcoded:

    legacy_detection:
      server_name_keywords: [hermes]
      command_patterns: [hermes-bridge]
      env_keys: [NAS_GATEWAY_URL, NAS_API_KEY, NAS_MODEL]
      url_pattern: "nas[-_\\./].*:\\d+"
      gateway_url_env: NAS_GATEWAY_URL      # optional; else first *_URL env key
      api_key_env: NAS_API_KEY              # optional; else first *_KEY env key
      placeholder_keys: [REPLACE_ME, your-key-here]
      passthrough_patterns: [v2-bridge, mcp-bridge]
      channels:                             # channel completeness (原三通道)
        - { label: nas, canonical: hermes-nas, match_keywords: [nas] }
        - { label: memory, canonical: hermes-memory, match_keywords: [memory] }
        - { label: gateway, canonical: hermes-gateway, match_keywords: [gateway] }

Without a profile/legacy_detection, the historical hermes defaults are used so
``--hermes``-equivalent behavior is preserved.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional


# Known MCP-capable tools and their configuration path templates (built-in
# registry; merged with config.yaml's mcp_tools at runtime).
MCP_CAPABLE_TOOLS = [
    {"name": "Claude Code", "config_path": "~/.claude.json",
     "mcp_key_path": ["mcpServers"], "note": "全局 MCP 配置"},
    {"name": "Cursor", "config_path": "~/.cursor/mcp.json",
     "mcp_key_path": ["mcpServers"], "note": "项目级/全局 MCP 配置"},
    {"name": "Windsurf", "config_path": "~/.windsurf/mcp_config.json",
     "mcp_key_path": ["mcpServers"], "note": "全局 MCP 配置"},
    {"name": "WorkBuddy", "config_path": "~/.workbuddy/mcp.json",
     "mcp_key_path": ["mcpServers"], "note": "全局 MCP 配置（原 CodeBuddy）"},
    {"name": "Qoder", "config_path": "~/.qoder/shared_client/mcp.json",
     "mcp_key_path": ["mcpServers"], "note": "共享客户端 MCP 配置"},
    {"name": "Continue", "config_path": "~/.continue/config.json",
     "mcp_key_path": ["experimental", "mcpServers"], "note": "实验性 MCP 支持"},
    {"name": "OpenCode", "config_path": "~/.config/opencode/opencode.json",
     "mcp_key_path": ["mcp"], "env_key": "environment",
     "note": "OpenCode 全局 MCP 配置"},
    {"name": "Cherry Studio", "config_path": "~/.cherrystudio/mcp/mcp.json",
     "mcp_key_path": ["mcpServers"], "note": "MCP 配置存储在 IndexedDB 中"},
    {"name": "Codex", "config_path": "~/.codex/config.toml",
     "mcp_key_path": ["mcp_servers"], "format": "toml",
     "note": "OpenAI Codex 全局 MCP 配置（TOML 格式）"},
    {"name": "Reasonix", "config_path": "~/.reasonix/config.json",
     "mcp_key_path": ["mcp"], "format": "reasonix-json",
     "note": "Reasonix 全局 MCP 配置（mcp 数组格式）"},
]


# A single detection block's full field set. Each block answers "is this MCP
# server one of the legacy/old channels to migrate away from?" via four
# heuristics plus an integrity deep-check.
GENERIC_DETECTION_BASE = {
    "label": "",
    "server_name_keywords": [],
    "command_patterns": [],
    "env_keys": [],
    "url_pattern": "",
    "gateway_url_env": "",
    "api_key_env": "",
    "placeholder_keys": [],
    "passthrough_patterns": [],
    "verify_script": True,
    "channels": [],
}


# Historical hermes defaults (HERMES_SIGNATURES + 三通道) — one detection block.
DEFAULT_LEGACY_DETECTION = {
    "label": "hermes",
    "server_name_keywords": ["hermes"],
    "command_patterns": ["hermes-bridge"],
    "env_keys": ["NAS_GATEWAY_URL", "NAS_API_KEY", "NAS_MODEL"],
    "url_pattern": r"nas[-_\./].*:\d+",
    "gateway_url_env": "NAS_GATEWAY_URL",
    "api_key_env": "NAS_API_KEY",
    "placeholder_keys": ["REPLACE_ME", "your-key-here"],
    "passthrough_patterns": ["v2-bridge", "mcp-bridge"],
    "verify_script": True,
    "channels": [
        {"label": "nas", "canonical": "hermes-nas", "match_keywords": ["nas"]},
        {"label": "memory", "canonical": "hermes-memory", "match_keywords": ["memory"]},
        {"label": "gateway", "canonical": "hermes-gateway", "match_keywords": ["gateway"]},
    ],
}

# ai-memory (会话交接层) legacy entry — same shape, token-based deep-check.
AI_MEMORY_DETECTION = {
    "label": "ai-memory",
    "server_name_keywords": ["ai-memory", "aimemory"],
    "command_patterns": ["ai-memory-bridge"],
    "env_keys": ["AI_MEMORY_SERVER_URL", "AI_MEMORY_AUTH_TOKEN"],
    "url_pattern": "",
    "gateway_url_env": "AI_MEMORY_SERVER_URL",
    "api_key_env": "AI_MEMORY_AUTH_TOKEN",
    "placeholder_keys": ["REPLACE_ME", "your-token-here", "<AI_MEMORY_TOKEN>"],
    "passthrough_patterns": [],
    "verify_script": False,
    "channels": [],
}

# When a profile declares no legacy_detection, check both legacy channels so the
# historical --hermes and --ai-memory aliases keep working through one path.
DEFAULT_DETECTIONS = [dict(DEFAULT_LEGACY_DETECTION), dict(AI_MEMORY_DETECTION)]


def _resolve_block(block: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve one detection block; ``None`` falls back to the hermes default."""
    if block is None:
        block = DEFAULT_LEGACY_DETECTION
    resolved = dict(GENERIC_DETECTION_BASE)
    provided = block or {}
    resolved.update(provided)
    env_keys = resolved.get("env_keys") or []

    if not provided.get("gateway_url_env"):
        for key in env_keys:
            if str(key).endswith("_URL"):
                resolved["gateway_url_env"] = key
                break
    if not provided.get("api_key_env"):
        for key in env_keys:
            if str(key).endswith(("_KEY", "_TOKEN", "_SECRET")):
                resolved["api_key_env"] = key
                break
    return resolved


def _resolve_detections(detection: Any) -> List[Dict[str, Any]]:
    """Normalize ``profile.legacy_detection`` (None/dict/list) to a block list."""
    if detection is None:
        return DEFAULT_DETECTIONS
    if isinstance(detection, dict):
        block = _resolve_block(detection)
        if not block.get("label"):
            block["label"] = "hermes"  # lone dict = legacy hermes block (backward compat)
        return [block]
    if isinstance(detection, list):
        blocks = [_resolve_block(d) for d in detection if isinstance(d, dict)]
        return blocks or DEFAULT_DETECTIONS
    return DEFAULT_DETECTIONS


def _norm_tool_name(name: str) -> str:
    """Lowercase, strip leading dot, remove spaces and hyphens."""
    return name.strip().lower().lstrip(".").replace(" ", "").replace("-", "")


def _load_json_file(filepath: str) -> Optional[Dict[str, Any]]:
    expanded = os.path.expanduser(filepath)
    if not os.path.isfile(expanded):
        return None
    try:
        with open(expanded, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, PermissionError, OSError):
        return None


def _check_legacy_server(
    server_name: str,
    server_config: Dict[str, Any],
    env_key: str = "env",
    detection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify one MCP server against a legacy detection declaration."""
    det = _resolve_block(detection)
    result = {
        "is_legacy": False,
        "match_reason": "",
        "gateway_url": "",
        "server_details": {},
    }

    name_lower = (server_name or "").lower()
    for keyword in det.get("server_name_keywords", []):
        if keyword and keyword in name_lower:
            result["is_legacy"] = True
            result["match_reason"] = f"服务名包含 '{keyword}'"
            break

    raw_cmd = server_config.get("command", "")
    if isinstance(raw_cmd, list):
        command_parts = [str(p) for p in raw_cmd]
        command = command_parts[0] if command_parts else ""
        args = command_parts[1:]
    else:
        command = raw_cmd or ""
        args = server_config.get("args", []) or []
    full_command = f"{command} {' '.join(map(str, args))}".strip()

    for pattern in det.get("command_patterns", []):
        if pattern and pattern in full_command:
            result["is_legacy"] = True
            if not result["match_reason"]:
                result["match_reason"] = f"命令包含 '{pattern}'"
            break

    env = server_config.get(env_key, {}) or {}
    gateway_url_env = det.get("gateway_url_env")
    for env_key_name in det.get("env_keys", []):
        if env_key_name in env:
            if not result["match_reason"]:
                result["match_reason"] = f"环境变量包含 '{env_key_name}'"
            result["is_legacy"] = True
            if gateway_url_env and env_key_name == gateway_url_env:
                result["gateway_url"] = env[env_key_name]
            break

    if not result["gateway_url"]:
        url = env.get(gateway_url_env or "", "")
        if not url:
            url = server_config.get("url", "")
        url_pattern = det.get("url_pattern")
        if url_pattern and url and re.search(url_pattern, url, re.IGNORECASE):
            result["gateway_url"] = url
            result["is_legacy"] = True
            if not result["match_reason"]:
                result["match_reason"] = "URL 匹配 legacy 模式"

    result["server_details"] = {
        "name": server_name,
        "command": command,
        "args_count": len(args),
        "has_env": bool(env),
        "url": server_config.get("url", ""),
        "kind": det.get("label", ""),
        "script_exists": None,
        "key_valid": None,
        "deep_check_note": "",
    }

    secret_env = det.get("api_key_env", "") or ""
    secret_value = env.get(secret_env, "") if secret_env else ""
    placeholder_keys = det.get("placeholder_keys") or []

    if det.get("verify_script", True):
        script = args[0] if args else (command or "")
        if command and command.split("/")[-1] in (
            "python", "python3", "node", "bash", "sh", "zsh", "ruby", "perl",
        ) and args:
            script = args[0]
        if script and not script.startswith(("http", "https")):
            if "/" in script:
                expanded = os.path.expanduser(script)
                exists = os.path.isfile(expanded)
            else:
                import shutil
                exists = shutil.which(script) is not None
            result["server_details"]["script_exists"] = exists
            if not exists:
                result["server_details"]["deep_check_note"] = f"脚本不存在: {script}"
            elif result["is_legacy"]:
                passthrough = any(
                    pattern in script for pattern in det.get("passthrough_patterns", [])
                )
                if secret_value:
                    placeholder = secret_value in placeholder_keys
                    result["server_details"]["key_valid"] = not placeholder
                    if placeholder:
                        result["server_details"]["deep_check_note"] = (
                            f"{secret_env} 是占位值，网关会拒绝认证"
                        )
                elif not passthrough and env.get(gateway_url_env or ""):
                    result["server_details"]["key_valid"] = False
                    result["server_details"]["deep_check_note"] = (
                        f"有 {gateway_url_env} 但缺 {secret_env}"
                    )
                elif passthrough:
                    result["server_details"]["key_valid"] = True
    elif result["is_legacy"]:
        # token-based deep-check (e.g. ai-memory): verify URL + token presence/value.
        if not result["gateway_url"]:
            result["server_details"]["key_valid"] = False
            result["server_details"]["deep_check_note"] = (
                f"缺少 {gateway_url_env or secret_env}"
            )
        elif not secret_value:
            result["server_details"]["key_valid"] = False
            result["server_details"]["deep_check_note"] = f"缺少 {secret_env}"
        elif secret_value in placeholder_keys:
            result["server_details"]["key_valid"] = False
            result["server_details"]["deep_check_note"] = f"{secret_env} 是占位值"
        else:
            result["server_details"]["key_valid"] = True

    return result


def _load_toml_mcp_servers(filepath: str) -> Optional[Dict[str, Any]]:
    expanded = os.path.expanduser(filepath)
    if not os.path.isfile(expanded):
        return None
    servers: Dict[str, Any] = {}
    cur = None
    cur_env = False
    try:
        with open(expanded, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("[mcp_servers.") and line.endswith("]"):
            section = line[len("[mcp_servers."):-1].strip()
            if section.endswith(".env"):
                cur = section[:-len(".env")]
                cur_env = True
                servers.setdefault(cur, {})
            else:
                cur = section
                cur_env = False
                servers.setdefault(cur, {})
        elif cur and "=" in line and not line.startswith("["):
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                value = [i.strip().strip('"') for i in inner.split(",")] if inner else []
            else:
                value = value.strip('"')
            if cur_env:
                servers[cur].setdefault("env", {})[key] = value
            else:
                servers[cur][key] = value
    return servers if servers else None


def _load_reasonix_plugins(filepath: str) -> Optional[Dict[str, Any]]:
    import tomllib
    expanded = os.path.expanduser(filepath)
    if not os.path.isfile(expanded):
        return None
    try:
        with open(expanded, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return None
    servers = {}
    for plugin in plugins:
        if not isinstance(plugin, dict) or not plugin.get("name"):
            continue
        servers[plugin["name"]] = {k: v for k, v in plugin.items() if k != "name"}
    return servers if servers else None


def _load_reasonix_json_mcp(filepath: str) -> Optional[Dict[str, Any]]:
    expanded = os.path.expanduser(filepath)
    if not os.path.isfile(expanded):
        return None
    data = _load_json_file(expanded)
    if not isinstance(data, dict):
        return None
    mcp_list = data.get("mcp")
    if not isinstance(mcp_list, list):
        return None
    servers = {}
    for entry in mcp_list:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        name, cmdline = entry.split("=", 1)
        parts = cmdline.split()
        if not parts:
            continue
        servers[name.strip()] = {"command": parts[0], "args": parts[1:]}
    return servers if servers else None


def _get_mcp_config_for_tool(tool_def: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if tool_def.get("format") == "toml":
        return _load_toml_mcp_servers(tool_def["config_path"])
    if tool_def.get("format") == "reasonix":
        return _load_reasonix_plugins(tool_def["config_path"])
    if tool_def.get("format") == "reasonix-json":
        return _load_reasonix_json_mcp(tool_def["config_path"])
    config = _load_json_file(tool_def["config_path"])
    if config is None:
        return None
    current = config
    for key in tool_def["mcp_key_path"]:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current if isinstance(current, dict) else None


def _legacy_channel_of(
    name: str,
    channels: List[Dict[str, Any]],
    profile_name: str,
) -> str:
    lowered = (name or "").lower()
    for channel in channels or []:
        for keyword in channel.get("match_keywords", []):
            if keyword and keyword in lowered:
                return channel.get("label", "")
    if profile_name and lowered == profile_name.lower() and channels:
        return channels[0].get("label", "")
    return ""


def check_legacy_channels(
    installed_tools: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Check every installed, MCP-capable tool for declared legacy channels.

    Returns::

        {"capable_total": int, "capable_checked": int, "connected": int,
         "disconnected": int, "gateway_url": str, "tools": [...]}
    """
    profile = profile or {}
    detections = _resolve_detections(profile.get("legacy_detection"))
    profile_name = profile.get("name", "")

    installed_names = {
        _norm_tool_name(t.get("name", ""))
        for t in installed_tools
        if t.get("is_installed", False)
    }

    mcp_tools = list(MCP_CAPABLE_TOOLS)
    if config and "mcp_tools" in config:
        existing = {t["name"] for t in mcp_tools}
        for tool_def in config["mcp_tools"]:
            if (
                "name" in tool_def
                and "config_path" in tool_def
                and "mcp_key_path" in tool_def
                and tool_def["name"] not in existing
            ):
                mcp_tools.append(tool_def)

    results = []
    connected_count = 0
    disconnected_count = 0
    gateway_url = ""

    for tool_def in mcp_tools:
        tool_name = tool_def["name"]
        is_installed = _norm_tool_name(tool_name) in installed_names

        result = {
            "name": tool_name,
            "mcp_capable": True,
            "installed": is_installed,
            "has_mcp_config": False,
            "connected": False,
            "servers": [],
            "mcp_servers_count": 0,
            "config_path": tool_def["config_path"],
            "note": tool_def.get("note", ""),
        }

        mcp_servers = _get_mcp_config_for_tool(tool_def)
        if mcp_servers is None:
            result["note"] = "MCP 配置不存在" if is_installed else "工具未安装"
            results.append(result)
            continue

        result["has_mcp_config"] = True
        result["mcp_servers_count"] = len(mcp_servers)
        if not is_installed:
            result["installed"] = True

        legacy_servers = []
        tool_env_key = tool_def.get("env_key", "env")
        seen_servers = set()
        for det_block in detections:
            for server_name, server_config in mcp_servers.items():
                if server_name in seen_servers:
                    continue
                check = _check_legacy_server(
                    server_name, server_config, env_key=tool_env_key, detection=det_block
                )
                if check["is_legacy"]:
                    seen_servers.add(server_name)
                    legacy_servers.append({
                        "name": server_name,
                        "kind": det_block.get("label", ""),
                        "match_reason": check["match_reason"],
                        "gateway_url": check["gateway_url"],
                        "details": check["server_details"],
                    })
                    if check["gateway_url"]:
                        gateway_url = check["gateway_url"]

        if legacy_servers:
            result["connected"] = True
            result["servers"] = legacy_servers
            connected_count += 1

            # channel completeness: aggregate over every block that declares channels
            present_channels = set()
            for det_block in detections:
                channels = det_block.get("channels") or []
                for server in legacy_servers:
                    label = _legacy_channel_of(server["name"], channels, profile_name)
                    if label:
                        present_channels.add(label)
            missing = []
            for det_block in detections:
                channels = det_block.get("channels") or []
                missing.extend(
                    channel.get("label", "")
                    for channel in channels
                    if channel.get("label") and channel.get("label") not in present_channels
                )
            result["channel_complete"] = not missing
            result["missing_channels"] = missing
        else:
            disconnected_count += 1
            result["channel_complete"] = False
            result["missing_channels"] = []
            if mcp_servers:
                others = list(mcp_servers.keys())
                result["note"] = (
                    f"已配置 {len(mcp_servers)} 个 MCP 服务，但未接入 legacy: "
                    f"{', '.join(others[:3])}"
                )
            else:
                result["note"] = "MCP 配置为空"

        results.append(result)

    return {
        "capable_total": len(mcp_tools),
        "capable_checked": sum(1 for r in results if r["has_mcp_config"]),
        "connected": connected_count,
        "disconnected": disconnected_count,
        "tools": results,
        "gateway_url": gateway_url or "未检测到",
    }


def format_legacy_report(legacy_result: Dict[str, Any]) -> str:
    lines = [
        "=" * 60,
        "  Legacy 通道连通性检查报告",
        "=" * 60,
        "",
        f"  Gateway: {legacy_result.get('gateway_url', '未检测到')}",
        "",
        f"  支持 MCP 的工具总数: {legacy_result['capable_total']}",
        f"  已检查配置:          {legacy_result['capable_checked']}",
        f"  已接入 legacy:       {legacy_result['connected']}",
        f"  未接入 legacy:       {legacy_result['disconnected']}",
        "",
        "── 工具清单 ──",
        "",
    ]

    for tool in legacy_result.get("tools", []):
        icon_installed = "✅" if tool["installed"] else "❌"
        icon_legacy = "🟢" if tool["connected"] else "🔴" if tool["installed"] else "⚪"

        if tool["connected"]:
            server_names = ", ".join(
                f"{s['name']}[{s.get('kind', '')}]" if s.get("kind") else s["name"]
                for s in tool["servers"]
            )
            complete = tool.get("channel_complete", True)
            missing = tool.get("missing_channels", [])
            completeness = "通道完整 ✅" if complete else "⚠️ 缺 " + "、".join(missing)
            lines.append(
                f"  {icon_legacy} {icon_installed} {tool['name']:<15} "
                f"legacy ✓ [{server_names}]  {completeness}"
            )
            for server in tool["servers"]:
                det = server.get("details", {})
                note = det.get("deep_check_note", "")
                if det.get("script_exists") is not None:
                    sc = "✅" if det.get("script_exists") else "❌"
                    kv = "✅" if det.get("key_valid") else "❌"
                    lines.append(
                        f"      └ {server['name']}: 脚本{sc} key{kv}"
                        + (f"  ⚠️ {note}" if note else "")
                    )
                elif det.get("key_valid") is not None:
                    kv = "✅" if det.get("key_valid") else "❌"
                    lines.append(
                        f"      └ {server['name']}: token{kv}"
                        + (f"  ⚠️ {note}" if note else "")
                    )
        elif tool["installed"]:
            lines.append(
                f"  {icon_legacy} {icon_installed} {tool['name']:<15} "
                f"legacy ✗  {tool.get('note', '')}"
            )
        else:
            lines.append(f"  {icon_legacy} {icon_installed} {tool['name']:<15} 未安装")

    lines.extend(["", "=" * 60])
    return "\n".join(lines)