"""市场源模型（v0.31.0 #4 前半，设计 2026-10-22 §2）。

## 定位

技能市场源从硬编码 ``_SOURCE_SPECS``（skills.sh / qwenwork / enterprise——
后两个是特定会话工具集成，概念错位，用户定案移除）改为**可配置列表**：
``data/market_sources.yaml``（gitignored 个人配置，同 ``discovered_tools``
模式）。文件不存在时回落内置默认 ``[skills.sh]``。

## 通道纪律

读写一律经本模块（CLI ``--list/set/remove-market-source`` 调用）；GUI 经
CLI，不直接碰文件。写操作：读-改-写 + 备份（``file_atomic`` 约定）。

## 源类型

- ``skills-sh``：内置类型，走 ``npx skills`` CLI（社区技能库）；
- ``github-repo``：GitHub 仓库源，API 查最新 tag/release（更新检查用）。

## 语义

- ``id`` 唯一键，``--set-market-source`` 为 upsert；
- ``enabled: false`` = 保留配置但检查/搜索跳过；
- 删除默认源 skills.sh **允许**（用户明确要求可删；删后无其他源时
  更新检查报「无可用市场源」而不是静默）。
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional

import yaml

from file_atomic import atomic_write, backup_path

# 合法源类型（未知 type 拒绝——防手写配置笔误进渲染层）
SOURCE_TYPES = ("skills-sh", "github-repo")

# 内置默认源（文件不存在时的回落；出厂即 skills.sh 一条，用户可删可改）
DEFAULT_SOURCES: List[Dict[str, Any]] = [
    {"id": "skills-sh", "label": "skills.sh 社区技能库", "type": "skills-sh", "enabled": True},
]


def _sources_file() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "market_sources.yaml")
    )


def _normalize(entry: Dict[str, Any]) -> Dict[str, Any]:
    """归一一条源记录：补默认值 + 校验字段。非法条目抛 ValueError。"""
    sid = str(entry.get("id") or "").strip()
    if not sid:
        raise ValueError("市场源缺少 id")
    stype = str(entry.get("type") or "").strip()
    if stype not in SOURCE_TYPES:
        raise ValueError(f"未知市场源类型: {stype!r}（允许: {', '.join(SOURCE_TYPES)}）")
    url = str(entry.get("url") or "").strip()
    if stype == "github-repo" and not url:
        raise ValueError(f"github-repo 源 {sid!r} 缺少 url")
    return {
        "id": sid,
        "label": str(entry.get("label") or sid).strip(),
        "type": stype,
        "url": url or None,
        "enabled": bool(entry.get("enabled", True)),
    }


def list_sources(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读源清单：文件不存在 → 内置默认；存在 → 逐条归一（坏条目跳过并带 reason）。

    返回 ``{"sources": [...], "fallback": bool, "invalid": [...]}`` 的扁平
    dict 由调用方组装；本函数返回 (sources, fallback, invalid) 三元组。
    """
    src_path = path or _sources_file()
    if not os.path.isfile(src_path):
        return list(DEFAULT_SOURCES), True, []
    try:
        with open(src_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or []
    except (OSError, yaml.YAMLError):
        return list(DEFAULT_SOURCES), True, []
    if not isinstance(raw, list):
        return list(DEFAULT_SOURCES), True, []
    sources: List[Dict[str, Any]] = []
    invalid: List[Dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            sources.append(_normalize(entry))
        except ValueError as exc:
            invalid.append({"id": str(entry.get("id") or "?"), "reason": str(exc)})
    # 空列表文件 = 用户明确清空了所有源（合法状态：删光默认源后），
    # **不得**回落默认——否则「删除全部源」永远删不掉（违背可删定案）。
    # 只有「文件不存在」才回落默认（从未配置过）。
    return sources, False, invalid


def set_source(
    sid: str,
    *,
    label: str,
    stype: str,
    url: str = "",
    enabled: bool = True,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """upsert 一条源（id 唯一键）。返回 {status, message, backup}。"""
    src_path = path or _sources_file()
    entry = {"id": sid, "label": label, "type": stype, "url": url, "enabled": enabled}
    normalized = _normalize(entry)  # 校验失败抛 ValueError
    sources, _fb, _inv = list_sources(src_path)
    existing = next((s for s in sources if s["id"] == normalized["id"]), None)
    if existing is not None:
        sources = [normalized if s["id"] == normalized["id"] else s for s in sources]
        action = "updated"
    else:
        sources.append(normalized)
        action = "added"
    backup = _write_sources(src_path, sources)
    return {
        "status": "ok",
        "action": action,
        "backup": backup,
        "message": f"市场源 {normalized['id']} 已{'更新' if action == 'updated' else '添加'}"
                   f"（{normalized['label']} · {normalized['type']}）",
    }


def remove_source(sid: str, *, path: Optional[str] = None) -> Dict[str, Any]:
    """删除一条源（含默认源——用户明确要求可删）。不存在报 unchanged。"""
    src_path = path or _sources_file()
    sources, fallback, _inv = list_sources(src_path)
    remaining = [s for s in sources if s["id"] != sid]
    if len(remaining) == len(sources):
        return {"status": "unchanged", "backup": "", "message": f"市场源 {sid} 不存在"}
    backup = _write_sources(src_path, remaining)
    note = "（已无可用市场源，更新检查将提示配置源）" if not remaining else ""
    return {
        "status": "ok",
        "backup": backup,
        "message": f"市场源 {sid} 已删除{note}",
    }


def _write_sources(src_path: str, sources: List[Dict[str, Any]]) -> str:
    """写回源文件（先备份）。目录不存在则创建。"""
    backup = ""
    if os.path.isfile(src_path):
        backup = backup_path(src_path)
        shutil.copy2(src_path, backup)
    parent = os.path.dirname(src_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    rendered = yaml.safe_dump(sources, allow_unicode=True, default_flow_style=False)
    atomic_write(src_path, rendered, 0o644)
    return backup
