"""技能整理建议（FEAT-11）：只读判据，产出「可执行合并 / 上游标注 / 已否决」三类清单。

判据定义见 `docs/superpowers/specs/2026-09-23-skill-merge-advice-design.md`。
本模块**全程只读**：不写盘、不移动、不删除任何技能目录。执行能力属 FEAT-12。

为什么不能只看文本相似度（真实数据给的教训）：
`sensteed-java17-standard` × `sensteed-java8-standard` 的描述 token Jaccard = 1.00，
但它是按 Java 版本分工的平行规范分册，合并会毁掉版本路由；`sensteed-*-review` 8 个
两两 0.80~0.90，它们是 `sensteed-review-hub` 的路由目标。真重复与有意变体的区别
不在"像不像"，而在名称差异部分是噪声后缀还是实质限定词。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 统一库是唯一实体，~/.agents|.codex|.dsh|.hermes|.cc-switch/skills 全是它的符号链接。
_SKILLS_DIR = Path.home() / ".skills-manager" / "skills"

_T1_MIN_LEN = 40          # 归一后短于此的描述不足以支撑"逐字相同即同一份"的判断
_JACCARD_MIN = 0.6        # T4 相似度门槛（低于此值本就进不了候选）

# 噪声后缀：名称只差这些词时，视为同一目标的双重存在。
_NOISE_SUFFIXES = frozenset({
    "skill", "skills", "unified", "unifier", "manager", "pro", "max",
    "tools", "core", "suite", "helper", "common",
})

# 实质限定词：命中任一即否决合并。**优先级高于噪声集，顺序不可颠倒** ——
# sensteed-java8 × java17 的名称里不含任何噪声词，只有靠这张表才拦得住。
_SUBSTANTIVE = frozenset({
    # 语言/平台分册：同一套规范按语言路由，合并等于毁掉路由目标
    "android", "ios", "vue", "react", "nodejs", "python", "frontend",
    "java", "kotlin", "swift", "web",
    # 动作类型：*-review 由 sensteed-review-hub 分发
    "review",
    # 同一产品的不同实现面（oss / openapi 等是"另一套接口"，不是重名）
    "oss", "openapi", "alerting", "promql", "opentelemetry", "bridge", "cli",
    "v1", "v2", "v3",
})
_HAS_DIGIT = re.compile(r"\d")                # 版本号：java8 / java17 / 任何含数字段

# T2 自述转发壳：必须同时出现「仅当」与「统一交由 X 处理」，
# 否则只是正常描述里的巧合用词（例如 lark-sheets 的"请改用 lark-drive 搜索"）。
_ALIAS_EXPLICIT_RE = re.compile(r"仅当")
_ALIAS_TARGET_RE = re.compile(r"统一交由\s*([a-z][a-z0-9-]+)")


# ---------------------------------------------------------------- 文本归一


def _norm_desc(text: str) -> str:
    """描述归一：去掉所有非字母数字并转小写。

    中英文都退化为字符序列，足以判定"同一份描述挂了两个名字"，
    且不受标点、空格、换行、全半角差异影响。
    """
    return re.sub(r"\W+", "", (text or "").lower())


_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def _desc_tokens(text: str) -> set:
    """描述分词：拉丁词（>=3 字母）+ **中文按字符二元组（bigram）切**。

    不能把整段中文当一个 token：`re.findall(r"[\u4e00-\u9fff]{2,}")` 会把
    "创建和操作电子表格" 整串收成一个词，两段措辞略有出入的中文描述 Jaccard 实测只有
    **0.2**（真实相似度约 0.8），T4 对所有中文技能直接失效。本库 202 个技能里
    中文描述占多数，这个缺陷会让整个 T4 变成摆设。bigram 是无分词器时的标准做法。

    用集合而非序列，避免"同一内容换个说法顺序"造成的假不相似。
    """
    low = (text or "").lower()
    tokens = set(re.findall(r"[a-z]{3,}", low))
    for run in _CJK_RUN_RE.findall(low):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _name_tokens(name: str) -> set:
    """技能名成分：连字符切分，丢掉单字母碎片（如 `a-b-test` 里的 a/b）。"""
    return {t for t in name.split("-") if len(t) > 1}


def _stem_name(name: str) -> str:
    """按段做词干归一：**只有长度 > 4 的段**才剥 `ing`/`ed`/`s` 尾。

    长度下限是必需的：`oss` 剥 s 会变成 `os`、`doc` 剥 s 会变成 `do`，
    造成不同技能被误归一。归一后 `grafana-dashboard` / `-dashboards` /
    `-dashboarding` 三者同名，即 T3 的判据。
    """
    out = []
    for part in name.split("-"):
        out.append(re.sub(r"(ing|ed|s)$", "", part) if len(part) > 4 else part)
    return "-".join(out)


def _substantive_tokens(name: str) -> set:
    """名称中命中的实质限定词（含任何带数字的段，即版本号）。"""
    return {t for t in _name_tokens(name)
            if t in _SUBSTANTIVE or _HAS_DIGIT.search(t)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _alias_target(description: str) -> Optional[str]:
    """T2：从「仅当…显式指定…统一交由 X 技能处理」中取出目标 X。"""
    text = description or ""
    if not _ALIAS_EXPLICIT_RE.search(text):
        return None
    m = _ALIAS_TARGET_RE.search(text)
    return m.group(1) if m else None


def _family(name: str) -> str:
    """前缀族：第一个连字符之前的段；无连字符的技能自成一族。"""
    return name.split("-")[0] if "-" in name else name


# ---------------------------------------------------------------- 规则收集


def _collect_pairs(metas: Sequence[Dict[str, Any]]
                   ) -> Tuple[List[Tuple[int, str, str, str, str]], List[dict]]:
    """产出 (命中对, 被否决对)。

    命中对元素为 `(rank, rule, a, b, evidence)`，rank 越小规则越强：
    T1=1（描述逐字相同）、T2=2（自述转发壳）、T3=3（名称词干相同）、T4=4（弱相似）。
    """
    by = {m["name"]: m for m in metas}
    names = sorted(by)
    hits: List[Tuple[int, str, str, str, str]] = []
    rejected: List[dict] = []

    # T2：壳技能 → 它指定的目标。目标不存在时不是合并机会，而是悬空转发缺陷。
    for n in names:
        tgt = _alias_target(by[n].get("description") or "")
        if not tgt:
            continue
        if tgt not in by:
            rejected.append({
                "kind": "dangling_alias", "members": [n, tgt], "rule": "T2",
                "fold_into": tgt, "fold_into_exists": False, "jaccard": None,
                "blocked_by": ["转发目标不存在"],
                "verdict": f"{n} 自称交由 {tgt} 处理，但 {tgt} 不在技能库中（悬空引用），"
                           f"不构成合并建议",
            })
        else:
            hits.append((2, "T2", n, tgt, f"自述转发壳：统一交由 {tgt} 处理"))

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            A, B = by[a], by[b]
            na = _norm_desc(A.get("description") or "")
            nb = _norm_desc(B.get("description") or "")
            if len(na) > _T1_MIN_LEN and na == nb:
                # T1 不设实质限定词关卡：描述逐字相同而名称含版本号，本身就是
                # "同一份内容挂两个版本名"的缺陷，归并正是解法。
                hits.append((1, "T1", a, b, f"描述归一后逐字相同（{len(na)} 字）"))
                continue

            j = _jaccard(_desc_tokens(A.get("description") or ""),
                         _desc_tokens(B.get("description") or ""))
            if j >= _JACCARD_MIN:
                tokens = _name_tokens(a) | _name_tokens(b)
                blocked = sorted((_substantive_tokens(a) | _substantive_tokens(b)) & tokens)
                diff = _name_tokens(a) ^ _name_tokens(b)
                if blocked:
                    # 实质限定词优先：即便差异里也有噪声后缀，也不建议合并。
                    rejected.append({
                        "kind": "variant", "members": [a, b], "rule": None,
                        "fold_into": None, "fold_into_exists": None,
                        "jaccard": round(j, 3), "blocked_by": blocked,
                        "verdict": "有意变体（版本/语言/实现面分册），不合并",
                    })
                elif diff and diff <= _NOISE_SUFFIXES:
                    hits.append((4, "T4", a, b,
                                 f"描述高度相似（Jaccard={j:.2f}）且名称差异仅为噪声后缀 "
                                 f"{sorted(diff)}"))

    # T3：词干归一后同名。同样过一遍实质限定词关卡（保守优先）。
    stems: Dict[str, List[str]] = {}
    for n in names:
        stems.setdefault(_stem_name(n), []).append(n)
    for stem, group in stems.items():
        if len(group) < 2:
            continue
        for i, a in enumerate(sorted(group)):
            for b in sorted(group)[i + 1:]:
                blocked = sorted((_substantive_tokens(a) | _substantive_tokens(b))
                                 & (_name_tokens(a) | _name_tokens(b)))
                if blocked:
                    rejected.append({
                        "kind": "variant", "members": [a, b], "rule": "T3",
                        "fold_into": None, "fold_into_exists": None,
                        "jaccard": None, "blocked_by": blocked,
                        "verdict": "名称词干相同但含实质限定词，按变体保留",
                    })
                else:
                    hits.append((3, "T3", a, b, f"名称词干归一相同 → {stem}"))

    return hits, rejected


def _groups(names: Sequence[str],
            hits: Sequence[Tuple[int, str, str, str, str]]
            ) -> Dict[str, Tuple[List[str], List[Tuple[int, str, str, str, str]]]]:
    """并查集把成对关系合成组。

    必须先合成组再判断，否则 `grafana-dashboard`/`-dashboards`/`-dashboarding`
    会被列成三对重复项；而 `ima`×`ima-skill` 同时被 T1 与 T4 命中，
    不去重就会出现两个含同一技能的组。
    """
    parent = {n: n for n in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]      # 路径减半
            x = parent[x]
        return x

    for rank, rule, a, b, ev in sorted(hits):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    members: Dict[str, List[str]] = {}
    for n in sorted(names):
        members.setdefault(find(n), []).append(n)
    bucket: Dict[str, List[Tuple[int, str, str, str, str]]] = {}
    for hit in hits:
        bucket.setdefault(find(hit[2]), []).append(hit)
    return {root: (mem, sorted(bucket.get(root, [])))
            for root, mem in members.items() if len(mem) >= 2}


def _pick_keep(mem: Sequence[str], by: Dict[str, Any]) -> str:
    """组内保留者。逐项 tiebreak，首个分出高下即定：

    load 更高 → 描述更长 → 带 scripts/references → 名称字典序。
    「无上游」**不在**此列：能进 actionable 的组按定义全是自持技能，
    组内该常量恒等、不具区分力（它是 §3.3 的组级准入门槛）。
    """
    def key(n: str):
        m = by[n]
        return (-int(m.get("load") or 0),
                -len(m.get("description") or ""),
                not m.get("has_scripts"),
                n)
    return sorted(mem, key=key)[0]


def _member_view(m: Dict[str, Any]) -> Dict[str, Any]:
    """成员对外字段。缺项会直接剥夺人工复核能力，故显式给默认值。"""
    return {
        "name": m["name"],
        "upstream": bool(m.get("upstream")),
        "load": int(m.get("load") or 0),
        "sessions": int(m.get("sessions") or 0),
        "last_used": m.get("last_used"),
        "has_scripts": bool(m.get("has_scripts")),
        "has_license": bool(m.get("has_license")),
        "lock_coverage": float(m.get("lock_coverage") or 0.0),
        "source": m.get("source"),
    }


# ---------------------------------------------------------------- 公开判据


def _pairs_by_rules(metas: Sequence[Dict[str, Any]]
                    ) -> Tuple[List[dict], List[dict], List[dict]]:
    """判据总入口（**纯函数，不碰磁盘**）。

    入参每项至少含 `name` / `description` / `upstream`，可选 `load`、
    `sessions`、`last_used`、`has_scripts`、`has_license`、`lock_coverage`、`source`。
    返回 `(actionable, upstream_only, rejected)`：
      - actionable：全组自持，可交给未来执行层
      - upstream_only：全组有上游登记，只标注 `source`
      - rejected：被实质限定词否决的变体对 + 跨来源并存组 + 悬空转发
    """
    by = {m["name"]: m for m in metas}
    hits, rejected = _collect_pairs(metas)
    actionable: List[dict] = []
    upstream_only: List[dict] = []
    rows: List[dict] = []

    for root, (mem, group_hits) in _groups(list(by), hits).items():
        mem = sorted(mem)
        best = min(group_hits)                 # rank 最小 = 最强规则
        # 命中元组是 (rank, rule, a, b, evidence)：b 在索引 3、evidence 在索引 4。
        # 把 evidence 取成 best[3] 会静默拿到另一个技能名（预演时真实踩过）。
        rule, other, evidence = best[1], best[3], best[4]
        ups = [n for n in mem if by[n].get("upstream")]
        # 悬空优先：T2 目标不存在的壳已在 rejected 里，不得再因"全组有上游"
        # 被判进 upstream_only（它首先是缺陷，不是归属问题）。
        dangling = [r for r in rejected if r["kind"] == "dangling_alias"
                    and r["members"][0] in mem]
        if dangling:
            continue
        # T2 的目标就是配对里的另一方（收集时按 (壳, 目标) 顺序入队），
        # 且**由壳自己指定**，不参与 keep 打分 —— 否则可能反过来把壳判成保留者。
        fold_into = other if rule == "T2" and other in mem else None
        if ups and len(ups) == len(mem):
            upstream_only.append({
                "rule": rule, "members": mem, "evidence": evidence,
                "sources": {n: by[n].get("source") for n in mem},
                "note": "同属上游仓库登记项，升级会覆盖本地改动，合并交由上游处理",
            })
            continue
        if ups:
            rejected.append({
                "kind": "mixed_source", "members": mem, "rule": rule,
                "fold_into": None, "fold_into_exists": None, "jaccard": None,
                "blocked_by": ["上游与自持并存"],
                "verdict": f"跨来源并存（{', '.join(ups)} 有上游登记），"
                           f"需选边：改用上游版或自持一份，不归并",
            })
            continue
        keep = fold_into or _pick_keep(mem, by)
        rows.append({
            "rule": rule, "members": mem, "keep": keep,
            "fold": [n for n in mem if n != keep],
            "fold_into": fold_into,
            "evidence": evidence,
            "rules_hit": sorted({h[1] for h in group_hits}),
            "detail": [_member_view(by[n]) for n in mem],
        })

    # 组 id 由排序后的首成员生成，保证同输入两次调用逐字节一致。
    rows.sort(key=lambda r: (r["members"][0], r["members"]))
    for idx, row in enumerate(rows, start=1):
        row["id"] = f"grp-{idx:02d}"
    actionable = [{k: rows[i][k] for k in
                   ("id", "rule", "members", "keep", "fold", "fold_into",
                    "evidence", "rules_hit", "detail")}
                  for i in range(len(rows))]
    actionable.sort(key=lambda r: r["id"])
    upstream_only.sort(key=lambda r: r["members"][0])
    rejected.sort(key=lambda r: (r["members"][0], r["members"][-1], r["kind"]))
    return actionable, upstream_only, rejected


# ---------------------------------------------------------------- 读盘装配


def _frontmatter_description(path: Path) -> str:
    """从 SKILL.md 顶部 YAML 块取 description，压平空白。

    不引第三方 YAML 解析器：这里只需要一个键，且描述里常含冒号与换行，
    逐行 `key:` 匹配比通用解析更稳。取不到时返回空串（该技能会落不进任何规则）。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return ""
    mm = re.search(r"^description:\s*(.+?)(?=\n[a-zA-Z_]+:|\Z)",
                   m.group(1), re.S | re.M)
    return " ".join(mm.group(1).split()) if mm else ""


