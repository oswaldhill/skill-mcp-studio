"""技能来源（provenance）：按仓库分组展示已安装技能。

**为什么读 `npx skills` 的 lock 而不是自建来源表**（2026-11-15）：
`~/.agents/.skill-lock.json` 已经记录了每个技能的 `source`（`owner/repo`）、
`sourceUrl`、`installedAt`、`updatedAt`。再维护一份自己的来源表，迟早与
上游漂移——而漂移后的两份数据没人能判断哪份对。所以这里只做**只读投影**：
把 lock 的内容整理成适合界面展示的形状，不写回、不缓存到别处。

**缺口必须如实报出**：实测本机 164 个技能里只有 47 个在 lock 有来源登记
（其余来自整仓库形态的技能库、手工拷入等）。`summarize()` 会同时给出
`recorded` 与 `unrecorded`，界面据此说明「来源只覆盖 N/M」，绝不把
「没有记录」呈现成「没有来源」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 未记录来源时的分组名。用文字而不是空串，便于界面直接展示。
UNKNOWN_SOURCE = "(未记录来源)"


def _default_lock_path() -> Path:
    """`npx skills` 的 lock 位置（`~/.agents/.skill-lock.json`）。

    独立成函数便于测试替换，不读环境变量——GUI 从 Finder 启动时是 launchd
    最小环境，靠 env 覆盖路径在真实场景里不可靠。
    """
    return Path.home() / ".agents" / ".skill-lock.json"


def read_skills(lock_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读取 lock 里的技能来源记录。文件缺失或损坏一律返回空列表。

    这里刻意不抛异常：来源视图是**附加信息**，它出问题时不该把整个
    Skills 页面拖垮。调用方通过返回空列表 + summarize 的 unrecorded
    数字知道「查不到」，而不是「没有」。
    """
    path = lock_path or _default_lock_path()
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get("skills", payload)
    if not isinstance(records, dict):
        return []

    rows: List[Dict[str, Any]] = []
    for name, rec in records.items():
        if not isinstance(rec, dict):
            continue
        rows.append({
            "name": str(name),
            "source": str(rec.get("source") or "").strip(),
            "source_url": str(rec.get("sourceUrl") or "").strip(),
            "source_type": str(rec.get("sourceType") or "").strip(),
            "installed_at": str(rec.get("installedAt") or "").strip(),
            "updated_at": str(rec.get("updatedAt") or "").strip(),
        })
    rows.sort(key=lambda r: r["name"])
    return rows


def group_by_source(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按来源仓库分组。组按技能数降序；组内按安装时间倒序（新的在前）。

    排序口径的理由：用户来这个视图通常是想「把某仓库装的一批一起处理」，
    所以分组顺序按批次大小；组内按时间倒序，最近的安装先看到。
    """
    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = row.get("source") or UNKNOWN_SOURCE
        bucket = buckets.setdefault(key, {
            "source": key,
            "source_url": row.get("source_url") or "",
            "skills": [],
        })
        bucket["skills"].append(row)
        if not bucket["source_url"] and row.get("source_url"):
            bucket["source_url"] = row["source_url"]

    groups = list(buckets.values())
    for g in groups:
        g["count"] = len(g["skills"])
        g["skills"].sort(key=lambda r: r.get("installed_at") or "", reverse=True)
    groups.sort(key=lambda g: (-g["count"], g["source"]))
    return groups


def summarize(rows: List[Dict[str, Any]],
              installed_total: Optional[int] = None) -> Dict[str, Any]:
    """给出覆盖情况：记录了几条、涉及几个来源、还有多少没记录。

    ``installed_total`` 是统一库里实际装着的技能数。传了它才能算出
    `unrecorded`；不传就只报已记录的部分，且 `complete` 为 None
    （不知道总数不等于"全都有记录"）。
    """
    sources = {r.get("source") or UNKNOWN_SOURCE for r in rows}
    out: Dict[str, Any] = {
        "recorded": len(rows),
        "sources": len(sources),
        "installed_total": installed_total,
        "unrecorded": None,
        "complete": None,
    }
    if installed_total is not None:
        out["unrecorded"] = max(int(installed_total) - len(rows), 0)
        out["complete"] = out["unrecorded"] == 0
    return out


def provenance_payload(lock_path: Optional[Path] = None,
                       installed_total: Optional[int] = None) -> Dict[str, Any]:
    """一次给出界面要的全部内容：分组 + 汇总。CLI 与 GUI 共用同一出口。"""
    rows = read_skills(lock_path=lock_path)
    return {
        "kind": "skill-provenance",
        "groups": group_by_source(rows),
        "summary": summarize(rows, installed_total=installed_total),
    }