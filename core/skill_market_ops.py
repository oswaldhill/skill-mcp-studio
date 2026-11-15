"""FEAT-9 技能市场写操作（安装 / 升级）。

与只读层 `skill_market` 分文件，是为了让「会写盘」这件事在代码审查上可见：
只读的检测逻辑绝不该出现在同一文件里，否则一次误改就可能让「检查更新」
变成写操作（`npx skills check` 正是这样的陷阱）。

安全形状：先生成 plan（可展示、可供用户确认）→ 再 execute。执行器接受
注入的 runner，测试期永不真调 npx。

**不使用 `npx skills check`**：该命令名为检查、实为升级，且不受技能选择控制。

安装目标：`npx skills add ... -g` 落到 `~/.agents/skills`，而它是
`~/.skills-manager/skills` 的符号链接 ⇒ 已直接落在统一库，无需额外归一机制；
但仍要装后校验，避免「命令成功却没装上」。

设计依据：docs/superpowers/specs/2026-09-23-skill-market-integration-design.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from skill_market import _run_npx

import paths


def _skills_dir() -> Path:
    """独立成函数，便于测试替换。

    真实解析交给 ``paths``：此前是模块级 ``Path.home()`` 常量，import 时定死、
    运行期改不动（评审 P0-4）。
    """
    return paths.skills_dir()


def plan_install(package: str) -> Dict[str, Any]:
    """生成安装计划，不执行。

    `-g` 是必须的：只有全局安装才落到统一库。
    """
    pkg = (package or "").strip()
    if not pkg:
        return {"ok": False, "action": "install", "package": "", "argv": [],
                "reason": "包名为空"}
    return {
        "ok": True,
        "action": "install",
        "package": pkg,
        "argv": ["add", pkg, "-g", "-y"],
        "reason": "",
    }


# ---------------------------------------------------------------------------
# 安装源识别（2026-11-14 新增）
#
# 需求：Skill 页要支持「输入/搜索包名」与「贴 GitHub 地址」两种安装入口。
#
# 为什么源识别要单独成函数、而不是把输入直接塞进 plan_install：
#   `npx skills add` 对包名和 URL 的解析规则不同，且**只认 GitHub**。若把用户
#   粘贴的任意 URL 原样传给 npx，等于让一个外部地址决定装什么进统一库——这是
#   供应链入口，必须先在前置环节把形状限定死，不能指望下游命令替我们校验。
# ---------------------------------------------------------------------------

#: 允许的来源主机。只放行 GitHub 本身，不接受任意 URL。
_ALLOWED_HOSTS = frozenset({
    "github.com",
    "www.github.com",
    "raw.githubusercontent.com",
})

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://|git\+https?://|ssh://git@|git@)"
    r"(?P<host>[^/:]+)"
    r"[:/]"
    r"(?P<owner>[A-Za-z0-9._-]+)/"
    r"(?P<repo>[A-Za-z0-9._-]+?)"
    r"(?:\.git)?"
    r"(?:/tree/[^/]+/(?P<subpath>.+?))?"
    r"/?$",
    re.IGNORECASE,
)

#: 包名形状：`owner/repo` 或 `owner/repo@skill`。
_PACKAGE_RE = re.compile(
    r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:@[A-Za-z0-9._-]+)?$")



#: ANSI / OSC 转义序列。`npx skills` 走 clack 渲染，stdout 里混着颜色与光标控制。
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")

#: `◇  Found 9 skills`
_FOUND_RE = re.compile(r"Found\s+(\d+)\s+skills?", re.IGNORECASE)

#: 技能名行：`│    vercel-composition-patterns`（`│` 后恰好 4 空格，单 token）
_SKILL_NAME_RE = re.compile(r"^\s*\u2502 {4}([A-Za-z0-9][A-Za-z0-9._-]*)\s*$")

#: 描述行：`│      React composition patterns...`（`│` 后 6 个以上空格）
_SKILL_DESC_RE = re.compile(r"^\s*\u2502 {6,}(\S.*?)\s*$")


def classify_install_source(raw: Optional[str]) -> Dict[str, Any]:
    """把用户输入分派成 ``github`` / ``package`` / ``rejected``。

    返回 ``kind`` 而非布尔值，是为了让调用方能据类型走不同 UI：
    GitHub URL 要先 `--list` 预览仓库里有哪些技能，包名可以直接装。
    """
    text = (raw or "").strip()
    if not text:
        return {"ok": False, "kind": "rejected", "reason": "安装源为空"}

    # 先认 URL（含 git@ 形式）。不是 URL 才按包名判，避免把 URL 误当包名。
    if "://" in text or text.startswith("git@"):
        m = _GITHUB_URL_RE.match(text)
        if not m:
            return {"ok": False, "kind": "rejected",
                    "reason": "仅支持 GitHub 仓库地址（https://github.com/owner/repo）"}
        host = (m.group("host") or "").lower()
        if host not in _ALLOWED_HOSTS:
            return {"ok": False, "kind": "rejected",
                    "reason": f"仅允许 github.com 地址，当前为 {host}"}
        owner, repo = m.group("owner"), m.group("repo")
        if not owner or not repo:
            return {"ok": False, "kind": "rejected", "reason": "无法解析 owner/repo"}
        return {
            "ok": True, "kind": "github", "source": text,
            "host": host, "owner": owner, "repo": repo,
            "subpath": (m.group("subpath") or "").strip("/"),
            "canonical": f"https://github.com/{owner}/{repo}",
        }

    if not _PACKAGE_RE.match(text):
        return {"ok": False, "kind": "rejected",
                "reason": "包名形状应为 owner/repo 或 owner/repo@skill"}
    return {"ok": True, "kind": "package", "source": text, "package": text}


def plan_repo_preview(source: str) -> Dict[str, Any]:
    """生成「列出仓库内技能」的计划，不执行也不安装。

    `add -l` 只读：列出该仓库包含哪些技能。一个仓库常含多个技能，直接 add
    会把它们全装进统一库，所以必须先预览再让用户选。
    """
    cls = classify_install_source(source)
    if not cls["ok"]:
        return {"ok": False, "action": "preview", "argv": [],
                "reason": cls["reason"]}
    if cls["kind"] != "github":
        return {"ok": False, "action": "preview", "argv": [],
                "reason": "预览仅适用于 GitHub 仓库地址"}
    return {
        "ok": True, "action": "preview", "source": cls["canonical"],
        "argv": ["add", cls["canonical"], "-l"],
        "reason": "",
    }


def strip_ansi(text: str) -> str:
    """去掉 ANSI 转义与行内光标控制，保留可读正文。

    `npx skills` 用 clack 输出：颜色码、`\x1b[1G\x1b[J` 这类清行控制、以及
    spinner 的 `\r` 重绘都会混进 stdout，不先洗掉就无法按行解析。
    """
    if not text:
        return ""
    # CSI 序列（颜色、光标移动、清屏）与 OSC 序列
    text = _ANSI_RE.sub("", text)
    # spinner 用 
    # spinner 用回车符反复重绘同一行：只保留最后一次绘制的内容
    text = text.replace("\r", "\n")
    return text


def parse_preview_skills(raw: str) -> Dict[str, Any]:
    """解析 `npx skills add <url> -l` 的输出，返回可勾选的技能清单。

    实测输出形状（2026-11-15）：
        ◇  Found 9 skills
        │
        ◇  Available Skills
        │
        │    vercel-composition-patterns      ← 名字：4 空格缩进
        │
        │      React composition patterns...  ← 描述：6 空格缩进
        │
        │    deploy-to-vercel

    判定规则：只认「`│` 后恰好 4 个空格 + 无空格的单 token」为技能名；
    描述行缩进更深，标题行带 `◇`，都不会被误收。
    """
    text = strip_ansi(raw)
    if not text.strip():
        return {"ok": False, "skills": [], "reason": "仓库未返回技能列表",
                "declared_count": None, "parsed_count": 0,
                "count_mismatch": False}

    declared = None
    m = _FOUND_RE.search(text)
    if m:
        declared = int(m.group(1))

    skills: List[Dict[str, str]] = []
    pending_name: Optional[str] = None
    for line in text.split("\n"):
        nm = _SKILL_NAME_RE.match(line)
        if nm:
            pending_name = nm.group(1)
            skills.append({"name": pending_name, "description": ""})
            continue
        dm = _SKILL_DESC_RE.match(line)
        if dm and skills:
            desc = dm.group(1)
            # 只取第一条描述行：描述可能折成多行，全拼起来反而难读
            if not skills[-1]["description"]:
                skills[-1]["description"] = desc
            continue

    parsed = len(skills)
    mismatch = declared is not None and declared != parsed
    if not skills:
        return {"ok": False, "skills": [], "reason": "未能从仓库输出中解析出技能名",
                "declared_count": declared, "parsed_count": 0,
                "count_mismatch": mismatch}
    return {"ok": True, "skills": skills, "reason": "",
            "declared_count": declared, "parsed_count": parsed,
            "count_mismatch": mismatch}


def plan_install_repo(
    source: str,
    skills: Optional[List[str]] = None,
    all_skills: bool = False,
    agents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """生成「从 GitHub 仓库安装指定技能」的计划，不执行。

    必须显式二选一：``skills``（装指定）或 ``all_skills=True``（装全部）。
    **不接受「什么都不传」**：那会让一次误点把整仓库几十个技能装进统一库。
    """
    cls = classify_install_source(source)
    if not cls["ok"]:
        return {"ok": False, "action": "install", "argv": [],
                "reason": cls["reason"]}
    if cls["kind"] != "github":
        return {"ok": False, "action": "install", "argv": [],
                "reason": "该入口仅用于 GitHub 仓库地址"}

    clean_skills = [s.strip() for s in (skills or []) if s and s.strip()]
    if clean_skills and all_skills:
        return {"ok": False, "action": "install", "argv": [],
                "reason": "不能同时指定具体技能与全部技能"}
    if not clean_skills and not all_skills:
        return {"ok": False, "action": "install", "argv": [],
                "reason": "未选择要安装的技能：请先预览并勾选，或显式选择全部"}

    argv = ["add", cls["canonical"], "-g", "-y"]
    if all_skills:
        argv += ["--skill", "*"]
    else:
        argv += ["--skill", ",".join(clean_skills)]

    clean_agents = [a.strip() for a in (agents or []) if a and a.strip()]
    if clean_agents:
        argv += ["--agent", ",".join(clean_agents)]

    return {
        "ok": True, "action": "install", "source": cls["canonical"],
        "owner": cls["owner"], "repo": cls["repo"],
        "skills": clean_skills, "all_skills": all_skills,
        "agents": clean_agents, "argv": argv, "reason": "",
    }


def detect_conflicts(names: List[str]) -> Dict[str, Any]:
    """装前重名检测：已存在与缺失分开报，绝不静默覆盖。

    `npx skills add` 遇到同名技能会覆盖既有内容，而用户往往不知道统一库里
    已有同名技能 —— 直接装等于无声替换。因此安装前必须先查一次。
    """
    root = _skills_dir()
    present, missing = [], []
    for name in names or []:
        clean = (name or "").strip()
        if not clean:
            continue
        (present if (root / clean).is_dir() else missing).append(clean)
    return {
        "ok": True,
        "conflicts": present,
        "missing": missing,
        "has_conflict": bool(present),
        "root": str(root),
    }


def plan_upgrade(names: List[str]) -> Dict[str, Any]:
    """生成升级计划，不执行。names 为空则拒绝。"""
    clean = [n.strip() for n in (names or []) if n and n.strip()]
    if not clean:
        return {"ok": False, "action": "upgrade", "names": [], "argv": [],
                "reason": "未指定要升级的技能"}
    return {
        "ok": True,
        "action": "upgrade",
        "names": clean,
        "argv": ["update", *clean, "-g", "-y"],
        "reason": "",
    }


def verify_installed(names: List[str]) -> Dict[str, Any]:
    """校验技能是否已落在统一库。装后必查，避免「命令成功但没装上」。"""
    root = _skills_dir()
    present, missing = [], []
    for n in names or []:
        (present if (root / n).is_dir() else missing).append(n)
    return {
        "ok": not missing,
        "present": present,
        "missing": missing,
        "root": str(root),
    }


def execute_plan(
    plan: Dict[str, Any],
    runner: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """执行计划。runner 可注入（测试期不真跑 npx）。不抛异常。"""
    if not plan.get("ok"):
        return {"ok": False, "stdout": "", "stderr": "",
                "reason": plan.get("reason", ""), "verify": None}

    # 升级前备份（2026-10-23 评审修复）：UI 一直承诺「升级前自动备份」，
    # 但此前从未实现——上游把内容改坏时用户毫无退路。安装（install）不备份
    # （新装无旧内容可留），升级（upgrade）逐个技能备份。
    backups: Dict[str, str] = {}
    if plan.get("action") == "upgrade":
        for name in list(plan.get("names") or []):
            # backup_skill 现在返回结构体：ok=新备份，skipped=内容未变、
            # 沿用最近一份（同样可作为回滚点），failed 才不带路径。
            res = backup_skill(name)
            if res.get("status") in ("ok", "skipped") and res.get("path"):
                backups[name] = res["path"]

    run = runner or _run_npx
    try:
        res = run(plan["argv"], timeout=1800)
    except Exception as exc:                      # runner 崩溃不应中断调用方
        # backups 一并带出：备份已经落盘，用户即便升级失败也可以回滚
        return {"ok": False, "stdout": "", "stderr": str(exc),
                "reason": "执行失败", "verify": None, "action": plan["action"],
                "backups": backups}

    out: Dict[str, Any] = {
        "ok": res.get("code") == 0,
        "code": res.get("code"),
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", ""),
        "action": plan["action"],
        "reason": "",
        "backups": backups,
    }
    if plan["action"] == "install":
        # 包名形如 owner/repo@skill，落盘目录名取 @ 之后
        out["verify"] = verify_installed([plan["package"].split("@")[-1]])
    else:
        out["verify"] = verify_installed(plan["names"])

    if out["ok"] and not out["verify"]["ok"]:
        out["ok"] = False
        out["stderr"] = (out["stderr"] or "") + "\n命令成功但统一库中未找到安装结果"

    # v0.31.0：npx skills update 可能 exit 0 但实际没升级（实测：上游仓库
    # 迁移时输出「1 skill(s) cannot be checked automatically: find-skills
    # (Private or deleted repo)」——verify 只查目录存在会误报成功，用户
    # 看到假成功且版本不变）。解析 stdout 的失败标记：
    # - 有 npx 建议的重装命令 → **自动回退重装**（用户定案 2026-10-22：
    #   「重装也属于升级的一种，只要是结果是一致的即可」）；
    # - 无建议命令 → 诚实报告失败。
    if out["ok"] and plan["action"] == "upgrade":
        parsed = _parse_upgrade_failure(out.get("stdout", ""))
        if parsed["failure"]:
            fallback_argv = parsed["fallback_argv"]
            if fallback_argv:
                try:
                    res2 = run(fallback_argv, timeout=1800)
                except Exception as exc:
                    res2 = {"code": -1, "stdout": "", "stderr": str(exc)}
                if res2.get("code") == 0:
                    out["ok"] = True
                    out["action"] = "upgrade-reinstall"
                    out["fallback"] = "上游仓库迁移，已按建议自动重装到最新版"
                    out["stdout"] = (out.get("stdout") or "") + "\n[自动重装] " + (res2.get("stdout") or "")
                else:
                    out["ok"] = False
                    out["reason"] = "上游无法更新且自动重装失败"
                    out["stderr"] = (out["stderr"] or "") + "\n" + parsed["failure"] + \
                        "\n自动重装也失败：" + (res2.get("stderr") or "")
            else:
                out["ok"] = False
                out["reason"] = "上游无法更新"
                out["stderr"] = (out["stderr"] or "") + "\n" + parsed["failure"]

    # v0.31.0：安装/升级成功后写版本记录（data/skill_versions.json）——
    # 回滚基准（--skill-rollback 留后续版本）+ 更新检查的本机基准。
    # 版本取安装后 SKILL.md frontmatter 的 version（刚落盘，读它最准）。
    if out["ok"]:
        try:
            out["versions_written"] = _record_versions(plan)
        except Exception:
            # 记录失败不阻断安装结果（best-effort；主流程已成功）
            out["versions_written"] = 0
    return out


def _parse_upgrade_failure(stdout: str) -> Dict[str, Any]:
    """解析 npx skills update 的「exit 0 但没升级」输出。

    返回 ``{"failure": str, "fallback_argv": [str]}``（无失败时 failure 为空）。

    实测标记（2026-10-22，find-skills 上游迁移）::

        1 skill(s) cannot be checked automatically:
          • find-skills (Private or deleted repo)
            To update: npx skills add https://github.com/... -g -y

    ANSI 色码先剥离再匹配（npx 输出带 38;5;xxx 色码）。
    fallback_argv 从「To update: npx skills <argv>」提取（自动重装回退用，
    用户定案 2026-10-22：重装也属于升级，结果一致即可）。
    """
    import re as _re

    plain = _re.sub(r"\x1b\[[0-9;]*m", "", stdout or "")
    if "cannot be checked automatically" not in plain:
        return {"failure": "", "fallback_argv": []}
    lines = [ln.strip() for ln in plain.split("\n") if ln.strip()]
    failed = [ln for ln in lines if _re.match(r"^[•\-*]\s+\S+\s+\(", ln)]
    hint = next((ln for ln in lines if ln.startswith("To update:")), "")
    parts = ["以下技能无法自动更新（上游仓库私有/已迁移/已删除）："]
    parts.extend(f"  {f}" for f in failed)
    fallback_argv: List[str] = []
    if hint:
        # "To update: npx skills add <url> -g -y" → ["add", "<url>", "-g", "-y"]
        m = _re.match(r"To update:\s*npx skills (.+)$", hint)
        if m:
            fallback_argv = m.group(1).split()
        parts.append(f"修复建议：{hint.replace('To update: ', '')}")
    return {"failure": "\n".join(parts), "fallback_argv": fallback_argv}


def _backup_root() -> Path:
    """升级备份根目录（独立成函数便于测试替换）。

    位置：``<repo>/data/skill_backups/<技能名>/<时间戳>/``。放 data/ 下是因为
    它已被 .gitignore 覆盖、且与项目其他备份（``*.bak-<时间戳>``）同一区域。
    """
    return Path(__file__).resolve().parents[1] / "data" / "skill_backups"


#: 每个技能保留的备份份数上限（内容不同的历史版本）。
#: 2026-11-09 用户实测 find-skills 攒了 327 份、其中 326 份字节完全一致——
#: 升级每次都无条件备份，纯粹占盘。上限 + 内容去重一起解决。
DEFAULT_BACKUP_KEEP = 10


def _tree_hash(root: Path) -> str:
    """目录内容指纹：相对路径 + 文件字节，**与 mtime 无关**。

    用来判断「这次要备份的内容是否与最近一份备份相同」。不能用 mtime：
    ``copytree`` 之后备份目录里的文件时间会变，而内容其实一样。
    """
    import hashlib

    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        h.update(str(p.relative_to(root)).encode("utf-8"))
        h.update(b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"<unreadable>")
        h.update(b"\0")
    return h.hexdigest()


def _backup_dirs(name: str) -> List[Path]:
    """某技能的备份目录（新到旧；目录名即时间戳，可直接按名排序）。"""
    root = _backup_root() / name
    if not root.is_dir():
        return []
    return sorted([d for d in root.iterdir() if d.is_dir()],
                  key=lambda p: p.name, reverse=True)


def _dir_size(root: Path) -> int:
    try:
        return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    except OSError:
        return 0


def _prune_skill_dir(skill_root: Path, keep: int, *, dry_run: bool = False) -> Dict[str, Any]:
    """单个技能的备份目录：**内容去重 + 保留最近 keep 份**。

    从新到旧扫，规则两条（任一命中即删）：
    1. 内容与更靠前的某份完全相同（去重，保留最新的那一份）；
    2. 已经保留了 ``keep`` 份不同内容（上限，删更旧的）。
    """
    import shutil

    snaps = sorted([d for d in skill_root.iterdir() if d.is_dir()],
                   key=lambda p: p.name, reverse=True)
    seen: set = set()
    kept = removed = freed = 0
    for snap in snaps:
        digest = _tree_hash(snap)
        duplicate = digest in seen
        over = kept >= max(0, int(keep))
        if duplicate or over:
            size = _dir_size(snap)
            if not dry_run:
                try:
                    shutil.rmtree(snap)
                except OSError:
                    continue  # 删不掉就跳过，不影响其它备份
            removed += 1
            freed += size
            continue
        seen.add(digest)
        kept += 1
    return {"kept": kept, "removed": removed, "freed": freed}


def prune_skill_backups(
    keep: int = DEFAULT_BACKUP_KEEP,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """清理升级前备份：全部技能做「内容去重 + 保留最近 keep 份」。

    返回::

        {"status": "ok"|"dry-run"|"nothing-to-prune",
         "skills": N, "kept": N, "removed": N, "freed": 字节数,
         "names": [有清理动作的技能], "message": "..."}
    """
    root = _backup_root()
    stats: Dict[str, Any] = {
        "skills": 0, "kept": 0, "removed": 0, "freed": 0, "names": [],
    }
    if not root.is_dir():
        return {**stats, "status": "nothing-to-prune",
                "message": "没有升级备份目录（还没发生过升级）"}

    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not any(d.is_dir() for d in skill_dir.iterdir()):
            continue
        stats["skills"] += 1
        one = _prune_skill_dir(skill_dir, keep, dry_run=dry_run)
        stats["kept"] += one["kept"]
        stats["removed"] += one["removed"]
        stats["freed"] += one["freed"]
        if one["removed"]:
            stats["names"].append(skill_dir.name)

    if stats["removed"] == 0:
        return {**stats, "status": "nothing-to-prune",
                "message": f"备份已是最简（无重复、未超过每技能 {keep} 份上限）"}

    freed_mb = stats["freed"] / 1024 / 1024
    action = "将删除" if dry_run else "已删除"
    return {
        **stats,
        "status": "dry-run" if dry_run else "ok",
        "message": f"{action} {stats['removed']} 份重复/超限备份"
                   f"（保留 {stats['kept']} 份，涉及 {len(stats['names'])} 个技能）"
                   f"，释放约 {freed_mb:.1f} MB",
    }


def backup_stats() -> Dict[str, Any]:
    """只读：备份总量与重复情况（GUI 卡片展示用）。

    ``duplicates`` 按内容指纹统计——同一技能下与更早备份内容相同的份数，
    也就是「清理能删掉多少」。
    """
    root = _backup_root()
    stats: Dict[str, Any] = {
        "skills": 0, "snapshots": 0, "duplicates": 0,
        "bytes": 0, "root": str(root), "keep": DEFAULT_BACKUP_KEEP,
    }
    if not root.is_dir():
        return stats
    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue
        snaps = sorted([d for d in skill_dir.iterdir() if d.is_dir()],
                       key=lambda p: p.name, reverse=True)
        if not snaps:
            continue
        stats["skills"] += 1
        stats["snapshots"] += len(snaps)
        seen: set = set()
        kept = 0
        for snap in snaps:
            digest = _tree_hash(snap)
            stats["bytes"] += _dir_size(snap)
            if digest in seen or kept >= DEFAULT_BACKUP_KEEP:
                stats["duplicates"] += 1
                continue
            seen.add(digest)
            kept += 1
    return stats


def backup_skill(
    name: str,
    skills_dir: Optional[Path] = None,
    *,
    keep: int = DEFAULT_BACKUP_KEEP,
) -> Dict[str, Any]:
    """升级前把技能目录整体复制一份。

    返回 ``{"status": "ok"|"skipped"|"failed", "path": str, "reason": str}``。

    **为什么必须有这一步**：升级弹框对用户承诺「本地内容会被上游覆盖，
    升级前自动备份」。此前 ``execute_plan`` 只跑 npx、只做安装后校验，
    **从未备份**——承诺是空的（2026-10-23 评审发现）。上游把技能改坏、
    或迁移后重装成完全不同内容时，用户将永久失去原版。

    **内容去重**（2026-11-09 用户要求）：要备份的内容与最近一份备份完全相同
    时返回 ``skipped``，不再复制一份。实测 find-skills 攒了 327 份、326 份
    字节一致，全是白占盘。
    **份数上限**：备份成功后顺手淘汰超出 ``keep`` 的旧版本。
    """
    import shutil
    from datetime import datetime

    src = (skills_dir or _skills_dir()) / name
    if not src.is_dir():
        return {"status": "failed", "path": "", "reason": "技能目录不存在"}

    existing = _backup_dirs(name)
    if existing:
        latest = existing[0]
        if _tree_hash(latest) == _tree_hash(src):
            return {"status": "skipped", "path": str(latest),
                    "reason": "与最近一份备份内容相同，跳过重复备份"}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = _backup_root() / name / stamp
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, symlinks=True)
    except (OSError, shutil.Error) as exc:
        return {"status": "failed", "path": "", "reason": f"备份失败：{exc}"}

    pruned = _prune_skill_dir(dest.parent, keep)
    reason = ""
    if pruned["removed"]:
        reason = f"已清理 {pruned['removed']} 份旧备份（超过每技能 {keep} 份上限或内容重复）"
    return {"status": "ok", "path": str(dest), "reason": reason}


def list_skill_backups(name: str) -> List[Dict[str, Any]]:
    """列出某技能的升级前备份（新到旧）。"""
    root = _backup_root() / name
    if not root.is_dir():
        return []
    import datetime as _dt

    out: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        try:
            size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
        except OSError:
            size = 0
        try:
            mtime = _dt.datetime.fromtimestamp(child.stat().st_mtime)
            mtime_text = mtime.strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            mtime_text = ""
        out.append({"path": str(child), "name": child.name,
                    "mtime_text": mtime_text, "size": size})
    return out


def restore_skill_backup(name: str, backup_path: str,
                         skills_dir: Optional[Path] = None) -> Dict[str, Any]:
    """用备份覆盖当前技能目录（回滚）。

    先把当前目录另存为 ``.before-restore-<时间戳>``，再整体替换——
    回滚本身也必须可撤销，否则「恢复错了」没有退路。
    """
    import shutil
    from datetime import datetime

    dest = (skills_dir or _skills_dir()) / name
    src = Path(backup_path)
    if not src.is_dir():
        return {"ok": False, "reason": "备份路径不存在"}
    # 备份必须属于该技能，防误传其它技能的路径
    if _backup_root().resolve() not in src.resolve().parents:
        return {"ok": False, "reason": "备份路径不在受管备份目录内"}

    safety = None
    if dest.is_dir():
        safety = dest.with_name(
            f"{name}.before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}")
        try:
            shutil.move(str(dest), str(safety))
        except (OSError, shutil.Error) as exc:
            return {"ok": False, "reason": f"暂存当前版本失败：{exc}"}
    try:
        shutil.copytree(src, dest, symlinks=True)
    except (OSError, shutil.Error) as exc:
        # 恢复失败要把当前版本放回去，不能留下半成品
        if safety is not None and safety.is_dir() and not dest.exists():
            shutil.move(str(safety), str(dest))
        return {"ok": False, "reason": f"覆盖失败：{exc}"}
    return {"ok": True, "restored_from": str(src),
            "previous_saved_at": str(safety) if safety else ""}


def _record_versions(plan: Dict[str, Any]) -> int:
    """把本次安装/升级的技能版本写进 data/skill_versions.json，返回写入条数。"""
    import json
    from datetime import datetime

    names = ([plan["package"].split("@")[-1]] if plan["action"] == "install"
             else list(plan.get("names") or []))
    if not names:
        return 0
    from skill_state import read_skill_meta
    meta = read_skill_meta(str(_skills_dir()), names)
    vpath = Path(__file__).resolve().parents[1] / "data" / "skill_versions.json"
    records: Dict[str, Any] = {}
    if vpath.is_file():
        try:
            records = json.loads(vpath.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            records = {}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    written = 0
    for name in names:
        ver = (meta.get(name) or {}).get("version")
        if not ver:
            continue
        prev = records.get(name) or {}
        records[name] = {
            "version": ver,
            "source": plan.get("package") if plan["action"] == "install" else prev.get("source"),
            "installed_at": prev.get("installed_at") if plan["action"] == "upgrade" else now,
            "updated_at": now,
        }
        written += 1
    if written:
        vpath.parent.mkdir(parents=True, exist_ok=True)
        vpath.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written
