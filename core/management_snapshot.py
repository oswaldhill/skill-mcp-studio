"""Management snapshot (stage-5 P5): one JSON payload for the three-panel GUI.

The stage-2 ``--all-profiles`` snapshot stays as the audit-matrix contract (the
GUI/CLI consistency gate depends on it).  This module builds a **management**
payload shaped for the three panels the user asked for:

- ``agents``   — every IDE/Agent (installed evidence + config correctness);
- ``skills``   — skill inventory + per-client unified/individual link form;
- ``mcp``      — endpoint library + per-client attachment + per-client inventory.

It only reuses read-only engine surfaces (``run_scan``, ``check_agents``,
``endpoint_library``, ``mcp_inventory``, ``skill_state``), so building it never
writes anything.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from combined_checker import check_agents, result_ok
from config_backups import list_config_backups
from endpoint_library import endpoint_entries, resolve_client_attach, validate_attachment
from mcp_entry_risk import is_high_risk_entry
from mcp_inventory import attachment_consistency, inventory_client
from profile_loader import load_profile, list_profiles
from scanner import run_scan
from tool_registry import (
    _abbreviate_home,
    detect_installation,
    normalized_name,
    read_app_versions,
    read_cli_versions,
)
from tool_registry import effective_tools as _tool_registry_effective_tools


def _drift_payload(config_path: str, missing: List[str]) -> Dict[str, Any]:
    """DATA-8: 识别「被外部工具改写」（漂移），与「尚未应用」区分。

    ``~/.codex/config.toml`` 这类文件是**多写者竞争**的：CC Switch 切换通道、
    Codex 应用升级都会重写整份文件，而它们的模板里通常不含用户自建的 MCP 条目，
    于是刚修好的端点会被静默抹掉（实测：修复后 34 秒即被写回旧状态）。

    判据只用一个客观事实：``<config>.bak-*`` 兄弟备份是**本工具写入前**留下的，
    所以只要存在备份、而期望的端点又不见了，就说明写入确实成功过、之后被别的
    程序改掉了。从未写入（无备份）只是「尚未应用」，不报漂移——避免把两件事
    混为一谈。返回证据（丢失项 + 最近备份）而非断言，措辞用「疑似」。
    """
    if not missing:
        return {"suspected": False, "lost": [], "backup_count": 0,
                "last_backup": "", "last_backup_at": ""}
    try:
        backups = list_config_backups(config_path) if config_path else []
    except OSError:
        backups = []
    if not backups:
        return {"suspected": False, "lost": [], "backup_count": 0,
                "last_backup": "", "last_backup_at": ""}
    newest = backups[0]
    return {
        "suspected": True,
        "lost": sorted(missing),
        "backup_count": len(backups),
        "last_backup": _abbreviate_home(newest["path"], os.path.expanduser("~")),
        "last_backup_at": newest["mtime_text"],
    }


def _client_skills_paths(tool: Dict[str, Any], scan_result: Dict[str, Any]) -> List[str]:
    """Skills paths for one client (expanded), from the skills scan rows."""
    wanted = normalized_name(tool.get("name", ""))
    return [
        row.get("expanded_path", "")
        for row in scan_result.get("results", [])
        if normalized_name(row.get("tool_name", "")) == wanted and row.get("expanded_path")
    ]


def _client_skill_stats(tool: Dict[str, Any], scan_result: Dict[str, Any], unified_dir: str) -> Dict[str, Any]:
    wanted = normalized_name(tool.get("name", ""))
    rows = [
        row for row in scan_result.get("results", [])
        if normalized_name(row.get("tool_name", "")) == wanted
    ]
    statuses = [row.get("status", "") for row in rows]
    compliant = bool(rows) and all(s == "correct" for s in statuses)
    link_form = "n/a"
    if rows and rows[0].get("expanded_path") and unified_dir:
        from skill_state import skill_link_form

        forms = {
            skill_link_form(row["expanded_path"], unified_dir)
            for row in rows
            if row.get("expanded_path")
        }
        link_form = "mixed" if len(forms) > 1 else (next(iter(forms)) if forms else "n/a")
    home = os.path.expanduser("~")

    # INFO-1: per-client skill facts for the GUI (dir found / enabled count /
    # total).  Shares read_skill_states with the skills panel so the card never
    # disagrees with the L5 matrix.  Best-effort: any failure degrades to empty
    # counts rather than sinking the snapshot.
    dir_found = False
    enabled_count = 0
    skills_total = 0
    try:
        from skill_state import read_skill_states

        states: Dict[str, str] = {}
        for row in rows:
            ep = row.get("expanded_path") or ""
            if not ep:
                continue
            p = os.path.expanduser(ep)
            if os.path.isdir(p) or os.path.islink(p):
                dir_found = True
                for skill, state in read_skill_states(p, unified_dir).items():
                    if state == "enabled" or skill not in states:
                        states[skill] = state
        enabled_count = sum(1 for v in states.values() if v == "enabled")
        skills_total = len(states)
    except (OSError, ValueError):
        # D-9: 技能状态读取失败按「无状态信息」降级，不再裸吞任意异常。
        pass
    return {
        "skills_compliant": compliant,
        "skill_link_form": link_form,
        "skills_dir_found": dir_found,
        "skills_enabled_count": enabled_count,
        "skills_total": skills_total,
        "skills_paths": [row.get("path", "") for row in rows],
        "expanded_paths": [_abbreviate_home(row.get("expanded_path", ""), home) for row in rows],
    }


def _agent_entry(tool: Dict[str, Any], config: Dict[str, Any], scan_result: Dict[str, Any], unified_dir: str) -> Dict[str, Any]:
    install = detect_installation(tool)
    app_versions = read_app_versions(install["app_paths"])
    cli_versions = read_cli_versions(install["cli_paths"])
    skill_stats = _client_skill_stats(tool, scan_result, unified_dir)
    # B1 fix: skills_compliant must be gated by installed — an uninstalled
    # client may still have residual root symlinks producing scan rows with
    # status 'correct', but it is NOT compliant because it is not installed.
    # The exit-code path (result_ok) already gates on installed; this keeps
    # the management payload (and thus the GUI) consistent with that gate.
    skill_stats["skills_compliant"] = bool(install["installed"]) and skill_stats["skills_compliant"]
    # UI-4 fix: type falls back to infer_tool_type(name) when the registry
    # entry omits it (the tools registry has no type on most entries).
    tool_type = tool.get("type", "") or ""
    if not tool_type:
        try:
            from scanner import infer_tool_type

            tool_type = infer_tool_type(tool.get("name", ""))
        except Exception:
            tool_type = ""
    # DATA-4: per-client attach provenance — distinguish "explicitly declared"
    # from "defaulted to all endpoints" so the UI can label it.  The presence of
    # an ``mcp_attach`` field (post-overlay merge, so client_mcp_attach overlay
    # counts as explicit too) is the authoritative signal; absence = default-all.
    resolved_attach = resolve_client_attach(tool, config)
    has_explicit = bool(tool.get("mcp_attach"))
    return {
        "name": tool.get("name", "Unknown"),
        "type": tool_type,
        "installed": install["installed"],
        "install_state": install["install_state"],
        "install_evidence": install["evidence"],
        # 三类已解析安装证据路径（app bundle / cli 命令 / config 文件）供 UI 展示
        "app_paths": install["app_paths"],
        "app_versions": app_versions,
        "cli_paths": install["cli_paths"],
        "cli_versions": cli_versions,
        "config_paths": install["config_paths"],
        # 客户端 MCP 配置文件路径（与 install 证据的 config_paths 区分）
        "mcp_config_path": tool.get("config_path", ""),
        "aliases": tool.get("aliases", []) or [],
        "mcp_attach": resolved_attach,
        "has_explicit_attach": has_explicit,
        "fix_supported": tool.get("fix_supported", True),
        # FEAT-6: 非 IDE/Agent 客户端（如 CC Switch 这类配置/工具管理器）。它们是
        # 技能挂载点而非客户端，故只在技能审计里可见；UI 据此把它们排除在
        # IDE/Agent 列表与统计之外（否则一个「配置工具」会被算成一个 Agent）。
        "is_agent": not bool(tool.get("non_agent")),
        **skill_stats,
    }


def effective_tools(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """registry ∪ tools registry ∪ discovered(持久化) 去重合并（见 tool_registry.effective_tools）。"""
    return _effective_tools(config)


def _effective_tools(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _tool_registry_effective_tools(config)


def _mcp_inventory_payload(entries: List[Any], tool: Dict[str, Any]) -> List[Dict[str, Any]]:
    """inventory 条目载荷；每条附带高风险判定，供 GUI 分级确认。"""
    payload: List[Dict[str, Any]] = []
    for entry in entries:
        high, reason = is_high_risk_entry(
            {"key": entry.key, "command": entry.command, "args": list(entry.args)}, tool
        )
        payload.append(
            {
                "key": entry.key,
                "url": entry.url,
                "command": entry.command,
                "classification": entry.classification,
                "endpoint_key": entry.endpoint_key,
                "high_risk": high,
                "risk_reason": reason,
            }
        )
    return payload


def build_management_snapshot(
    config: Dict[str, Any],
    config_path: str = "",
    *,
    live_probe: bool = True,
    auto_discover: bool | None = None,
) -> Dict[str, Any]:
    """Assemble the three-panel management payload (read-only)."""
    validate_attachment(config)
    try:
        scan_result = run_scan(config_path=config_path or None, auto_discover=auto_discover)
    except Exception:
        scan_result = {"unified_dir": config.get("unified_skills_dir", "~/.skills"), "results": [], "summary": {}}
    unified_dir = scan_result.get("unified_dir", config.get("unified_skills_dir", "~/.skills"))

    # --- agents: registry ∪ tools registry ∪ discovered, install + config correctness ---
    agents: List[Dict[str, Any]] = []
    for tool in _effective_tools(config):
        agents.append(_agent_entry(tool, config, scan_result, unified_dir))

    # 类型排序：AI Agent → AI IDE → IDE Plugin → 其他（未标注/未知类型排末尾），
    # 同类内按名称字母序稳定排序，与前端 dashboard 的展示顺序一致。
    _type_order = ("AI Agent", "AI IDE", "IDE Plugin")

    def _type_sort_key(a: Dict[str, Any]):
        t = a.get("type") or ""
        rank = _type_order.index(t) if t in _type_order else len(_type_order)
        return (rank, (a.get("name") or "").lower())

    agents.sort(key=_type_sort_key)

    # FEAT-4: auto-discovered new clients (visible so the user can act on them)
    discovered_candidates = [
        {"name": t.get("name", ""), "type": t.get("type", ""), "skills_paths": t.get("skills_paths", [])}
        for t in (scan_result.get("new_tools") or [])
        if isinstance(t, dict)
    ]

    # --- skills: repo inventory + unified dir + per-client enable matrix (FEAT-5) ---
    try:
        from skill_state import repo_skill_names, read_skill_states, read_skill_meta, read_nested_meta, scan_skill_nesting

        skills = repo_skill_names(unified_dir)
        skill_meta = read_skill_meta(unified_dir, skills)
        skill_nesting = scan_skill_nesting(unified_dir)
        nested_meta = read_nested_meta(unified_dir, skill_nesting)
    except Exception:
        skills = []
        skill_meta = {}
        skill_nesting = {}
        nested_meta = {}
    # FEAT-5: per-skill × per-client enable matrix so the GUI can render it
    clients_states: List[Dict[str, Any]] = []
    sorted_skills = sorted(skills)
    for tool in _effective_tools(config):
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        # FEAT-7: 非 IDE/Agent 的客户端（non_agent，如 CC Switch）不进本面板。
        # 它是技能的**管理/安装者**而非消费方，列在这里会让「技能面板 7 个 vs
        # IDE/Agent 表 6 个」自相矛盾——同一个界面里两个数字对不上，用户无从判断
        # 该信哪个。两处口径统一为「本机安装的 IDE/Agent」，此面板不再列它。
        # 仅影响本面板的渲染数据：技能**审计**（combined_checker 遍历
        # scan_result.results 的 managed_names）不经此路径，故 CC Switch 的技能
        # 合规检查照常进行，监督能力不受影响。
        if tool.get("non_agent"):
            continue
        # 一致性门控：skills 面板只保留「本机扫描到」的客户端（installed /
        # config_only），与 home 列表的 install_state!=="none" 判定对齐。未安装
        # 但残留 skills 目录(symlink)的客户端（如已卸载的 TRAE）不应出现——
        # 否则会把这些幽灵客户端误标为「启用了全部技能」。
        if detect_installation(tool)["install_state"] == "none":
            continue
        # 用扫描结果里的实际 skills 路径，而非 tool.get("skills_paths")：同一
        # 客户端可能同时出现在 mcp_tools 段（只有 config_path）和 tools 段
        # （只有 skills_paths），去重后 tool 是 mcp_tools 条目、缺失 skills_paths，
        # 直接取字段会漏掉这些有 skills 挂载的客户端。
        paths = _client_skills_paths(tool, scan_result)
        if not paths:
            continue
        client_dir = os.path.expanduser(paths[0])
        try:
            states = read_skill_states(client_dir, unified_dir)
        except Exception:
            states = {}
        # only keep clients whose path exists, to avoid noise
        if os.path.isdir(client_dir):
            clients_states.append({
                "name": tool["name"],
                "states": {s: states.get(s, "not_in_repo") for s in sorted_skills},
            })
    skills_panel = {
        "unified_dir": unified_dir,
        "skills": sorted_skills,
        "skill_count": len(sorted_skills),
        "clients_states": clients_states,
        "skill_meta": skill_meta,
        "skill_nesting": skill_nesting,
        "nested_meta": nested_meta,
    }

    # --- mcp: endpoint library + per-client attachment + per-client inventory ---
    endpoints = endpoint_entries(config)
    profile_legacy: set = set()
    for entry in endpoints:
        for ln in entry.get("legacy_names", []) or []:
            profile_legacy.add(ln)

    mcp_clients: List[Dict[str, Any]] = []
    for tool in _effective_tools(config):
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        # FEAT-6: 非 IDE/Agent 管理器（CC Switch）不进 MCP 面板——它不消费 MCP，
        # 而是把 MCP 注入别的客户端。留在这里会被渲染成一行「不支持 MCP」，
        # 那是在暗示一个它并不扮演的角色。
        if tool.get("non_agent"):
            continue
        # 一致性门控：mcp 面板与 home / skills 面板对齐，只保留本机扫描到的
        # 客户端（installed / config_only），跳过未安装（none）的幽灵客户端。
        if detect_installation(tool)["install_state"] == "none":
            continue
        legacy = sorted(profile_legacy | set(tool.get("legacy_names", []) or []))
        entries = inventory_client(tool, endpoint_entries=endpoints, legacy_names=legacy)
        # 排序：已挂载(attached) 在上，旧通道(legacy) 次之，未纳管(unmanaged) 沉底。
        # 稳定排序保持同类目下的原始顺序。
        _cls_rank = {"attached": 0, "legacy": 1, "unmanaged": 2}
        entries = sorted(entries, key=lambda e: _cls_rank.get(e.classification, 2))
        # DATA-7: 区分「不支持 MCP」与「缺失」。注册表未声明 mcp_config_path 的
        # 客户端（如 ima.copilot）根本没有 MCP 能力，不适用「期望挂载」这一概念。
        # 此前仍按默认「全部端点」给它套上期望，于是被判成「声明要挂却没挂」的
        # 异常——把能力缺失误报成故障。不支持时期望置空，缺失自然为空。
        supports_mcp = bool(tool.get("config_path"))
        expected_attach = resolve_client_attach(tool, config) if supports_mcp else []
        consistency = attachment_consistency(entries, expected_attach)
        mcp_clients.append({
            "name": tool.get("name", "Unknown"),
            "mcp_attach": expected_attach,
            # 显式声明 vs 默认「全部端点」——UI 据此标注来源
            "has_explicit_attach": bool(tool.get("mcp_attach")),
            # 该客户端是否具备 MCP 能力（未声明 mcp_config_path 即不支持）
            "supports_mcp": supports_mcp,
            # 期望 / 实际 / 缺失(异常) / 未声明
            "observed_attach": consistency["observed"],
            "missing_attach": consistency["missing"],
            "undeclared_attach": consistency["undeclared"],
            # DATA-5:透传 MCP 配置定位字段，供 UI 展示与未来编辑入口
            "config_path": tool.get("config_path", ""),
            "format": tool.get("format", "json"),
            "mcp_key_path": tool.get("mcp_key_path", ["mcpServers"]),
            "inventory": _mcp_inventory_payload(entries, tool),
            # DATA-8: 被外部工具改写（漂移）的客观证据，供 UI 提示 + 一键回流
            "drift": _drift_payload(tool.get("config_path", ""), consistency["missing"]),
        })

    # --- per-endpoint audit conclusion (reusing check_agents) ---
    endpoint_status: Dict[str, Dict[str, Any]] = {}
    for key in list_profiles(config):
        try:
            bundle = load_profile(config, key, config_path=config_path or None)
            result = check_agents(
                config, scan_result, live_probe=live_probe, profile=bundle["profile"], endpoint_key=key
            )
            endpoint_status[key] = {
                "endpoint": result.get("endpoint", ""),
                "ok": result_ok(result),
                "probe": result.get("probe", {}),
                "summary": result.get("summary", {}),
                "records": result.get("records", []),
            }
        except Exception as exc:  # per-endpoint failure must not sink the whole snapshot
            # DATA-3: keep probe schema uniform — exception branch fills the
            # same fields as the normal branch so UI does not branch on shape.
            endpoint_status[key] = {
                "endpoint": "",
                "ok": False,
                "probe": {"initialize_ok": False, "tools_list_ok": False, "tool_names": [], "error": str(exc)},
                "summary": {},
                "records": [],
            }

    # --- mainstream registry (for the unified add panel): name + registered? ---
    registered_names: set = {
        "".join(c for c in str(t["name"]).lower() if c.isalnum())
        for t in _effective_tools(config)
        if isinstance(t, dict) and t.get("name")
    }
    mainstream_tools = []
    try:
        from mainstream_registry import register_mainstream_tools

        mainstream_list = register_mainstream_tools()
        for mt in mainstream_list:
            inst = detect_installation(mt)
            norm = "".join(c for c in mt["name"].lower() if c.isalnum())
            mainstream_tools.append({
                "name": mt["name"],
                "type": mt.get("type", ""),
                "aliases": mt.get("aliases", []),
                "app_bundles": (mt.get("install") or {}).get("app_bundles", []),
                "commands": (mt.get("install") or {}).get("commands", []),
                "config_paths": (mt.get("install") or {}).get("config_paths", []),
                "skills_paths": mt.get("skills_paths", []),
                "config_path": mt.get("config_path", ""),
                "scan_dir": mt.get("scan_dir", ""),
                "format": mt.get("format", "json"),
                "mcp_key_path": mt.get("mcp_key_path", ["mcpServers"]),
                "registered": norm in registered_names,
                "installed": bool(inst["installed"]),
                "install_state": inst["install_state"],
            })
    except Exception:
        mainstream_tools = []

    # --- settings: 只读设置快照（供「设置」页三分区展示）+ 关于版本 ---
    import platform as _platform_mod

    _sys = _platform_mod.system().lower()
    if _sys == "darwin":
        _platform_label = "macOS"
        _default_scan = ["~/.config/*/skills", "~/.*/skills", "~/.config/*/agent/skills"]
    elif _sys == "linux":
        _platform_label = "Linux"
        _default_scan = ["~/.config/*/skills", "~/.*/skills", "~/.config/*/agent/skills"]
    elif _sys == "windows":
        _platform_label = "Windows"
        _default_scan = ["%APPDATA%\\*\\skills", "%USERPROFILE%\\.*\\skills"]
    else:
        _platform_label = _sys
        _default_scan = ["~/.config/*/skills", "~/.*/skills"]

    settings_snapshot = {
        "active_profile": config.get("active_profile", ""),
        "unified_skills_dir": config.get("unified_skills_dir", "~/.skills"),
        "auto_discover": {
            "enabled": bool((config.get("auto_discover") or {}).get("enabled", False)),
            "scan_paths": (config.get("auto_discover") or {}).get("scan_paths", []),
            "exclude_paths": (config.get("auto_discover") or {}).get("exclude_paths", []),
        },
        # A-8: 不再透出 legacy ``unified_mcp`` 旧键——现代端点库由 ``endpoints`` +
        # ``active_profile`` 表达（含 legacy 包装后的规范化视图）。
        "endpoints": endpoints,
        "platform": {
            "os": _platform_label,
            "default_scan_paths": _default_scan,
            "default_unified_dir": config.get("unified_skills_dir", "~/.skills-manager/skills"),
        },
    }
    try:
        from app_info import read_app_info

        app_info = read_app_info()
    except Exception:
        app_info = {"version": "", "build": 0, "build_number": 0, "semver_ok": False, "full": ""}

    return {
        # DATA-6: this payload's schema_version (1) is the *management snapshot*
        # envelope version — distinct from config.yaml's schema_version (1 or 2,
        # the config file format). Disambiguated by the ``kind`` field below.
        "schema_version": 1,
        "kind": "management",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_profile": config.get("active_profile", ""),
        "app": {
            "name": "Skill MCP Studio",
            "version": app_info.get("version", ""),
            "build": app_info.get("build", 0),
            "build_number": app_info.get("build_number", 0),
            "semver_ok": app_info.get("semver_ok", False),
            "full": app_info.get("full", ""),
        },
        "settings": settings_snapshot,
        "agents": agents,
        "discovered_candidates": discovered_candidates,
        "mainstream_tools": mainstream_tools,
        "skills": skills_panel,
        "mcp": {
            "endpoints": endpoints,
            "clients": mcp_clients,
            "endpoint_status": endpoint_status,
        },
    }