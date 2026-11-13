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
import re
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
    """单个约束路径的状态：missing / dir / current / covered / stale。

    ``covered``（v0.43.0）：文件里**没有共享块**，但每条约束都已以别的措辞存在。
    用户要求「这里的检查不是说内容必须一模一样，而是表达的意思一样即可」——
    所以「语义已覆盖」算达标，只是还没被收进标记块。
    """
    p = Path(os.path.expanduser(raw))
    base = {"path": raw, "resolved": str(p)}
    if p.is_dir():
        return dict(base, state="dir", reason="规则目录，不参与共享块同步")
    text = _read_text(p) if p.is_file() else None
    if text is None:
        # v0.46.7：缺文件**不是**「无可写入」。write_rules 本来就会新建文件与父目录，
        # 所以这是一个**可修复**状态，界面必须给出「新建并写入」的入口。
        # 此前菜单按 `paths.some(exists)` 判定，缺文件时直接不生成修复项 ——
        # 用户反馈「DeepSeek Harness 没有写入约束的功能」即由此而来。
        return dict(base, state="missing",
                    reason="约束文件还不存在；修复时会新建并写入共享块",
                    creatable=True)
    current = extract(text)
    if current is not None and current == (content or "").rstrip("\n"):
        return dict(base, state="current", reason="已是最新")
    # 「语义已覆盖」只在**没有（或只覆盖了一部分）标记块**时兜底判定。
    # 块存在且内容不同，说明用户改过共享内容：此时必须报 stale，
    # 否则改内容后界面会一直显示「已含」，用户不知道该同步（实测踩到：
    # 「完全无关」与「完全不相干」相似度 0.67 而被判成已覆盖）。
    if current is None and _covered(text.splitlines(), content):
        return dict(base, state="covered", reason="内容已以其他措辞存在（语义一致）")
    if current is None:
        return dict(base, state="absent", reason="文件里没有共享块，且缺少部分约束")
    return dict(base, state="stale", reason="共享块内容与当前配置不一致")


