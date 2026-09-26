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

    run = runner or _run_npx
    try:
        res = run(plan["argv"], timeout=1800)
    except Exception as exc:                      # runner 崩溃不应中断调用方
        return {"ok": False, "stdout": "", "stderr": str(exc),
                "reason": "执行失败", "verify": None, "action": plan["action"]}

    out: Dict[str, Any] = {
        "ok": res.get("code") == 0,
        "code": res.get("code"),
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", ""),
        "action": plan["action"],
        "reason": "",
    }
    if plan["action"] == "install":
        # 包名形如 owner/repo@skill，落盘目录名取 @ 之后
        out["verify"] = verify_installed([plan["package"].split("@")[-1]])
    else:
        out["verify"] = verify_installed(plan["names"])

    if out["ok"] and not out["verify"]["ok"]:
        out["ok"] = False
        out["stderr"] = (out["stderr"] or "") + "\n命令成功但统一库中未找到安装结果"
    return out