def load_metas(skills_dir: Optional[Path] = None,
               usage: Optional[Dict[str, Any]] = None,
               installed: Optional[Sequence[Dict[str, Any]]] = None
               ) -> List[Dict[str, Any]]:
    """把磁盘事实拼成判据入参。

    `usage` 来自 `skill_usage.scan_usage()`，其 `skills` 字典**只含有触达记录的技能**，
    零触达技能取默认值 0 而不是缺席 —— 它们正是最需要被建议合并的那批。
    `installed` 来自 `skill_market.list_installed()`，其 `registered` 字段
    （在 `.skill-lock.json` 有登记）就是"有上游"的唯一依据。
    """
    skills_dir = Path(skills_dir) if skills_dir else _SKILLS_DIR
    if not skills_dir.is_dir():
        return []
    names = sorted(d.name for d in skills_dir.iterdir()
                   if d.is_dir() and not d.name.startswith(".")
                   and (d / "SKILL.md").is_file())
    reg: Dict[str, dict] = {i["name"]: i for i in (installed or [])
                            if i.get("registered")}
    usage_skills = (usage or {}).get("skills") or {}

    cover: Dict[str, float] = {}
    fams: Dict[str, List[str]] = {}
    for n in names:
        fams.setdefault(_family(n), []).append(n)
    for fam, mem in fams.items():
        ratio = sum(1 for m in mem if m in reg) / len(mem)
        for m in mem:
            cover[m] = round(ratio, 3)

    metas: List[Dict[str, Any]] = []
    for n in names:
        d = skills_dir / n
        try:
            entries = set(os.listdir(d))
        except OSError:
            entries = set()
        u = usage_skills.get(n) or {}
        metas.append({
            "name": n,
            "description": _frontmatter_description(d / "SKILL.md"),
            "upstream": n in reg,
            "source": (reg.get(n) or {}).get("source"),
            "load": int(u.get("load") or 0),
            "sessions": int(u.get("sessions") or 0),
            "last_used": u.get("last_used"),
            "has_scripts": bool({"scripts", "references"} & entries),
            "has_license": any(e.upper().startswith(("LICENSE", "COPYING"))
                               for e in entries),
            "lock_coverage": cover.get(n, 0.0),
        })
    return metas


