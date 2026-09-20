"""MCP 条目删除编排：分类挑 key、高风险门、attach 声明同步、空声明拒绝。

落盘逻辑 100% 复用既有安全链——条目删除走
``mcp_fixer.remove_mcp_entries_tool``，挂载声明走
``endpoint_store.set_client_attach``（写 ``client_mcp_attach`` overlay）。本模块
只做编排与门禁，不新增任何写盘路径。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from endpoint_library import resolve_client_attach
from endpoint_store import set_client_attach
from mcp_entry_risk import is_high_risk_entry
from mcp_fixer import remove_mcp_entries_tool
from mcp_inventory import inventory_client
from tool_registry import effective_tools, normalized_name

CLASSES = ("attached", "legacy", "unmanaged")


def _find_tool(config: Dict[str, Any], client_name: str) -> Optional[Dict[str, Any]]:
    wanted = normalized_name(client_name)
    for tool in effective_tools(config):
        if not isinstance(tool, dict):
            continue
        if normalized_name(tool.get("name", "")) == wanted:
            return tool
    return None


def _endpoint_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    from endpoint_library import list_endpoints  # 局部导入避免循环

    profiles = config.get("profiles") or {}
    entries: List[Dict[str, Any]] = []
    for key in list_endpoints(config):
        profile = profiles.get(key) or {}
        entry = {"key": key, "name": profile.get("name", key)}
        for legacy in profile.get("legacy_names", []) or []:
            entry.setdefault("legacy_names", []).append(legacy)
        entries.append(entry)
    return entries


def _legacy_names(config: Dict[str, Any], tool: Dict[str, Any]) -> List[str]:
    names = set(tool.get("legacy_names", []) or [])
    for entry in _endpoint_entries(config):
        names.update(entry.get("legacy_names", []) or [])
    return sorted(names)


def client_entries(config: Dict[str, Any], tool: Dict[str, Any]) -> List[Any]:
    """该客户端当前全部 MCP 条目（已分类）。"""
    return inventory_client(
        tool,
        endpoint_entries=_endpoint_entries(config),
        legacy_names=_legacy_names(config, tool),
    )


def _annotate(entry: Any, tool: Dict[str, Any]) -> Dict[str, Any]:
    high, reason = is_high_risk_entry(
        {"key": entry.key, "command": entry.command, "args": list(entry.args)}, tool
    )
    return {
        "key": entry.key,
        "classification": entry.classification,
        "endpoint_key": entry.endpoint_key,
        "high_risk": high,
        "risk_reason": reason,
    }


def _plan(
    config: Dict[str, Any],
    tool: Dict[str, Any],
    keys: List[str],
    *,
    force_high_risk: bool,
) -> Dict[str, Any]:
    """把待删 key 解析为「可删 / 高危 / 不存在 / 声明变更 / 拒绝」。"""
    entries = {entry.key: entry for entry in client_entries(config, tool)}
    annotated = {entry.key: _annotate(entry, tool) for entry in entries.values()}

    existing = [k for k in keys if k in entries]
    missing = [k for k in keys if k not in entries]
    blocked = [annotated[k] for k in existing if annotated[k]["high_risk"]]
    if blocked and not force_high_risk:
        return {"refused": True, "high_risk": blocked, "existing": existing, "missing": missing}

    attach_keys: List[str] = []
    for key in existing:
        entry = entries[key]
        if entry.classification == "attached" and entry.endpoint_key:
            attach_keys.append(entry.endpoint_key)

    declaration = list(resolve_client_attach(tool, config))
    remaining = [k for k in declaration if k not in attach_keys]
    if attach_keys and not remaining:
        return {
            "refused": True,
            "empty_declaration": True,
            "existing": existing,
            "missing": missing,
            "high_risk": [],
        }

    return {
        "refused": False,
        "existing": existing,
        "missing": missing,
        "high_risk": [],
        "attach_keys": attach_keys,
        "remaining": remaining,
        "explicit_attach": bool(tool.get("mcp_attach")),
    }


def remove_entries(
    config: Dict[str, Any],
    client_name: str,
    keys: List[str],
    *,
    force_high_risk: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """删除指定 key 的 MCP 条目（含 attached 声明同步）。"""
    tool = _find_tool(config, client_name)
    if tool is None:
        return {"status": "error", "message": f"未找到客户端 {client_name}", "removed": []}

    plan = _plan(config, tool, keys, force_high_risk=force_high_risk)
    base = {
        "removed": [],
        "skipped_high_risk": [],
        "attach_updated": [],
        "path": tool.get("config_path", ""),
        "backup": "",
    }
    if plan.get("empty_declaration"):
        base["status"] = "refused"
        base["message"] = (
            "拒绝：删除后该客户端的挂载声明将变为空，而本项目语义中"
            "「空声明」等同于「挂载全部端点」，会回弹成挂载全部。"
            "如需彻底断开，请改用端点库 / 客户端管理。"
        )
        return base
    if plan.get("refused"):
        base["status"] = "refused"
        base["high_risk"] = plan["high_risk"]
        base["message"] = "拒绝：以下条目疑似客户端自带，需显式确认后才能删除：" + "、".join(
            h["key"] for h in plan["high_risk"]
        )
        return base
    if not plan["existing"]:
        base["status"] = "unchanged"
        base["message"] = "没有匹配到要移除的条目"
        return base

    if dry_run:
        base["status"] = "dry-run"
        base["message"] = "将移除：" + "、".join(plan["existing"])
        return base

    # 先删配置条目：若随后的声明更新失败，下一次「修复 MCP」会把条目装回来（自愈）。
    outcome = remove_mcp_entries_tool(tool, plan["existing"])
    base["status"] = outcome.get("status", "error")
    base["message"] = outcome.get("message", "")
    base["backup"] = outcome.get("backup", "")
    if outcome.get("status") != "updated":
        return base

    base["removed"] = list(plan["existing"])
    if not plan["attach_keys"]:
        return base

    store_result = set_client_attach(config, tool.get("name", client_name), plan["remaining"])
    if store_result.get("status") not in ("ok", "dry-run"):
        base["status"] = "error"
        base["message"] = (
            "配置条目已移除，但挂载声明更新失败（"
            + str(store_result.get("message", ""))
            + "）。下次「修复 MCP」可能重新写入该条目；可用「从备份恢复」回滚。"
        )
        return base

    base["attach_updated"] = list(plan["attach_keys"])
    return base


def remove_class(
    config: Dict[str, Any],
    client_name: str,
    klass: str,
    *,
    include_high_risk: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """按分类批量清理一个客户端的 MCP 条目。"""
    if klass not in CLASSES:
        return {
            "status": "error",
            "message": f"未知分类 {klass}；可选：{'、'.join(CLASSES)}",
            "removed": [],
        }
    tool = _find_tool(config, client_name)
    if tool is None:
        return {"status": "error", "message": f"未找到客户端 {client_name}", "removed": []}

    annotated = [_annotate(entry, tool) for entry in client_entries(config, tool)]
    targets = [item["key"] for item in annotated if item["classification"] == klass]
    skipped = [item for item in annotated if item["classification"] == klass and item["high_risk"]]
    if not include_high_risk:
        targets = [key for key in targets if key not in {s["key"] for s in skipped}]

    result = remove_entries(
        config, client_name, targets, force_high_risk=include_high_risk, dry_run=dry_run
    )
    result.setdefault("skipped_high_risk", [])
    if not include_high_risk:
        result["skipped_high_risk"] = [
            {"key": item["key"], "reason": item["risk_reason"]} for item in skipped
        ]
    return result