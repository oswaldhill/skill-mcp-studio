"""技能合并执行（FEAT-12）：把整理建议落成实际操作。

本模块是 FEAT-11 只读判据的写侧对应物。判据仍在 `skill_merge_advisor`，
本模块只负责"按一条已经成立的建议去动盘"，且动盘前后都要能解释。

为什么执行前必须重算判据：
界面上的「可执行合并」来自缓存（可能几十分钟前扫的）。期间用户可能手动
改过技能、装了新技能、或改过挂载。若照着过期建议执行，等于用旧世界的
结论去改新世界的盘。因此这里不信任传入的 keep/fold，而是重新跑一遍判据，
确认该组此刻仍在 actionable 里，否则拒绝。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from pathlib import Path

from skill_merge_advisor import scan_advice
from skill_ops import soft_delete_skill


def _resolve_dir(skills_dir: Optional[str]) -> Path:
    """把传入的目录统一成已展开的绝对 Path。

    `scan_advice` 收 Path，直接把带 `~` 的 str 传进去不会展开，会扫到空目录，
    导致判据复核永远报"建议已不成立" —— 表现为执行被永久拒绝（不误删，但功能
    完全不可用）。所以这里统一先展开。
    """
    raw = skills_dir or "~/.skills-manager/skills"
    return Path(os.path.expanduser(str(raw)))

# 单次最多归并的技能数：一次误操作的爆炸半径上限。
_MAX_FOLD = 20


def _err(message: str, *, steps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "status": "error",
        "message": message,
        "keep": "",
        "folded": [],
        "failed": [],
        "steps": steps or [],
    }


def _find_group(advice: Dict[str, Any], keep: str, fold: Sequence[str]) -> Optional[Dict[str, Any]]:
    """在本次重算的 actionable 里找出与该请求对应的一组。

    匹配要求：保留方一致，且请求的归并方**全部**在该组内（允许组里还有
    对方多出来的成员，那种情况下面会按请求执行，不擅自扩大范围）。
    """
    want = set(fold)
    for grp in advice.get("actionable") or []:
        if grp.get("keep") != keep:
            continue
        members = set(grp.get("members") or [])
        if want <= members:
            return grp
    return None


def merge_group(
    keep: str,
    fold: Sequence[str],
    *,
    skills_dir: Optional[str] = None,
    dry_run: bool = False,
    advice: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按一条整理建议执行合并：归并方备份后移入 _trash，保留方不动。

    返回 ``{"status", "message", "keep", "folded", "failed", "steps"}``。
    status ∈ ok / dry-run / error。

    `advice` **仅供测试注入**已算好的判据，避免每个用例都重扫会话日志（一次
    约 1 分多钟）。CLI 与 GUI **一律不传**：生产路径必须自己重算，否则就变成
    信任界面传来的结论，那道防误删的护栏也就失效了。
    """
    keep = (keep or "").strip()
    fold = [f.strip() for f in (fold or []) if f and f.strip()]

    if not keep:
        return _err("缺少保留方技能名")
    if not fold:
        return _err("缺少要归并的技能名")
    if keep in fold:
        return _err(f"保留方 {keep} 不能同时是要归并的技能")
    if len(fold) > _MAX_FOLD:
        return _err(f"一次最多归并 {_MAX_FOLD} 个技能，本次请求 {len(fold)} 个")

    # ---- 1. 重算判据：不信任界面传来的结论 -------------------------------
    base_path = _resolve_dir(skills_dir)
    if advice is None:
        try:
            advice = scan_advice(skills_dir=base_path)
        except Exception as exc:  # noqa: BLE001 - 判据异常一律拒绝执行
            return _err(f"执行前复核判据失败，未做任何改动：{exc}")

    if advice.get("error"):
        return _err(f"执行前复核判据失败，未做任何改动：{advice['error']}")

    grp = _find_group(advice, keep, fold)
    if grp is None:
        return _err(
            f"该建议已不成立：{keep} 与 {', '.join(fold)} 此刻不再构成可执行合并组。"
            "可能技能库已变动，请重新统计后再看。未做任何改动。"
        )

    # ---- 2. 确认目录都在 --------------------------------------------------
    base = str(base_path)
    missing = [n for n in [keep] + list(fold) if not os.path.isdir(os.path.join(base, n))]
    if missing:
        return _err(f"未找到技能目录：{', '.join(missing)}。未做任何改动。")

    # ---- 3. 逐个归并（备份 + 移入 _trash，可恢复）--------------------------
    steps: List[Dict[str, Any]] = []
    folded: List[str] = []
    failed: List[Dict[str, str]] = []

    for name in fold:
        res = soft_delete_skill(base, name, dry_run=dry_run)
        status = res.get("status", "error")
        if status in ("ok", "dry-run"):
            folded.append(name)
            steps.append({
                "status": status,
                "step": f"归并 {name}",
                "message": f"备份 {res.get('backup', '')}，移入 {res.get('path', '')}",
            })
        else:
            failed.append({"name": name, "message": res.get("message", "未知错误")})
            steps.append({
                "status": "error",
                "step": f"归并 {name}",
                "message": res.get("message", "未知错误"),
            })

    # ---- 4. 如实报告 ----------------------------------------------------
    if failed and folded:
        return {
            "status": "error",
            "message": f"部分失败：已归并 {len(folded)} 个，{len(failed)} 个失败。"
                       f"保留方 {keep} 未改动。",
            "keep": keep,
            "folded": folded,
            "failed": failed,
            "steps": steps,
        }
    if failed:
        return {
            "status": "error",
            "message": f"归并失败，未改动任何技能（{len(failed)} 个失败）。",
            "keep": keep,
            "folded": [],
            "failed": failed,
            "steps": steps,
        }

    verb = "将归并" if dry_run else "已归并"
    return {
        "status": "dry-run" if dry_run else "ok",
        "message": f"{verb} {len(folded)} 个技能到 {keep}：{', '.join(folded)}"
                   f"（已备份到 _backup/ 并移入 _trash/，可恢复）",
        "keep": keep,
        "folded": folded,
        "failed": [],
        "steps": steps,
    }


