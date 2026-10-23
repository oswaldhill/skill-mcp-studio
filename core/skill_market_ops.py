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
            path = backup_skill(name)
            if path:
                backups[name] = path

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


def backup_skill(name: str, skills_dir: Optional[Path] = None) -> Optional[str]:
    """升级前把技能目录整体复制一份，返回备份路径（失败返回 None）。

    **为什么必须有这一步**：升级弹框对用户承诺「本地内容会被上游覆盖，
    升级前自动备份」。此前 ``execute_plan`` 只跑 npx、只做安装后校验，
    **从未备份**——承诺是空的（2026-10-23 评审发现）。上游把技能改坏、
    或迁移后重装成完全不同内容时，用户将永久失去原版。

    目录可能很大，但技能包通常几百 KB；单次复制可接受。
    跳过符号链接目标不存在等异常情况（尽力而为，失败不阻断升级，
    但会在返回里体现为 None，调用方**不应**把它当作「已备份」）。
    """
    import shutil
    from datetime import datetime

    src = (skills_dir or _skills_dir()) / name
    if not src.is_dir():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = _backup_root() / name / stamp
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, symlinks=True)
        return str(dest)
    except (OSError, shutil.Error):
        return None


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