def audit(content: Optional[str] = None,
          registry: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """只读检查：每个声明了约束文件的客户端，其各路径与共享块的差异。"""
    body = read_content() if content is None else content
    flags = load_settings()
    rows: List[Dict[str, Any]] = []
    counts = {"current": 0, "covered": 0, "stale": 0, "absent": 0, "missing": 0, "dir": 0, "clients": 0}
    for tool in (registry or MAINSTREAM_TOOLS):
        paths = tool.get("rules_paths") or []
        if not paths:
            continue
        states = [_path_state(raw, body) for raw in paths]
        # 一个客户端的整体状态取「最需要处理」的那个：
        # missing > absent > stale > dir > current
        order = ["missing", "absent", "stale", "dir", "covered", "current"]
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


# ---------------- 语义等价与近似条目替换（v0.43.0） ----------------

#: 判定「意思一样」时忽略的标点与格式符号。
_NOISE = " \t\u3000，。、；：！？,.;:!?（）()【】[]「」“”\"'`#*-—_·\n\r"


def _norm(text: str) -> str:
    """把一行压成可比较的骨架：去标点、去空白、小写。"""
    return "".join(ch.lower() for ch in (text or "") if ch not in _NOISE)


def _tokens(text: str) -> List[str]:
    """中文按 2-gram、英文按词切分，用于估算相似度。"""
    norm = "".join(ch for ch in (text or "") if ch not in _NOISE)
    out: List[str] = []
    cjk = [ch for ch in norm if "\u4e00" <= ch <= "\u9fff"]
    out.extend("".join(cjk[i:i + 2]) for i in range(max(0, len(cjk) - 1)))
    import re as _re
    out.extend(w.lower() for w in _re.findall(r"[A-Za-z0-9_\-]{2,}", norm))
    return out


def _lcs(a: str, b: str) -> int:
    """最长公共子序列长度（字符级）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if ca == cb else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def _similar(a: str, b: str) -> float:
    """行级相似度 0..1：字符级 Dice 系数。

    不用 Jaccard-on-token：中文里「必须用中文回答」与「所有回答都必须使用中文」的
    2-gram 交集很少（Jaccard 仅 0.33），但字符级重叠过半 —— 后者才符合「意思一样」
    的直觉。实测标定：同义改写 0.53~0.75，不同主题 < 0.25。
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return 2.0 * _lcs(na, nb) / (len(na) + len(nb))


#: 判定「同一层意思」的相似度阈值。
#: 0.45 覆盖同义改写（「必须用中文回答」vs「所有回答都必须使用中文」= 0.53），
#: 又不会把不同主题（0.06~0.25）误判成重复。
SIMILARITY_THRESHOLD = 0.45


def content_lines(content: str) -> List[str]:
    """共享内容的「条目」：去空行、去纯标点行、去 Markdown 列表前缀。"""
    out: List[str] = []
    for raw in (content or "").splitlines():
        line = raw.strip().lstrip("-*+ ").strip()
        if _norm(line):
            out.append(line)
    return out


def _covered(lines: List[str], content: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """文件里的行是否已覆盖共享内容的每一条（允许措辞不同、顺序不同）。"""
    wanted = content_lines(content)
    if not wanted:
        return True
    have = [_norm(ln) for ln in lines]
    for w in wanted:
        if not any(_similar(w, h) >= threshold for h in have):
            return False
    return True


def _strip_similar(lines: List[str], content: str,
                   threshold: float = SIMILARITY_THRESHOLD) -> List[str]:
    """删掉文件里与共享内容「意思相同」的旧条目，避免同一句出现两遍。

    只处理**单行条目**：多行段落里的某一行被删会破坏结构，宁可留着。
    """
    wanted = content_lines(content)
    kept: List[str] = []
    for ln in lines:
        bare = ln.strip().lstrip("-*+ ").strip()
        if bare and any(_similar(bare, w) >= threshold for w in wanted):
            continue
        kept.append(ln)
    return kept


def apply(text: str, block: str, content: str = "") -> str:
    """把共享块替换 / 插入到 ``text`` 里（纯函数，便于单测）。

    ``content`` 给定时，先删掉文件里与它**意思相同**的独立条目（用户要求
    「把原来文件中类似的内容给替换掉」），再插入/替换标记块——否则同一句会在
    文件里出现两遍：一遍在块里、一遍在块外。
    """
    if content:
        lines = text.splitlines()
        kept = _strip_similar(lines, content)
        if len(kept) != len(lines):
            text = "\n".join(kept).rstrip("\n") + "\n"
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

    routed = any(roles_for(tool, i) for i in range(len(paths)))
    results: List[Dict[str, Any]] = []
    for idx, raw in enumerate(paths):
        # 按文件职责筛选内容（v0.46.0）：没声明角色就沿用旧行为（全部写入）。
        roles_here = roles_for(tool, idx) if routed else None
        body_for_path = lines_for_roles(body, roles_here or []) if routed else body
        block = block_for(body_for_path) if (body_for_path or "").strip() else ""
        # **先判「这个文件不接收」，再算状态**（v0.46.1）。
        # 顺序反了会踩坑：body 为空时 _covered([], "") 恒为 True，状态被判成
        # covered（「已经写好了」），于是既不清旧块、也不报 skip —— 用户 dry-run 里
        # 看到的是 "covered" 而不是 "skip"，完全误导。
        if routed and not roles_here:
            p_skip = Path(os.path.expanduser(raw))
            existing_skip = _read_text(p_skip) if p_skip.is_file() else None
            if existing_skip and extract(existing_skip) is not None:
                cleared = re.sub(re.escape(BEGIN) + r"[\s\S]*?" + re.escape(END) + r"\n?",
                                 "", existing_skip).rstrip("\n") + "\n"
                if dry_run:
                    results.append({"path": raw, "state": "cleared", "ok": True, "changed": True,
                                    "reason": "该文件职责不接收共享约束，将移除旧块", "dry_run": True})
                else:
                    res = write_rules(tool.get("name"), cleared, index=idx, registry=registry)
                    results.append({"path": raw, "state": "cleared", "reason": "该文件职责不接收共享约束，已移除旧块",
                                    "ok": bool(res.get("ok")), "changed": bool(res.get("ok"))})
            else:
                results.append({"path": raw, "state": "skip", "reason": "该文件职责不接收共享约束",
                                "ok": True, "changed": False})
            continue
        state = _path_state(raw, body_for_path)
        if state["state"] in ("dir",):
            results.append(dict(state, ok=False, skipped=True))
            continue
        if routed and roles_here and not block:
            # 这个文件不接收任何内容 → 若它里面有旧块，清掉，避免残留过期规则。
            p_clear = Path(os.path.expanduser(raw))
            existing_clear = _read_text(p_clear) if p_clear.is_file() else None
            if existing_clear and extract(existing_clear) is not None:
                cleared = re.sub(re.escape(BEGIN) + r"[\s\S]*?" + re.escape(END) + r"\n?",
                                 "", existing_clear).rstrip("\n") + "\n"
                res = write_rules(tool.get("name"), cleared, index=idx, registry=registry)
                results.append({"path": raw, "state": "cleared", "reason": "该文件职责不接收共享约束，已移除旧块",
                                "ok": bool(res.get("ok")), "changed": bool(res.get("ok"))})
            else:
                results.append({"path": raw, "state": "skip", "reason": "该文件职责不接收共享约束",
                                "ok": True, "changed": False})
            continue
        if state["state"] == "current":
            results.append(dict(state, ok=True, changed=False))
            continue
        if dry_run:
            results.append(dict(state, ok=True, changed=True, dry_run=True,
                                reason=("将新建该文件并写入共享块" if state["state"] == "missing"
                                        else state.get("reason", ""))))
            continue
        p = Path(os.path.expanduser(raw))
        existing = _read_text(p) or ""
        merged = apply(existing, block, body_for_path)
        res = write_rules(tool.get("name"), merged, index=idx, registry=registry)
        results.append(dict(state, ok=bool(res.get("ok")), changed=bool(res.get("ok")),
                            created=state["state"] == "missing",
                            backup=res.get("backup", ""),
                            reason=res.get("reason", "") or (
                                "已新建文件并写入共享块" if state["state"] == "missing" else "")))

    changed = sum(1 for r in results if r.get("changed"))
    failed = [r for r in results if not r.get("ok")]
    return {
        "ok": not failed,
        "client": tool.get("name"),
        "changed": changed,
        "results": results,
        "reason": "" if not failed else f"{len(failed)} 个路径未完成",
    }

# ---------------- 多约束文件：按职责分流（v0.46.0） ----------------
#
# 用户：「对于这种有多个约束文件的，是否真的需要多个，还是只需要改一个就可以了？
#       修改的方案是什么？优先写到哪个里面？」
#
# 现实：WorkBuddy 有两个文件，职责完全不同 ——
#   SOUL.md  人格 / 行为准则（怎么做事）
#   USER.md  用户档案（我是谁：姓名、角色、技术栈、沟通偏好）
#
# 此前把所有内容同时写进两个文件，等于把「怎么做事」塞进「我是谁」里，同一个块
# 出现两遍，两边各自维护。现在按**内容分类**选文件：
#
#   每条共享内容先分类 → 只有包含任一类别的文件才写 → 每类只写进最合适的那一个。
#
# 没有声明 `rules_roles` 的客户端保持旧行为（全部路径都写）——不为一个特例改变
# 所有客户端的语义。角色表放在注册表里，用户可以按需扩充。

#: 内容分类的关键词。命中即归入该类；一条内容可以属于多类，但**只会写进一个文件**。
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    # 用户档案：我是谁
    "profile": ["我的名字", "我叫", "my name", "调用我", "称呼我", "我是系统架构",
                "用户偏好", "我的技术栈", "user-profile", "user profile"],
    # 工作偏好 / 协作方式
    "preference": ["偏好", "prefer", "习惯", "沟通方式", "communication style"],
    # 通用行为准则（怎么做事）
    "behavior": ["必须使用中文", "包括思考过程", "回答", "不要", "禁止", "应该",
                 "生成", "响应", "语言", "语气", "tone", "style"],
}
#: 匹配时的大小写折叠（中文无影响，英文关键词用小写比较）。
_PROFILE_KEYS = ["profile", "preference", "behavior"]


def category_of(line: str) -> Optional[str]:
    """把一条共享内容归到一个类别。

    优先级：profile > preference > behavior > None。
    「必须先说我是谁」排在前面，是因为用户档案类内容最容易误归进「行为准则」。
    """
    low = (line or "").lower()
    for cat in ("profile", "preference", "behavior"):
        for kw in CATEGORY_KEYWORDS[cat]:
            if kw.lower() in low:
                return cat
    return None


def lines_for_roles(content: str, roles: List[str]) -> str:
    """按文件角色筛选共享内容：只保留属于这些角色的条目。"""
    if not roles:
        return ""
    kept = [ln for ln in content_lines(content) if category_of(ln) in roles]
    return "\n".join(kept) + ("\n" if kept else "")


def roles_for(tool: Dict[str, Any], index: int) -> List[str]:
    """取第 index 个约束路径的角色；没有声明就返回空（= 旧行为，全部写）。"""
    roles = tool.get("rules_roles") or []
    if index < len(roles):
        return list(roles[index] or [])
    return []


def allocation(tool: Dict[str, Any], content: str) -> List[Dict[str, Any]]:
    """计算「每条内容写进哪个文件」，供界面展示（纯函数，便于单测）。

    返回 [{path, roles, lines, why}]；没有角色声明时 roles 为空、lines 为全部内容。
    """
    paths = tool.get("rules_paths") or []
    out: List[Dict[str, Any]] = []
    body = content or ""
    routed = any(roles_for(tool, i) for i in range(len(paths)))
    for i, raw in enumerate(paths):
        roles = roles_for(tool, i)
        if routed:
            lines = [ln for ln in content_lines(body) if category_of(ln) in roles]
            why = "按职责分流：" + "、".join(roles) if roles else "该文件不接收共享约束"
        else:
            lines = content_lines(body)
            why = "未声明文件职责，全部写入"
        out.append({"path": raw, "roles": roles, "lines": lines, "why": why})
    return out