def merge_all(
    *,
    skills_dir: Optional[str] = None,
    dry_run: bool = False,
    advice: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行全部可执行合并组：对每个 actionable 组调用 merge_group。

    逐组独立执行：某组失败不影响其他组，最后汇总。
    """
    base_path = _resolve_dir(skills_dir)
    if advice is None:
        try:
            advice = scan_advice(skills_dir=base_path)
        except Exception as exc:  # noqa: BLE001
            return _err(f"复核判据失败，未做任何改动：{exc}")
    if advice.get("error"):
        return _err(f"复核判据失败，未做任何改动：{advice['error']}")

    groups = advice.get("actionable") or []
    if not groups:
        return {
            "status": "ok", "message": "当前没有可执行合并组。",
            "keep": "", "folded": [], "failed": [], "steps": [],
        }

    all_folded: List[str] = []
    all_failed: List[Dict[str, str]] = []
    steps: List[Dict[str, Any]] = []
    ok_groups = 0

    for grp in groups:
        keep = grp.get("keep") or ""
        fold = grp.get("fold") or []
        if not keep or not fold:
            continue
        res = merge_group(keep, fold, skills_dir=str(base_path), dry_run=dry_run,
                          advice=advice)
        if res.get("status") in ("ok", "dry-run"):
            ok_groups += 1
            all_folded.extend(res.get("folded") or [])
        else:
            # 组级失败（如某成员目录不存在，整组被拒）时 res["failed"] 可能为空，
            # 若只看它就会把这一组漏掉，最终误报整体成功。这里补一条组级失败。
            fails = res.get("failed") or [
                {"name": keep, "message": res.get("message", "该组未能执行")}
            ]
            all_failed.extend(fails)
        all_folded.extend([] if res.get("status") not in ("ok", "dry-run")
                          else [])
        steps.append({
            "status": res.get("status", "error"),
            "step": f"合并组 {keep}",
            "message": res.get("message", ""),
        })

    if all_failed and not all_folded:
        return {
            "status": "error",
            "message": f"全部失败：{len(all_failed)} 个技能未能归并。",
            "keep": "", "folded": [], "failed": all_failed, "steps": steps,
        }

    verb = "将归并" if dry_run else "已归并"
    tail = f"，{len(all_failed)} 个失败" if all_failed else ""
    return {
        "status": "error" if all_failed else ("dry-run" if dry_run else "ok"),
        "message": f"{verb} {len(all_folded)} 个技能（{ok_groups} 组）{tail}。"
                   f"备份在 _backup/，原件在 _trash/。",
        "keep": "", "folded": all_folded, "failed": all_failed, "steps": steps,
    }
