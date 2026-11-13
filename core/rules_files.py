"""各 AI 客户端的「主要约束文件」发现与读写（2026-11-09 用户需求）。

不同客户端的规则文件各不相同：Claude Code 用 ``CLAUDE.md``、Codex 用
``AGENTS.md``、Gemini CLI 用 ``GEMINI.md``、Cursor 用 ``.cursor/rules/`` 目录……
用户希望在一个地方看清「每个 Agent 的约束文件是什么、有没有配、内容是什么」，
而不是逐个翻目录。

## 三条纪律

1. **不猜路径**：只认注册表（``mainstream_registry_data``）里显式声明的
   ``rules_paths``。客户端没声明就显示「无约定」——猜一个路径去读，猜错会让
   用户以为「这里就是它的配置」，比不显示更糟。
2. **只读预览有上限**：``MAX_PREVIEW_BYTES`` 之外的截断并标注 ``truncated``，
   避免把几十 MB 的日志误当约束文件读进内存、塞进弹框。
3. **写操作先备份再原子写**：复用 ``file_atomic``（备份 → 原子写 → 回读校验），
   与项目其它配置写入同一套安全形状。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from file_atomic import atomic_write, backup_path
from mainstream_registry_data import MAINSTREAM_TOOLS
from tool_registry import normalized_name

#: 单文件预览上限（512 KiB）。超出部分截断并标 ``truncated``。
MAX_PREVIEW_BYTES = 512 * 1024


def _fmt_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return ""


def _count_lines(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def find_tool(client: str, registry: Optional[List[Dict[str, Any]]] = None):
    """按名字 / 别名找注册表条目；找不到返回 None。"""
    target = normalized_name(client or "")
    if not target:
        return None
    for tool in (registry or MAINSTREAM_TOOLS):
        candidates = [tool.get("name") or ""] + list(tool.get("aliases") or [])
        if any(normalized_name(c) == target for c in candidates if c):
            return tool
    return None


def _stat_path(raw: str) -> Dict[str, Any]:
    """单个约束路径的状态（文件或目录）。"""
    p = Path(os.path.expanduser(raw))
    info: Dict[str, Any] = {
        "path": raw, "resolved": str(p), "exists": p.exists(),
        "kind": "", "size": 0, "lines": 0, "files": 0, "mtime": "",
        # v0.46.7：缺失文件可被「修复」创建（write_rules 会新建文件与父目录）。
        # 界面据此决定是否给出「新建并写入」入口；目录类目标不可整体写入。
        "creatable": False,
    }
    if not p.exists():
        info["creatable"] = True
    try:
        if p.is_dir():
            info["kind"] = "dir"
            files = [x for x in p.rglob("*") if x.is_file()]
            info["files"] = len(files)
            info["size"] = sum(x.stat().st_size for x in files)
            info["mtime"] = _fmt_time(p.stat().st_mtime)
        elif p.is_file():
            info["kind"] = "file"
            st = p.stat()
            info["size"] = st.st_size
            info["mtime"] = _fmt_time(st.st_mtime)
            info["lines"] = _count_lines(p)
    except OSError:
        pass
    return info


def discover(registry: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """列出所有声明了 ``rules_paths`` 的客户端的约束文件状态。"""
    rows: List[Dict[str, Any]] = []
    declared = configured = 0
    for tool in (registry or MAINSTREAM_TOOLS):
        paths = tool.get("rules_paths") or []
        if not paths:
            continue
        entries = [_stat_path(raw) for raw in paths]
        declared += len(entries)
        configured += sum(1 for e in entries if e["exists"])
        rows.append({
            "name": tool.get("name"),
            "type": tool.get("type"),
            "paths": entries,
        })
    return {
        "rows": rows,
        "summary": {
            "clients": len(rows),
            "declared": declared,
            "configured": configured,
        },
    }


def read_rules(client: str, index: int = 0,
               registry: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """读取某客户端第 ``index`` 个约束文件的内容（目录则列文件清单）。"""
    tool = find_tool(client, registry)
    if not tool:
        return {"ok": False, "reason": f"未知客户端：{client}"}
    paths = tool.get("rules_paths") or []
    if not paths:
        return {"ok": False, "reason": f"{tool.get('name')} 没有声明约束文件"}
    if index < 0 or index >= len(paths):
        return {"ok": False, "reason": f"{tool.get('name')} 只有 {len(paths)} 个约束路径"}

    raw = paths[index]
    p = Path(os.path.expanduser(raw))
    base = {"ok": True, "client": tool.get("name"), "path": raw,
            "resolved": str(p), "index": index}

    if p.is_dir():
        files = sorted(str(x.relative_to(p)) for x in p.rglob("*") if x.is_file())
        return dict(base, kind="dir", files=files, content="", truncated=False)
    if not p.is_file():
        return dict(base, kind="missing", files=[], content="", truncated=False,
                    reason="文件不存在（可新建）")

    size = p.stat().st_size
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(MAX_PREVIEW_BYTES)
    except OSError as exc:
        return {"ok": False, "reason": f"读取失败：{exc}"}
    return dict(base, kind="file", files=[], content=content,
                size=size, truncated=size > MAX_PREVIEW_BYTES)


def write_rules(client: str, content: str, index: int = 0,
                registry: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """写回某客户端的约束文件：备份 → 原子写 → 回读校验。

    目标是目录时拒绝（不支持把整段文本写进一个规则目录，那会覆盖掉其中
    所有文件）；文件不存在时直接新建（``backup`` 为空）。
    """
    tool = find_tool(client, registry)
    if not tool:
        return {"ok": False, "reason": f"未知客户端：{client}"}
    paths = tool.get("rules_paths") or []
    if index < 0 or index >= len(paths):
        return {"ok": False, "reason": f"{tool.get('name')} 没有第 {index + 1} 个约束路径"}

    raw = paths[index]
    p = Path(os.path.expanduser(raw))
    if p.is_dir():
        return {"ok": False, "reason": "目标是规则目录，不支持整体写入（请在目录内逐文件编辑）"}

    backup = ""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o644
        if p.is_file():
            backup = backup_path(str(p))
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                with open(backup, "w", encoding="utf-8") as bh:
                    bh.write(fh.read())
            mode = p.stat().st_mode & 0o777
        atomic_write(str(p), content, mode)
    except OSError as exc:
        return {"ok": False, "reason": f"写入失败：{exc}", "backup": backup}

    try:
        written = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "reason": f"写入后回读失败：{exc}", "backup": backup}
    if written != content:
        return {"ok": False, "reason": "写入后校验不一致（内容被截断或编码异常）",
                "backup": backup}

    return {"ok": True, "path": str(p), "backup": backup,
            "bytes": len(content.encode("utf-8")),
            "lines": content.count("\n") + (1 if content and not content.endswith("\n") else 0)}
