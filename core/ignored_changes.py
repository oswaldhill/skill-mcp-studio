"""变更忽略清单（``data/ignored_changes.yaml``）。

## 为什么需要

后台巡检按 4 维度对比快照，但有些变更是**用户主动接受**的（例如某个客户端
自己改了配置、或用户有意不再接入某端点）。若不给「保持」这个出口，同一条
变更会在每一轮巡检里反复出现并反复弹通知 —— 通知最终会被无视，等于失效。

方案文档 5.4 定的语义：被「保持」的变更记入忽略清单，**直到该变更消失**
（快照不再报告它）或用户主动清除。因此这里存的是「变更指纹」而不是简单开关。

## 指纹怎么算

一条变更由 ``(维度, 名称, 类型)`` 三元组唯一标识：

- 维度：``agents`` / ``mcp`` / ``skills`` / ``hooks``
- 名称：变更所属的客户端或条目名（``change["name"]``）
- 类型：``change["type"]``，如 ``hooks_configured_changed``、``hook_events_removed``

刻意**不把旧值/新值纳入指纹**：同一处配置反复改动仍算同一条变更，用户「保持」
一次即长期有效。若纳入值，每次值变都会重新打扰一次，与「防骚扰」初衷相悖。

## 存储

``data/ignored_changes.yaml``（``data/`` 已在 .gitignore 中，属机器本地状态）：

```yaml
version: 1
ignored:
  - dim: hooks
    name: Cursor
    type: hooks_configured_changed
    ignored_at: '2026-10-10T09:00:00+00:00'
```

文件缺失/损坏时按「空清单」处理：忽略清单是**便利设施**，读不到不应让
变更检测整体失败。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml

#: 相对仓库根的默认位置；调用方可覆盖。
DEFAULT_IGNORED_PATH = os.path.join("data", "ignored_changes.yaml")

#: 指纹三元组的字段名，供 GUI/CLI 复用，避免各处手写字符串。
FINGERPRINT_FIELDS = ("dim", "name", "type")


def change_fingerprint(dim: str, change: Dict[str, Any]) -> Dict[str, str]:
    """把一条变更压成可持久化的指纹。"""
    return {
        "dim": str(dim),
        "name": str(change.get("name", "")),
        "type": str(change.get("type", "")),
    }


def _fingerprint_key(fp: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(fp.get("dim", "")),
        str(fp.get("name", "")),
        str(fp.get("type", "")),
    )


def load_ignored(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取忽略清单；文件缺失或损坏时返回空列表。"""
    target = path or DEFAULT_IGNORED_PATH
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("ignored")
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("dim") and item.get("type"):
            out.append(item)
    return out


def save_ignored(items: List[Dict[str, Any]], path: Optional[str] = None) -> str:
    """写回忽略清单（原子写 + 备份），返回实际写入路径。"""
    from file_atomic import atomic_write, backup_path

    target = path or DEFAULT_IGNORED_PATH
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)

    payload = {"version": 1, "ignored": items}
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    if not content.endswith("\n"):
        content += "\n"

    backup_path(target)  # 首次写入时无备份，函数内部会跳过
    atomic_write(target, content, 0o644)
    return target


def ignored_keys(items: List[Dict[str, Any]]) -> set:
    """把清单转成指纹集合，便于 O(1) 判定。"""
    return {_fingerprint_key(it) for it in items}


def filter_changes(diff: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 diff 里剔除已忽略的变更，并重算 summary / has_changes。

    返回新的 diff（不改原对象）。被剔除的条数记在 ``ignored_count``，
    便于 GUI 显示「N 条已忽略」而不是让用户以为变更凭空消失了。
    """
    keys = ignored_keys(items)
    if not keys:
        out = dict(diff)
        out["ignored_count"] = 0
        return out

    dims_in = diff.get("dimensions") or {}
    dims_out: Dict[str, List[Dict[str, Any]]] = {}
    removed = 0
    for dim, changes in dims_in.items():
        kept = []
        for change in changes or []:
            if not isinstance(change, dict):
                kept.append(change)
                continue
            if _fingerprint_key(change_fingerprint(dim, change)) in keys:
                removed += 1
                continue
            kept.append(change)
        dims_out[dim] = kept

    summary = {dim: len(changes or []) for dim, changes in dims_out.items()}
    out = dict(diff)
    out["dimensions"] = dims_out
    out["summary"] = summary
    out["has_changes"] = any(summary.values())
    out["ignored_count"] = removed
    return out


def add_ignored(
    dim: str,
    name: str,
    change_type: str,
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """把一条变更加入忽略清单（幂等）。返回更新后的清单。"""
    items = load_ignored(path)
    key = (str(dim), str(name), str(change_type))
    if any(_fingerprint_key(it) == key for it in items):
        return items
    items.append({
        "dim": str(dim),
        "name": str(name),
        "type": str(change_type),
        "ignored_at": datetime.now(timezone.utc).isoformat(),
    })
    save_ignored(items, path)
    return items


def remove_ignored(
    dim: str,
    name: str,
    change_type: str,
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """从忽略清单移除一条（幂等）。返回更新后的清单。"""
    items = load_ignored(path)
    key = (str(dim), str(name), str(change_type))
    kept = [it for it in items if _fingerprint_key(it) != key]
    if len(kept) != len(items):
        save_ignored(kept, path)
    return kept


def prune_ignored(
    diff: Dict[str, Any],
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """清除「已不再出现」的忽略项。

    方案文档 5.4：忽略状态持续到**该变更消失**。变更消失后条目应及时清理，
    否则文件会无限增长，且同一个指纹日后重现时会被静默忽略（用户已经忘了
    自己保持过它）。
    """
    items = load_ignored(path)
    if not items:
        return items
    dims = diff.get("dimensions") or {}
    present = set()
    for dim, changes in dims.items():
        for change in changes or []:
            if isinstance(change, dict):
                present.add(_fingerprint_key(change_fingerprint(dim, change)))
    kept = [it for it in items if _fingerprint_key(it) in present]
    if len(kept) != len(items):
        save_ignored(kept, path)
    return kept
