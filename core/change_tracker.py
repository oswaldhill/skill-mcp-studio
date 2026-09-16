"""
变更追踪模块
功能：
- 持久化存储每次扫描的状态快照
- 对比前后两次扫描的差异
- 输出变更报告：工具增减、skills 状态变化等
"""

import os
import yaml
import time
from typing import Dict, Any, List, Optional


STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "state.yaml"
)


def load_previous_state() -> Dict[str, Any]:
    """
    加载上一次扫描的状态快照。

    Returns:
        dict: 上次状态，如果不存在则返回空字典
    """
    state_path = os.path.normpath(STATE_FILE)
    if not os.path.exists(state_path):
        return {
            "version": 1,
            "last_scan_time": None,
            "tools": [],
            "skills_count": 0,
            "summary": {},
        }

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_current_state(scan_result: Dict[str, Any]) -> str:
    """
    保存当前扫描的状态快照。

    Args:
        scan_result: 扫描结果字典

    Returns:
        str: 状态文件路径
    """
    state_path = os.path.normpath(STATE_FILE)
    data_dir = os.path.dirname(state_path)

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # 提取工具状态列表
    tools = []
    skills_set = set()
    for r in scan_result.get("results", []):
        tool_name = r.get("tool_name", "")
        path = r.get("path", "")
        status = r.get("status", "")
        is_installed = r.get("is_installed", False)
        tools.append({
            "name": tool_name,
            "path": path,
            "status": status,
            "is_installed": is_installed,
        })

        # 收集技能目录名（用于后续对比 skills 数量变化）
        expanded = os.path.expanduser(path)
        if os.path.isdir(expanded) or os.path.islink(expanded):
            try:
                for item in os.listdir(expanded):
                    if os.path.isdir(os.path.join(expanded, item)) and not item.startswith("."):
                        skills_set.add(item)
            except Exception:
                pass

    state = {
        "version": 1,
        "last_scan_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_scan_timestamp": int(time.time()),
        "tools": tools,
        "tools_count": len(tools),
        "skills_count": len(skills_set),
        "summary": scan_result.get("summary", {}),
        "unified_dir": scan_result.get("unified_dir", ""),
    }

    with open(state_path, "w", encoding="utf-8") as f:
        yaml.dump(state, f, allow_unicode=True, default_flow_style=False)

    return state_path


def compute_changes(current_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    对比当前结果与上次状态的变更。

    Args:
        current_result: 当前扫描结果

    Returns:
        dict: {
            "has_changes": bool,
            "first_run": bool,        # 是否是首次运行
            "last_scan_time": str,    # 上次扫描时间
            "tools_added": list,      # 新增的工具
            "tools_removed": list,    # 移除的工具
            "tools_status_changed": list,  # 状态变化的工具
            "summary_changes": dict,  # 统计摘要变化
            "new_count": int,         # 新增工具数
            "removed_count": int,     # 移除工具数
            "changed_count": int,     # 状态变化工具数
        }
    """
    prev = load_previous_state()
    current_summary = current_result.get("summary", {})
    prev_summary = prev.get("summary", {})
    prev_tools = prev.get("tools", [])
    current_results = current_result.get("results", [])

    first_run = prev.get("last_scan_time") is None
    last_scan_time = prev.get("last_scan_time", "无历史记录")

    # 构建工具名 → 状态的映射
    prev_map = {}
    for t in prev_tools:
        key = f"{t.get('name', '')}|{t.get('path', '')}"
        prev_map[key] = t.get("status", "")

    curr_map = {}
    for r in current_results:
        key = f"{r.get('tool_name', '')}|{r.get('path', '')}"
        curr_map[key] = {
            "status": r.get("status", ""),
            "is_installed": r.get("is_installed", False),
        }

    tools_added = []
    tools_removed = []
    tools_status_changed = []

    # 找新增和状态变化的工具
    for key, curr_info in curr_map.items():
        if key not in prev_map:
            # 新工具
            name, path = key.split("|", 1)
            tools_added.append({
                "name": name,
                "path": path,
                "status": curr_info["status"],
                "is_installed": curr_info["is_installed"],
            })
        elif prev_map[key] != curr_info["status"]:
            # 状态变化
            name, path = key.split("|", 1)
            tools_status_changed.append({
                "name": name,
                "path": path,
                "from": prev_map[key],
                "to": curr_info["status"],
                "is_installed": curr_info["is_installed"],
            })

    # 找已移除的工具
    for key in prev_map:
        if key not in curr_map:
            name, path = key.split("|", 1)
            tools_removed.append({
                "name": name,
                "path": path,
            })

    # 统计摘要变化
    summary_changes = {}
    all_keys = set(list(prev_summary.keys()) + list(current_summary.keys()))
    for k in all_keys:
        prev_val = prev_summary.get(k, 0)
        curr_val = current_summary.get(k, 0)
        if prev_val != curr_val:
            summary_changes[k] = {
                "from": prev_val,
                "to": curr_val,
                "diff": curr_val - prev_val,
            }

    has_changes = bool(tools_added or tools_removed or tools_status_changed or summary_changes)

    return {
        "has_changes": has_changes,
        "first_run": first_run,
        "last_scan_time": last_scan_time,
        "tools_added": tools_added,
        "tools_removed": tools_removed,
        "tools_status_changed": tools_status_changed,
        "summary_changes": summary_changes,
        "new_count": len(tools_added),
        "removed_count": len(tools_removed),
        "changed_count": len(tools_status_changed),
    }


def format_change_report(changes: Dict[str, Any]) -> str:
    """
    将变更信息格式化为可读字符串。

    Args:
        changes: compute_changes() 的返回结果

    Returns:
        str: 格式化的变更报告
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  变更报告")
    lines.append("=" * 60)
    lines.append("")

    if changes["first_run"]:
        lines.append("  🆕 首次运行，无历史对比数据")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"  上次扫描: {changes['last_scan_time']}")
    lines.append("")

    if not changes["has_changes"]:
        lines.append("  ✅ 无变化")
        lines.append("")
        return "\n".join(lines)

    # 新增工具
    if changes["tools_added"]:
        lines.append(f"  🆕 新增工具 ({changes['new_count']}):")
        for t in changes["tools_added"]:
            label = "✅" if t["is_installed"] else "❌"
            lines.append(f"    {label} {t['name']} ({t['path']}) → {t['status']}")
        lines.append("")

    # 移除工具
    if changes["tools_removed"]:
        lines.append(f"  🗑️ 移除工具 ({changes['removed_count']}):")
        for t in changes["tools_removed"]:
            lines.append(f"    - {t['name']} ({t['path']})")
        lines.append("")

    # 状态变化
    if changes["tools_status_changed"]:
        lines.append(f"  🔄 状态变化 ({changes['changed_count']}):")
        for t in changes["tools_status_changed"]:
            lines.append(f"    {t['name']}: {t['from']} → {t['to']}")
        lines.append("")

    # 统计变化
    if changes["summary_changes"]:
        lines.append("  📊 统计变化:")
        for key, diff_info in changes["summary_changes"].items():
            arrow = "↑" if diff_info["diff"] > 0 else "↓"
            lines.append(f"    {key}: {diff_info['from']} → {diff_info['to']} {arrow}{abs(diff_info['diff'])}")
        lines.append("")

    return "\n".join(lines)
