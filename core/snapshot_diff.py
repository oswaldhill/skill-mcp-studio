"""快照对比：4 维度变更检测。

对比两次 management_snapshot 的差异，产出结构化变更清单。
用于后台巡检（Phase D）和变更通知（Phase E）。

4 个维度：
  1. IDE/Agent：安装状态翻转、新增/消失客户端
  2. MCP：端点挂载变化、inventory 条目增减
  3. Skill：链接形式变化、新增/删除技能
  4. Hook：hooks_configured 翻转、hook_events 变化
"""

import os
from typing import Any, Dict, List, Optional

import yaml

LAST_SNAPSHOT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "last_snapshot.yaml")
)


def save_last_snapshot(snap: Dict[str, Any]) -> str:
    """持久化当前快照到 data/last_snapshot.yaml（只保存对比所需字段）。"""
    os.makedirs(os.path.dirname(LAST_SNAPSHOT_PATH), exist_ok=True)
    slim = _slim_snapshot(snap)
    with open(LAST_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(slim, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return LAST_SNAPSHOT_PATH


def load_last_snapshot() -> Optional[Dict[str, Any]]:
    """读取上次快照；不存在返回 None。"""
    if not os.path.exists(LAST_SNAPSHOT_PATH):
        return None
    try:
        with open(LAST_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _slim_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    """从完整快照中提取对比所需字段（减小持久化体积）。"""
    out: Dict[str, Any] = {}

    def _slim_agent(a: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": a.get("name"),
            "installed": a.get("installed"),
            "install_state": a.get("install_state"),
            "hooks_configured": a.get("hooks_configured"),
            "hook_events": a.get("hook_events"),
        }

    out["agents"] = [_slim_agent(a) for a in (snap.get("agents") or [])]
    out["mainstream_tools"] = [_slim_agent(a) for a in (snap.get("mainstream_tools") or [])]

    mcp = snap.get("mcp") or {}
    out["mcp"] = {
        "clients": [
            {
                "name": c.get("name"),
                "inventory_keys": sorted(
                    [e.get("key", "") for e in (c.get("inventory") or [])]
                ),
                "observed_attach": c.get("observed_attach"),
            }
            for c in (mcp.get("clients") or [])
        ]
    }

    skills = snap.get("skills") or {}
    out["skills"] = {
        "skills": list(skills.get("skills") or []),
        "clients_states": [
            {"name": cs.get("name"), "states": cs.get("states")}
            for cs in (skills.get("clients_states") or [])
            if isinstance(cs, dict)
        ],
    }
    out["generated_at"] = snap.get("generated_at")
    return out


def compare_snapshots(
    old: Optional[Dict[str, Any]], new: Dict[str, Any]
) -> Dict[str, Any]:
    """对比两次快照，返回 4 维度变更清单。

    返回结构::

        {
            "has_changes": bool,
            "is_first": bool,          # old is None 时 True
            "dimensions": {
                "agents": [...],
                "mcp": [...],
                "skills": [...],
                "hooks": [...],
            },
            "summary": {"agents": N, "mcp": N, "skills": N, "hooks": N},
        }
    """
    if old is None:
        return {"has_changes": False, "is_first": True, "dimensions": {}, "summary": {}}

    new_slim = _slim_snapshot(new)
    changes: Dict[str, List[Dict[str, Any]]] = {
        "agents": [],
        "mcp": [],
        "skills": [],
        "hooks": [],
    }

    _diff_agents(old, new_slim, changes["agents"])
    _diff_mcp(old, new_slim, changes["mcp"])
    _diff_skills(old, new_slim, changes["skills"])
    _diff_hooks(old, new_slim, changes["hooks"])

    has_changes = any(len(v) > 0 for v in changes.values())
    return {
        "has_changes": has_changes,
        "is_first": False,
        "dimensions": changes,
        "summary": {
            "agents": len(changes["agents"]),
            "mcp": len(changes["mcp"]),
            "skills": len(changes["skills"]),
            "hooks": len(changes["hooks"]),
        },
    }


def _agent_map(snap: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """合并 agents + mainstream_tools，按 name 去重（后者覆盖前者）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for a in (snap.get("agents") or []) + (snap.get("mainstream_tools") or []):
        nm = a.get("name")
        if nm:
            out[nm] = a
    return out


def _diff_agents(
    old: Dict[str, Any], new: Dict[str, Any], out: List[Dict[str, Any]]
) -> None:
    """维度 1：IDE/Agent 安装状态翻转、新增/消失。"""
    old_map = _agent_map(old)
    new_map = _agent_map(new)
    for name in sorted(set(old_map) | set(new_map)):
        o = old_map.get(name)
        n = new_map.get(name)
        if o is None:
            out.append({"type": "added", "name": name, "detail": "新增客户端"})
        elif n is None:
            out.append({"type": "removed", "name": name, "detail": "客户端消失"})
        elif o.get("install_state") != n.get("install_state"):
            out.append(
                {
                    "type": "install_state_changed",
                    "name": name,
                    "old": o.get("install_state"),
                    "new": n.get("install_state"),
                    "detail": f"安装状态 {o.get('install_state')} -> {n.get('install_state')}",
                }
            )


def _diff_mcp(
    old: Dict[str, Any], new: Dict[str, Any], out: List[Dict[str, Any]]
) -> None:
    """维度 2：MCP 端点挂载变化、inventory 条目增减。"""
    old_clients = {
        c["name"]: c for c in (old.get("mcp", {}).get("clients") or []) if c.get("name")
    }
    new_clients = {
        c["name"]: c for c in (new.get("mcp", {}).get("clients") or []) if c.get("name")
    }
    for name in sorted(set(old_clients) | set(new_clients)):
        o = old_clients.get(name)
        n = new_clients.get(name)
        if o is None:
            out.append({"type": "added", "name": name, "detail": "新增 MCP 客户端"})
            continue
        if n is None:
            out.append({"type": "removed", "name": name, "detail": "MCP 客户端消失"})
            continue
        old_keys = set(o.get("inventory_keys") or [])
        new_keys = set(n.get("inventory_keys") or [])
        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        if added:
            out.append(
                {
                    "type": "mcp_added",
                    "name": name,
                    "keys": added,
                    "detail": f"新增端点: {', '.join(added)}",
                }
            )
        if removed:
            out.append(
                {
                    "type": "mcp_removed",
                    "name": name,
                    "keys": removed,
                    "detail": f"移除端点: {', '.join(removed)}",
                }
            )


def _diff_skills(
    old: Dict[str, Any], new: Dict[str, Any], out: List[Dict[str, Any]]
) -> None:
    """维度 3：Skill 新增/删除、客户端启用数量变化。"""
    old_list = old.get("skills", {}).get("skills") or []
    new_list = new.get("skills", {}).get("skills") or []
    old_set = set(old_list)
    new_set = set(new_list)
    for name in sorted(old_set | new_set):
        if name not in old_set:
            out.append({"type": "added", "name": name, "detail": "新增技能"})
        elif name not in new_set:
            out.append({"type": "removed", "name": name, "detail": "删除技能"})
    # 客户端启用数量变化
    old_cs = {
        c["name"]: c
        for c in (old.get("skills", {}).get("clients_states") or [])
        if isinstance(c, dict) and c.get("name")
    }
    new_cs = {
        c["name"]: c
        for c in (new.get("skills", {}).get("clients_states") or [])
        if isinstance(c, dict) and c.get("name")
    }
    for name in sorted(set(old_cs) | set(new_cs)):
        o = old_cs.get(name)
        n = new_cs.get(name)
        if o is None or n is None:
            continue
        old_states = o.get("states") or []
        new_states = n.get("states") or []
        old_enabled = sum(1 for s in old_states if isinstance(s, dict) and s.get("status") == "enabled")
        new_enabled = sum(1 for s in new_states if isinstance(s, dict) and s.get("status") == "enabled")
        if old_enabled != new_enabled:
            out.append(
                {
                    "type": "enabled_count_changed",
                    "name": name,
                    "old": old_enabled,
                    "new": new_enabled,
                    "detail": f"启用技能数 {old_enabled} -> {new_enabled}",
                }
            )


def _diff_hooks(
    old: Dict[str, Any], new: Dict[str, Any], out: List[Dict[str, Any]]
) -> None:
    """维度 4：Hook 配置翻转、事件变化。"""
    old_map = _agent_map(old)
    new_map = _agent_map(new)
    for name in sorted(set(old_map) & set(new_map)):
        o = old_map[name]
        n = new_map[name]
        old_cfg = o.get("hooks_configured")
        new_cfg = n.get("hooks_configured")
        if old_cfg != new_cfg:
            out.append(
                {
                    "type": "hooks_configured_changed",
                    "name": name,
                    "old": old_cfg,
                    "new": new_cfg,
                    "detail": f"Hook 接入 {old_cfg} -> {new_cfg}",
                }
            )
        old_ev = set(o.get("hook_events") or [])
        new_ev = set(n.get("hook_events") or [])
        added = sorted(new_ev - old_ev)
        removed = sorted(old_ev - new_ev)
        if added:
            out.append(
                {
                    "type": "hook_events_added",
                    "name": name,
                    "events": added,
                    "detail": f"新增事件: {', '.join(added)}",
                }
            )
        if removed:
            out.append(
                {
                    "type": "hook_events_removed",
                    "name": name,
                    "events": removed,
                    "detail": f"移除事件: {', '.join(removed)}",
                }
            )
