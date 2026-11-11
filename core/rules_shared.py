"""共享约束块：在所有 Agent 的约束文件里维护同一段内容（v0.40.0 用户需求）。

用户：「可以配置一个需要在所有 Agent 中增加的约束内容，然后可以通过同步管理
（和 skill 一样），检查每一个 Agent 是否都拥有这个约束内容；如果没有，可以点击
强制更新进去」。

## 模型

内容存在 ``data/shared_rules.md``，写入每个约束文件时用一对**标记**包起来：

```
<!-- shared-rules:begin v1 -->
（用户配置的内容）
<!-- shared-rules:end -->
```

标记而不是「整体覆盖」的理由：约束文件里**还有用户自己的规则**，整体覆盖会把它们
全部冲掉。标记让写入变成幂等的「替换这一段 / 追加这一段」，其余内容逐字节不动。

## 三条纪律

1. **只碰标记块**：块外的字节一个都不改；没有标记时追加到文件末尾（前面补一个空行）。
2. **写前备份**：``write_rules`` 已经做了「备份 → 原子写 → 回读校验」，这里不另造一套。
3. **检查是只读的**：``audit`` 只读不写，``apply`` 才写，且逐客户端独立成败。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mainstream_registry_data import MAINSTREAM_TOOLS
from rules_files import find_tool

#: 共享块标记（写进文件，因此必须足够显眼、且不会被普通 Markdown 误伤）。
BEGIN = "<!-- shared-rules:begin v1 -->"
END = "<!-- shared-rules:end -->"

_DEFAULT_PATH = "data/shared_rules.md"


#: 逐 Agent 的参与开关存在哪。``None`` = 跟随全局（默认参与）。
_SETTINGS_PATH = "data/shared_rules_settings.json"


def settings_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", _SETTINGS_PATH)
    )


def load_settings() -> Dict[str, bool]:
    """读逐 Agent 开关：``{客户端名: 是否参与}``。缺失 = 参与（默认开）。"""
    import json

    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    clients = raw.get("clients") if isinstance(raw, dict) else None
    if not isinstance(clients, dict):
        return {}
    return {str(k): bool(v) for k, v in clients.items()}


def set_client_enabled(client: str, enabled: bool) -> Dict[str, Any]:
    """开 / 关某个 Agent 的参与开关；写盘沿用「临时文件 + os.replace」。"""
    import json

    if not (client or "").strip():
        return {"ok": False, "reason": "客户端名为空"}
    data = {"clients": load_settings()}
    data["clients"][client] = bool(enabled)
    path = Path(settings_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        return {"ok": False, "reason": f"保存失败：{exc}"}
    return {"ok": True, "client": client, "enabled": bool(enabled)}


def content_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", _DEFAULT_PATH)
    )


def read_content() -> str:
    try:
        return Path(content_path()).read_text(encoding="utf-8")
    except OSError:
        return ""


def write_content(content: str) -> Dict[str, Any]:
    """保存共享内容（空串 = 清空，等于停用这个功能）。"""
    path = Path(content_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content or "", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "reason": f"保存失败：{exc}"}
    return {"ok": True, "path": str(path), "bytes": len((content or "").encode("utf-8"))}


def block_for(content: str) -> str:
    body = (content or "").rstrip("\n")
    return f"{BEGIN}\n{body}\n{END}\n"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def extract(text: str) -> Optional[str]:
    """取出文件里已有的共享块内容；没有块返回 None。"""
    if not text:
        return None
    start = text.find(BEGIN)
    if start < 0:
        return None
    end = text.find(END, start + len(BEGIN))
    if end < 0:
        return None
    inner = text[start + len(BEGIN):end]
    return inner.strip("\n")


def _path_state(raw: str, content: str) -> Dict[str, Any]:
    """单个约束路径对共享块的状态：missing / absent / stale / current / dir。"""
    p = Path(os.path.expanduser(raw))
    base = {"path": raw, "resolved": str(p)}
    if p.is_dir():
        return dict(base, state="dir", reason="规则目录，不参与共享块同步")
    text = _read_text(p) if p.is_file() else None
    if text is None:
        return dict(base, state="missing", reason="文件不存在")
    current = extract(text)
    if current is None:
        return dict(base, state="absent", reason="文件里没有共享块")
    if current == (content or "").rstrip("\n"):
        return dict(base, state="current", reason="已是最新")
    return dict(base, state="stale", reason="共享块内容与当前配置不一致")


def audit(content: Optional[str] = None,
          registry: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """只读检查：每个声明了约束文件的客户端，其各路径与共享块的差异。"""
    body = read_content() if content is None else content
    flags = load_settings()
    rows: List[Dict[str, Any]] = []
    counts = {"current": 0, "stale": 0, "absent": 0, "missing": 0, "dir": 0, "clients": 0}
    for tool in (registry or MAINSTREAM_TOOLS):
        paths = tool.get("rules_paths") or []
        if not paths:
            continue
        states = [_path_state(raw, body) for raw in paths]
        # 一个客户端的整体状态取「最需要处理」的那个：
        # missing > absent > stale > dir > current
        order = ["missing", "absent", "stale", "dir", "current"]
        worst = min(states, key=lambda s: order.index(s["state"]))["state"]
        for s in states:
            counts[s["state"]] = counts.get(s["state"], 0) + 1
        counts["clients"] += 1
        rows.append({
            "name": tool.get("name"),
            "type": tool.get("type"),
            "state": worst,
            # enabled=False 的 Agent 仍列出来（用户要能看到并随时切回来），
            # 但不计入「待处理」，也不参与「同步到全部」。
            "enabled": flags.get(tool.get("name"), True),
            "paths": states,
        })
    return {
        "ok": True,
        "content_bytes": len((body or "").encode("utf-8")),
        "digest": _digest(body or ""),
        "begin": BEGIN,
        "end": END,
        "rows": rows,
        "summary": counts,
    }


def apply(text: str, block: str) -> str:
    """把共享块替换 / 插入到 ``text`` 里（纯函数，便于单测）。"""
    start = text.find(BEGIN)
    if start >= 0:
        end = text.find(END, start + len(BEGIN))
        if end >= 0:
            tail = text[end + len(END):].lstrip("\n")
            return text[:start] + block + (("\n" + tail) if tail else "")
    # 没有块：追加到末尾，保证与上文隔一个空行
    base = text.rstrip("\n")
    return (base + "\n\n" if base else "") + block


def apply_client(client: str, content: Optional[str] = None,
                 registry: Optional[List[Dict[str, Any]]] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
    """把共享块写进某客户端的**全部**约束路径；逐路径回报结果。"""
    from rules_files import write_rules

    body = read_content() if content is None else content
    if not (body or "").strip():
        return {"ok": False, "reason": "共享内容为空，先写内容再同步"}
    tool = find_tool(client, registry)
    if not tool:
        return {"ok": False, "reason": f"未知客户端：{client}"}
    # 未参与的 Agent 不允许被写入：开关的意义就是「这个来源我不管」。
    if not load_settings().get(tool.get("name"), True):
        return {"ok": False, "reason": f"{tool.get('name')} 已关闭共享约束同步"}
    paths = tool.get("rules_paths") or []
    if not paths:
        return {"ok": False, "reason": f"{tool.get('name')} 没有声明约束文件"}

    block = block_for(body)
    results: List[Dict[str, Any]] = []
    for idx, raw in enumerate(paths):
        state = _path_state(raw, body)
        if state["state"] in ("dir",):
            results.append(dict(state, ok=False, skipped=True))
            continue
        if state["state"] == "current":
            results.append(dict(state, ok=True, changed=False))
            continue
        if dry_run:
            results.append(dict(state, ok=True, changed=True, dry_run=True))
            continue
        p = Path(os.path.expanduser(raw))
        existing = _read_text(p) or ""
        merged = apply(existing, block)
        res = write_rules(tool.get("name"), merged, index=idx, registry=registry)
        results.append(dict(state, ok=bool(res.get("ok")), changed=bool(res.get("ok")),
                            backup=res.get("backup", ""), reason=res.get("reason", "")))

    changed = sum(1 for r in results if r.get("changed"))
    failed = [r for r in results if not r.get("ok")]
    return {
        "ok": not failed,
        "client": tool.get("name"),
        "changed": changed,
        "results": results,
        "reason": "" if not failed else f"{len(failed)} 个路径未完成",
    }
