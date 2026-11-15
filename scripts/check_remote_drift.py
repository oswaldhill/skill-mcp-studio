#!/usr/bin/env python3
"""检查本仓库多远端之间的分支漂移。

**为什么单独一个脚本而不是纯单测**：本仓库同时推 codeup（origin）与 GitHub
（github）。2026-11-15 实测 GitHub `master` 停在 `50282e5`、落后 codeup
`master` **14 个提交**（含代码），而没有任何检查会报出来。

漂移分两种性质，处理方式必须不同：

1. **分叉（diverged）** —— 两个远端同名分支各有对方没有的提交。这是**故障**，
   必须人工处理（merge 或 reset），脚本退出码非 0。
2. **落后（behind）** —— GitHub 是发布镜像，阶段性落后是**预期行为**。
   脚本只报告落后量，退出码仍为 0，避免把正常状态判成失败、逼人推无意义的
   同步。

**契约**（与 tests/test_remote_branch_consistency.py 一致）：
- codeup：`master` + `develop`
- GitHub：只有 `master`，不应有 `develop`

用法::

    python3 scripts/check_remote_drift.py            # 人类可读报告
    python3 scripts/check_remote_drift.py --json     # 机读
    python3 scripts/check_remote_drift.py --strict   # 落后也判失败（发版前用）

**只读**：只跑 `git ls-remote` / `rev-list` / `merge-base`，不 fetch、不 push、
不改任何引用。要保持本地 tracking ref 新鲜，请自行 `git fetch --all`。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

#: 期望的分支拓扑。GitHub 不该有 develop。
EXPECTED: Dict[str, List[str]] = {
    "origin": ["master", "develop"],
    "github": ["master"],
}


def _git(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(ROOT), *args],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def _ls_remote(remote: str, branch: str) -> Optional[str]:
    """向服务器查某个分支的 sha。不存在返回 None。"""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-remote", "--heads", remote, branch],
        capture_output=True, text=True, timeout=60)
    line = out.stdout.strip()
    return line.split("\t")[0] if line else None


def _count(expr: str) -> int:
    txt = _git("rev-list", "--count", expr)
    try:
        return int(txt)
    except ValueError:
        return 0


def _is_ancestor(a: str, b: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", a, b],
        capture_output=True, timeout=60).returncode == 0


def inspect() -> Dict[str, Any]:
    remotes = _git("remote").split()
    report: Dict[str, Any] = {"remotes": remotes, "problems": [], "notes": [], "pairs": []}

    if not remotes:
        report["problems"].append("本仓库没有配置任何远端")
        return report

    tips: Dict[str, Optional[str]] = {}
    for remote, branches in EXPECTED.items():
        if remote not in remotes:
            report["notes"].append(f"未配置远端 {remote}，跳过")
            continue
        for branch in branches:
            tips[f"{remote}/{branch}"] = _ls_remote(remote, branch)

    # 形状检查：GitHub 不该有 develop
    if "github" in remotes:
        if _ls_remote("github", "develop"):
            report["problems"].append(
                "GitHub 上出现了 develop 分支 —— 该远端约定只保留 master")

    # 同名分支跨远端比对：origin/x vs github/x
    if "origin" in remotes and "github" in remotes:
        for branch in EXPECTED["origin"]:
            o = tips.get(f"origin/{branch}")
            g = tips.get(f"github/{branch}")
            if not o or not g:
                continue
            if o == g:
                report["pairs"].append({"branch": branch, "state": "in-sync",
                                        "origin": o[:8], "github": g[:8]})
                continue
            diverged = (not _is_ancestor(g, o)) and (not _is_ancestor(o, g))
            if diverged:
                report["problems"].append(
                    f"{branch} 在 origin 与 github 之间已分叉，需人工处理")
                report["pairs"].append({"branch": branch, "state": "diverged",
                                        "origin": o[:8], "github": g[:8]})
                continue
            if _is_ancestor(g, o):
                behind = _count(f"{g}..{o}")
                report["pairs"].append({"branch": branch, "state": "github-behind",
                                        "origin": o[:8], "github": g[:8],
                                        "behind": behind})
                report["notes"].append(
                    f"GitHub 的 {branch} 落后 origin 的 {branch} {behind} 个提交"
                    f"（发布镜像允许落后，发版前用 --strict 检查）")
            else:
                ahead = _count(f"{o}..{g}")
                report["pairs"].append({"branch": branch, "state": "github-ahead",
                                        "origin": o[:8], "github": g[:8],
                                        "ahead": ahead})
                report["notes"].append(
                    f"GitHub 的 {branch} 领先 origin {ahead} 个提交 ——"
                    " 可能有人直接推了 GitHub，值得核对")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="检查多远端分支漂移（只读）")
    ap.add_argument("--json", action="store_true", help="输出机读 JSON")
    ap.add_argument("--strict", action="store_true",
                    help="落后也判失败（发版前用）")
    args = ap.parse_args()

    rep = inspect()

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("远端漂移检查")
        print(f"  已配置远端: {', '.join(rep['remotes']) or '(无)'}")
        if rep["pairs"]:
            print()
            for p in rep["pairs"]:
                extra = ""
                if "behind" in p:
                    extra = f"  落后 {p['behind']} 个提交"
                elif "ahead" in p:
                    extra = f"  领先 {p['ahead']} 个提交"
                print(f"  [{p['state']:14s}] {p['branch']:8s} "
                      f"origin={p['origin']} github={p['github']}{extra}")
        if rep["notes"]:
            print()
            for n in rep["notes"]:
                print(f"  提示: {n}")
        if rep["problems"]:
            print()
            for x in rep["problems"]:
                print(f"  问题: {x}")
        else:
            print()
            print("  无分叉，无违反契约的分支")

    if rep["problems"]:
        return 1
    if args.strict:
        behind = [p for p in rep["pairs"] if p.get("behind")]
        if behind:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())