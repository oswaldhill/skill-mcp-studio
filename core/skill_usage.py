"""技能使用统计（只读、零侵入）。

数据来源是各 Agent 客户端落盘的会话日志。目前唯一可靠通路是 Codex 的
rollout jsonl：~/.codex/archived_sessions 与 ~/.codex/sessions。其它客户端
目录存在但格式不稳定，暂不纳入，用 source 字段留扩展位。

关键约束（实测得出，勿凭直觉改动）：

1. **只能从工具调用记录里提取路径**。每个会话都会往 developer message 里
   注入完整的 host_skills 清单（所有已装技能名都在里面）。若直接 grep 技能名
   或其 SKILL.md 路径，会把「被注入的清单」当成「被使用」，命中数虚高到
   100% 误报。因此本模块只解析 payload.type ∈ {function_call, custom_tool_call}
   的记录 —— 那才是模型真正发起的一次读/写动作。

2. **arguments 是二次编码的 JSON 字符串**。function_call 的 arguments、
   custom_tool_call 的 input 都可能是字符串，路径里的 "/" 在 JSON 里会写成
   "\\/"。所以匹配前统一把 "\\/" 还原成 "/"，否则正则在多数行上都落空。

3. **三档动作**，用于判断"到底有没有在用"：
   - load   : 引用到 <skill>/ 下的具体文件（绝大多数是 SKILL.md）。
              代表技能指令被读取或被派给子 agent，是"在用"的强信号。
   - browse : 只 <skill>/ 目录级出现，没有更深路径。典型是 ls 技能目录。
              弱信号，多为浏览/探查。
   - edit   : apply_patch / write / edit 改写技能文件。这是"维护"动作，
              既不算使用，也提示该技能正被人工调整（后续合并/归一要留意）。

时间戳是 ISO 8601 字符串（UTC，形如 2026-05-09T05:19:27.508Z），字典序即
时间序，直接取 max/min。

本模块只读文件、不写盘；任何写操作都不在这里发生（项目铁律）。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

# 统一技能库：只有这一个真实目录，其余客户端 skills 都是它的 symlink。
_SKILLS_SUB = ".skills-manager/skills"

# 会引用技能路径的写类工具。命中即归入 edit（维护动作，不计入使用）。
_WRITE_TOOLS = {
    "apply_patch", "write", "write_file", "edit", "edit_file",
    "str_replace", "multi_edit", "notebook_edit", "fs_write",
}

# 判「深入技能目录」：名字后必须还有至少一个真实路径段。
# 只写 `skills/hermes/`（尾斜杠、无后续段）是目录级浏览，不算深入 —— 早期版本
# 用 (\/)? 前瞻会把 `ls skills/hermes/` 误判成 load。
_SKILL_DEEP_RE = re.compile(r"skills/([A-Za-z0-9._-]+)/([^\s\"'\\]+)")
_SKILL_ANY_RE = re.compile(r"skills/([A-Za-z0-9._-]+)")


def _home() -> str:
    return os.path.expanduser("~")


def _skills_dir(skills_dir: str | None = None) -> str:
    if skills_dir:
        return os.path.expanduser(skills_dir)
    return os.path.join(_home(), _SKILLS_SUB)


def _default_session_dirs() -> list[str]:
    base = os.path.join(_home(), ".codex")
    return [
        os.path.join(base, "archived_sessions"),
        os.path.join(base, "sessions"),
    ]


def _iter_session_files(dirs: list[str]) -> list[str]:
    """递归收集 *.jsonl。

    ~/.codex/sessions 是按日期嵌套的（sessions/2026/MM/DD/*.jsonl），只扫顶层
    会把最新会话全部漏掉 —— 实测那里比 archived_sessions 还多。
    """
    files: list[str] = []
    seen: set[str] = set()
    for d in dirs:
        d = os.path.expanduser(d)
        if not os.path.isdir(d):
            continue
        for root, _dirs, names in os.walk(d):
            for name in sorted(names):
                if not name.endswith(".jsonl"):
                    continue
                full = os.path.join(root, name)
                key = os.path.realpath(full)
                if key in seen:
                    continue
                seen.add(key)
                files.append(full)
    files.sort()
    return files


def _payload_text(payload: dict) -> str | None:
    """把一条工具调用 payload 归一成一段可搜索文本（已还原 JSON 斜杠转义）。"""
    ptype = payload.get("type")
    raw: object = None
    if ptype == "function_call":
        raw = payload.get("arguments")
    elif ptype == "custom_tool_call":
        raw = payload.get("input")
    else:
        return None
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        text = json.dumps(raw, ensure_ascii=False)
    else:
        text = str(raw)
    # JSON 字符串里的 \/ 还原成 /
    return text.replace("\\/", "/")


def _classify_tool(payload: dict) -> str:
    """返回 load / edit；用于该技能被判定为「触达」时的动作归类基础。"""
    name = (payload.get("name") or "").strip()
    return "edit" if name in _WRITE_TOOLS else "load"


def _skills_touched(text: str) -> list[tuple[str, bool]]:
    """技能名 -> 是否深入该目录（名字后还有路径段，通常是 SKILL.md）。

    `ls skills/hermes/` 只有目录级引用 → deep=False（浏览）。
    `cat skills/hermes/SKILL.md` 触达具体文件 → deep=True（加载）。
    """
    best: dict[str, bool] = {}
    for m in _SKILL_ANY_RE.finditer(text):
        sname = m.group(1)
        if sname:
            best.setdefault(sname, False)
    for m in _SKILL_DEEP_RE.finditer(text):
        sname = m.group(1)
        if sname:
            best[sname] = True
    return [(n, d) for n, d in best.items() if n not in ("", ".", "..")]


def _iso_valid(ts: str) -> bool:
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def write_progress(
    progress_path: str | None,
    phase: str,
    done: int,
    total: int | None,
    extra: dict | None = None,
) -> None:
    """把扫描进度原子写入 progress_path（供 GUI 轮询）。

    进度是"过程信号"，不是结论：写失败一律吞掉，绝不影响统计本身。
    total 为 None 表示总量未知（例如此时还在收集文件列表），前端会退回只显示
    「已扫 N」而不是伪造一个百分比。
    """
    if not progress_path:
        return
    payload = {
        "phase": phase,
        "done": int(done),
        "total": int(total) if total is not None else None,
        "pct": int(round(done * 100 / total)) if total else None,
        "ts": datetime.now().timestamp(),
    }
    if extra:
        payload.update(extra)
    try:
        tmp = f"{progress_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, progress_path)
    except OSError:
        pass


def scan_usage(
    session_dirs: list[str] | None = None,
    skills_dir: str | None = None,
    limit_files: int | None = None,
    since: str | None = None,
    progress_path: str | None = None,
) -> dict:
    """扫描会话日志，返回每个技能的使用画像。

    since: 可选 ISO 日期前缀（如 "2026-09-01"），只统计该时间之后的动作。
           时间戳同为 UTC ISO 串，字典序即时间序，直接前缀比较。

    结构：
      {
        "source": "codex",
        "scanned_files": int,
        "sessions_dir": [..实际存在且被扫描的目录..],
        "tool_calls": int,               # 参与统计的工具调用总数
        "skills": {
          name: {
            "name", "load", "browse", "edit", "used",
            "sessions", "last_used", "first_used", "last_edit",
            "tools": {tool_name: count}
          }, ...
        },
        "ranking": [ {name, load, browse, edit, used, last_used}, ... ],  # 按 load 降序
        "summary": {
          "installed": int, "installed_names": [..],
          "used": int, "loaded": int, "browse_only": int,
          "never_used": [..],            # 已装但日志里零触达 → 清理候选
          "unused_load": [..],           # 已装、只有 browse/edit、从未 load
        },
      }
    """
    dirs = session_dirs if session_dirs is not None else _default_session_dirs()
    write_progress(progress_path, "收集会话文件", 0, None)
    files = _iter_session_files(dirs)
    scanned_dirs = sorted({os.path.dirname(f) for f in files})
    if limit_files is not None:
        files = files[:limit_files]

    total_files = len(files)
    write_progress(progress_path, "扫描会话文件", 0, total_files)

    since_prefix = since.strip() if isinstance(since, str) and since.strip() else None

    # name -> 累计状态
    state: dict[str, dict] = {}
    tool_calls = 0

    for idx, path in enumerate(files, 1):
        # 进度按文件粒度汇报：total_files 已知，所以这里是"准确进度"而非估算。
        # 每 5 个文件刷一次，避免把扫描拖慢在写盘上。
        if idx % 5 == 0 or idx == total_files:
            write_progress(progress_path, "扫描会话文件", idx, total_files)
        session_key = os.path.basename(path)
        try:
            fh = open(path, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                # 坏行 / `null` / 裸数组都可能出现，非对象一律跳过。
                if not isinstance(rec, dict):
                    continue
                if rec.get("type") != "response_item":
                    continue
                payload = rec.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") not in ("function_call", "custom_tool_call"):
                    continue
                text = _payload_text(payload)
                if not text or "skills/" not in text:
                    continue
                ts = rec.get("timestamp")
                ts = ts if isinstance(ts, str) and _iso_valid(ts) else None
                # since 过滤：没有时间戳的记录在限定窗口时不计入（无法判断新旧）。
                if since_prefix and (ts is None or ts < since_prefix):
                    continue
                tool_calls += 1
                base_action = _classify_tool(payload)
                tool_name = (payload.get("name") or "?").strip() or "?"
                for sname, deep in _skills_touched(text):
                    st = state.setdefault(sname, {
                        "name": sname, "load": 0, "browse": 0, "edit": 0,
                        "sessions": set(), "last_used": None,
                        "first_used": None, "last_edit": None, "tools": {},
                    })
                    if base_action == "edit":
                        st["edit"] += 1
                        if ts and (st["last_edit"] is None or ts > st["last_edit"]):
                            st["last_edit"] = ts
                    elif deep:
                        st["load"] += 1
                    else:
                        st["browse"] += 1
                    # 使用/浏览/编辑任一都推进 last_used；edit 也算"最后动过"
                    if ts:
                        if st["last_used"] is None or ts > st["last_used"]:
                            st["last_used"] = ts
                        if st["first_used"] is None or ts < st["first_used"]:
                            st["first_used"] = ts
                    st["sessions"].add(session_key)
                    st["tools"][tool_name] = st["tools"].get(tool_name, 0) + 1

    installed = _installed_skills(skills_dir)
    installed_names = sorted(installed)

    skills_out: dict[str, dict] = {}
    for sname, st in state.items():
        load, browse, edit = st["load"], st["browse"], st["edit"]
        used = (load + browse + edit) > 0
        skills_out[sname] = {
            "name": sname,
            "load": load,
            "browse": browse,
            "edit": edit,
            "used": used,
            "sessions": len(st["sessions"]),
            "last_used": st["last_used"],
            "first_used": st["first_used"],
            "last_edit": st["last_edit"],
            "tools": dict(sorted(st["tools"].items(), key=lambda kv: -kv[1])),
        }

    ranking = sorted(
        skills_out.values(),
        key=lambda s: (s["load"], s["browse"], s["last_used"] or ""),
        reverse=True,
    )
    ranking = [
        {"name": s["name"], "load": s["load"], "browse": s["browse"],
         "edit": s["edit"], "used": s["used"], "last_used": s["last_used"]}
        for s in ranking
    ]

    loaded_set = {n for n, s in skills_out.items() if s["load"] > 0}
    touched_set = set(skills_out.keys())
    never_used = [n for n in installed_names if n not in touched_set]
    unused_load = [
        n for n in installed_names
        if n in touched_set and n not in loaded_set
    ]

    write_progress(progress_path, "完成", total_files, total_files)

    return {
        "source": "codex",
        "scanned_files": len(files),
        "sessions_dir": scanned_dirs,
        "since": since_prefix,
        "tool_calls": tool_calls,
        "skills": skills_out,
        "ranking": ranking,
        "summary": {
            "installed": len(installed_names),
            "installed_names": installed_names,
            "used": len(touched_set & installed),
            "loaded": len(loaded_set & installed),
            "browse_only": len(unused_load),
            "never_used": never_used,
            "unused_load": unused_load,
        },
    }


def _installed_skills(skills_dir: str | None) -> set[str]:
    root = _skills_dir(skills_dir)
    out: set[str] = set()
    if not os.path.isdir(root):
        return out
    try:
        entries = os.listdir(root)
    except OSError:
        return out
    for name in entries:
        if name.startswith("."):          # .git 等隐藏目录不是技能
            continue
        full = os.path.join(root, name)
        if os.path.isdir(full):
            out.add(name)
    return out


def summarize_text(payload: dict) -> str:
    """把 scan_usage 结果渲染成人读要点（供 CLI 非 JSON 出口复用）。"""
    s = payload["summary"]
    lines = [
        f"  数据来源: {payload['source']}｜扫描 {payload['scanned_files']} 个会话文件"
        f"｜命中技能的工具调用 {payload['tool_calls']} 次",
        f"  已装 {s['installed']}｜被读取加载 {s['loaded']}｜仅浏览/编辑 {s['browse_only']}"
        f"｜零触达 {len(s['never_used'])}",
        "",
        "  使用排行（按加载次数）：",
    ]
    for i, r in enumerate(payload["ranking"][:15], 1):
        when = (r["last_used"] or "")[:10] or "-"
        lines.append(
            f"    {i:>2}. {r['name']:<28} load={r['load']:<4} "
            f"browse={r['browse']:<3} edit={r['edit']:<3} 最近 {when}"
        )
    if s["never_used"]:
        lines += ["", f"  零触达（清理候选）: {len(s['never_used'])} 个"]
        preview = s["never_used"][:20]
        lines.append("    " + "、".join(preview)
                     + ("…" if len(s["never_used"]) > len(preview) else ""))
    return "\n".join(lines)