def scan_advice(skills_dir: Optional[Path] = None,
                session_dirs: Optional[Sequence[Path]] = None,
                since: Optional[str] = None,
                usage: Optional[Dict[str, Any]] = None,
                installed: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """唯一公开出口。只读：不写盘、不移动、不删除。

    `usage` / `installed` 可注入以便测试与复用（两者都是只读扫描，
    GUI 一次点击里若已跑过统计就直接传进来，避免重扫 30 秒会话日志）。
    """
    if usage is None:
        from skill_usage import scan_usage      # 延迟导入：避免无谓的会话扫描
        usage = scan_usage(session_dirs=session_dirs, since=since)
    if installed is None:
        from skill_market import list_installed
        installed = list_installed().get("installed") or []

    metas = load_metas(skills_dir=skills_dir, usage=usage, installed=installed)
    actionable, upstream_only, rejected = _pairs_by_rules(metas)
    return {
        "source": "codex-sessions+skill-lock",
        "since": since,
        "scanned_skills": len(metas),
        "usage_scanned_files": (usage or {}).get("scanned_files"),
        "actionable": actionable,
        "upstream_only": upstream_only,
        "rejected": rejected,
        "summary": {
            "scanned": len(metas),
            "actionable_groups": len(actionable),
            "actionable_skills": sum(len(a["members"]) for a in actionable),
            "upstream_only_groups": len(upstream_only),
            "rejected_entries": len(rejected),
            "zero_touch_in_actionable": sorted(
                d["name"] for a in actionable for d in a["detail"] if not d["load"]),
        },
    }


def summarize_text(payload: Dict[str, Any]) -> str:
    """人读渲染。三段顺序固定：先看能动手的，再看只能标注的，最后看被否决的。"""
    s = payload.get("summary") or {}
    lines = [
        f"扫描 {s.get('scanned', 0)} 个技能"
        f"｜可执行合并 {s.get('actionable_groups', 0)} 组"
        f"｜上游仅标注 {s.get('upstream_only_groups', 0)} 组"
        f"｜已否决 {s.get('rejected_entries', 0)} 条",
    ]
    act = payload.get("actionable") or []
    if act:
        lines += ["", "可执行合并组："]
        for g in act:
            lines.append(f"  [{g['rule']}] {g['keep']}  ←  " + "、".join(g["fold"]))
            lines.append(f"      依据：{g['evidence']}")
            for d in g["detail"]:
                marks = []
                if d["has_scripts"]:
                    marks.append("含脚本")
                if d["has_license"]:
                    marks.append("含 LICENSE")
                if not d["load"]:
                    marks.append("零触达")
                tag = f"（{'、'.join(marks)}）" if marks else ""
                lines.append(f"      · {d['name']:<32} load={d['load']:<4}"
                             f" 会话={d['sessions']:<3}{tag}")
    else:
        lines += ["", "可执行合并组：无"]
    ups = payload.get("upstream_only") or []
    if ups:
        lines += ["", "上游技能（仅标注，合并交由上游仓库处理）："]
        for g in ups:
            src = "、".join(sorted({v for v in g["sources"].values() if v})) or "未知来源"
            lines.append(f"  [{g['rule']}] {'、'.join(g['members'])}  来源：{src}")
    rej = payload.get("rejected") or []
    if rej:
        lines += ["", "已被判据否决（留痕，避免后来者重踩）："]
        for r in rej[:20]:
            lines.append(f"  · {' × '.join(r['members'])}  {r['verdict']}"
                         + (f"（{', '.join(r['blocked_by'])}）" if r["blocked_by"] else ""))
        if len(rej) > 20:
            lines.append(f"  …另有 {len(rej) - 20} 条，用 --format json 查看全部")
    lines += ["", "本功能全程只读，不删除、不移动任何技能目录。"]
    return "\n".join(lines)
