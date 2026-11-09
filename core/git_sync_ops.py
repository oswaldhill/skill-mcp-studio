"""Git 技能源的**写操作**：clone / fetch / pull / merge / push。

## 与 ``git_sources`` 的分工

``git_sources`` 只读（登记 + 观测）；本模块是唯一会改变仓库内容或远端状态
的地方。分开是为了让「看一眼状态」永远不会意外改动仓库。

## 四种同步动作的语义（2026-11-07 需求确认）

| 动作 | git 命令 | 安全性 | 何时用 |
|---|---|---|---|
| 检查（check） | ``fetch`` + ``rev-list`` | 只动 refs，不动工作区 | 想知道远端有没有新东西 |
| 快进拉取（pull-ff） | ``merge --ff-only`` | **分叉即拒绝**，绝不产生合并提交 | 日常同步（推荐） |
| 合并拉取（merge） | ``merge --no-edit`` | 会产生合并提交，冲突时停下并报告 | 本地有独立提交且确实要合 |
| 推送（push） | ``push`` | 推本地提交到远端 | 本地改动要共享 |

## 三条硬约束

1. **默认不写**：所有动作在 ``--dry-run`` 分支下只返回「将要做什么」，
   不执行会改变状态的命令。``fetch`` 例外——它只更新本地 refs，不碰工作区，
   且「检查要不要更新」本就依赖它。
2. **脏工作区不静默丢改动**：``pull-ff`` 遇到脏工作区直接拒绝，
   不 stash、不强制覆盖。（``merge`` 同样拒绝——理由一致：用户没要求
   我们把改动藏起来。）
3. **冲突不猜**：合并冲突时返回 ``status=conflict`` 与冲突文件列表，
   **不自动 abort**（保留现场让用户自己解决），也不谎报成功。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from git_sources import (
    _git,
    _normalize_path,
    current_branch,
    head_commit,
    is_git_repo,
    remote_url,
)


# --------------------------------------------------------------------------
# 结果构造
# --------------------------------------------------------------------------
def _result(
    source_id: str,
    action: str,
    *,
    ok: bool = False,
    status: str = "",
    message: str = "",
    dry_run: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": source_id,
        "action": action,
        "ok": ok,
        "status": status or ("ok" if ok else "error"),
        "message": message,
        "dry_run": dry_run,
    }
    payload.update(extra)
    return payload


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0]


# --------------------------------------------------------------------------
# clone（「从 Git 直接拉取」的入口）
# --------------------------------------------------------------------------
def clone_source(
    url: str,
    target: str,
    *,
    source_id: str = "",
    branch: str = "",
    depth: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """把远端仓库 clone 到 ``target``。``target`` 必须不存在或为空目录。

    clone 属于「从 Git 上直接拉取」——落地后它和本地添加的目录**没有任何
    区别**，都是 git 工作区，后续都走同一套同步动作。
    """
    sid = source_id or os.path.basename(_normalize_path(target)) or "source"
    dest = _normalize_path(target)

    if not url.strip():
        return _result(sid, "clone", message="未指定仓库地址")
    if not dest:
        return _result(sid, "clone", message="未指定目标目录")
    if os.path.exists(dest) and (not os.path.isdir(dest) or os.listdir(dest)):
        return _result(sid, "clone", message=f"目标目录已存在且非空：{dest}")

    if dry_run:
        return _result(
            sid,
            "clone",
            ok=True,
            status="dry-run",
            dry_run=True,
            message=f"将 clone {url} → {dest}",
            url=url,
            target=dest,
        )

    args = ["clone"]
    if branch:
        args += ["--branch", branch]
    if depth:
        args += ["--depth", str(depth)]
    args += [url, dest]

    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, exist_ok=True)
    # git clone 的 cwd 用父目录，目标由参数指定
    rc, out, err = _git(parent, *args, timeout=300)
    if rc != 0:
        return _result(
            sid,
            "clone",
            message=f"clone 失败：{_first_line(err) or f'退出码 {rc}'}",
            url=url,
            target=dest,
        )
    return _result(
        sid,
        "clone",
        ok=True,
        message=f"已 clone 到 {dest}",
        url=url,
        target=dest,
        branch=current_branch(dest),
        head=head_commit(dest),
    )


# --------------------------------------------------------------------------
# 检查（fetch + 比较；不碰工作区）
# --------------------------------------------------------------------------
def check_source(
    source_id: str,
    path: str,
    *,
    remote: str = "origin",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """``git fetch`` 后比较本地与远端。

    fetch 只更新 ``refs/remotes/*``，不改变工作区与本地分支——这就是它不受
    ``dry_run`` 约束的原因（否则「检查」永远只能看到上次 fetch 的旧结论）。
    """
    resolved = _normalize_path(path)
    if not is_git_repo(resolved):
        return _result(source_id, "check", message=f"不是 git 仓库：{resolved}")

    if not remote_url(resolved, remote):
        return _result(
            source_id,
            "check",
            status="no-remote",
            message=f"未配置远程「{remote}」（本地仓库无需同步）",
            path=resolved,
        )

    rc, _out, err = _git(resolved, "fetch", "--prune", remote, timeout=180)
    if rc != 0:
        return _result(
            source_id,
            "check",
            status="fetch-failed",
            message=f"fetch 失败：{_first_line(err) or f'退出码 {rc}'}",
            path=resolved,
        )

    branch = current_branch(resolved)
    upstream = f"{remote}/{branch}"
    rc2, _o2, _e2 = _git(resolved, "rev-parse", "--verify", upstream)
    if rc2 != 0:
        return _result(
            source_id,
            "check",
            status="no-upstream",
            message=f"远端没有分支「{branch}」",
            path=resolved,
            branch=branch,
        )

    rc3, counts, _e3 = _git(resolved, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    ahead = behind = 0
    if rc3 == 0 and counts.strip():
        parts = counts.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    if behind == 0 and ahead == 0:
        status, msg = "current", "已是最新"
    elif behind > 0 and ahead == 0:
        status, msg = "behind", f"落后 {behind} 个提交（可快进）"
    elif ahead > 0 and behind == 0:
        status, msg = "ahead", f"领先 {ahead} 个提交（可推送）"
    else:
        status, msg = "diverged", f"已分叉：领先 {ahead} / 落后 {behind}（需合并）"

    return _result(
        source_id,
        "check",
        ok=True,
        status=status,
        message=msg,
        path=resolved,
        branch=branch,
        remote=remote,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        head=head_commit(resolved),
    )


# --------------------------------------------------------------------------
# 拉取（ff-only / merge）
# --------------------------------------------------------------------------
def _dirty_files(path: str) -> List[str]:
    rc, out, _ = _git(path, "status", "--porcelain")
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def pull_source(
    source_id: str,
    path: str,
    *,
    remote: str = "origin",
    mode: str = "ff-only",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """拉取远端更新。

    ``mode='ff-only'``（默认）：只允许快进。分叉时拒绝并提示改用 merge。
    ``mode='merge'``：允许产生合并提交；冲突时保留现场并报告。
    """
    if mode not in ("ff-only", "merge"):
        return _result(source_id, "pull", message=f"未知拉取模式：{mode}")

    resolved = _normalize_path(path)
    if not is_git_repo(resolved):
        return _result(source_id, "pull", message=f"不是 git 仓库：{resolved}")
    if not remote_url(resolved, remote):
        return _result(
            source_id,
            "pull",
            status="no-remote",
            message="未配置远程，无需拉取",
            path=resolved,
        )

    branch = current_branch(resolved)
    upstream = f"{remote}/{branch}"
    before = head_commit(resolved)

    # (1) fetch：只动 refs，dry_run 下也执行——否则判断不了要不要拉
    rc, _o, err = _git(resolved, "fetch", "--prune", remote, timeout=180)
    if rc != 0:
        return _result(
            source_id,
            "pull",
            status="fetch-failed",
            message=f"fetch 失败：{_first_line(err) or f'退出码 {rc}'}",
            path=resolved,
        )

    rc, counts, _ = _git(resolved, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    ahead = behind = 0
    if rc == 0 and counts.strip():
        parts = counts.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    if behind == 0:
        return _result(
            source_id,
            "pull",
            ok=True,
            status="current",
            message="已是最新，无需拉取",
            path=resolved,
            branch=branch,
            before=before,
            after=before,
            ahead=ahead,
            behind=0,
        )

    # (2) 脏工作区一律拒绝：不 stash、不覆盖
    dirty = _dirty_files(resolved)
    if dirty:
        return _result(
            source_id,
            "pull",
            status="dirty",
            message=f"工作区有 {len(dirty)} 个未提交改动，已拒绝拉取（请先提交或清理）",
            path=resolved,
            branch=branch,
            dirty_files=dirty[:50],
        )

    # (3) 分叉判定
    if ahead > 0 and mode == "ff-only":
        return _result(
            source_id,
            "pull",
            status="diverged",
            message=f"已分叉（领先 {ahead} / 落后 {behind}），快进模式拒绝；如需合并请用 --merge",
            path=resolved,
            branch=branch,
            ahead=ahead,
            behind=behind,
            before=before,
        )

    if dry_run:
        return _result(
            source_id,
            "pull",
            ok=True,
            status="dry-run",
            dry_run=True,
            message=f"将拉取 {behind} 个提交（{mode}）",
            path=resolved,
            branch=branch,
            ahead=ahead,
            behind=behind,
            before=before,
        )

    # (4) 执行
    if mode == "ff-only":
        rc2, _o2, err2 = _git(resolved, "merge", "--ff-only", upstream, timeout=180)
    else:
        rc2, _o2, err2 = _git(resolved, "merge", "--no-edit", upstream, timeout=180)

    after = head_commit(resolved)
    if rc2 != 0:
        # 合并冲突：保留现场，列出冲突文件
        rc3, conf, _ = _git(resolved, "diff", "--name-only", "--diff-filter=U")
        conflicts = [ln for ln in conf.splitlines() if ln.strip()] if rc3 == 0 else []
        return _result(
            source_id,
            "pull",
            status="conflict" if conflicts else "merge-failed",
            message=(
                f"合并冲突，{len(conflicts)} 个文件需手工解决"
                if conflicts
                else f"拉取失败：{_first_line(err2) or f'退出码 {rc2}'}"
            ),
            path=resolved,
            branch=branch,
            conflicts=conflicts,
            before=before,
            after=after,
        )

    return _result(
        source_id,
        "pull",
        ok=True,
        status="pulled",
        message=f"已拉取 {behind} 个提交",
        path=resolved,
        branch=branch,
        before=before,
        after=after,
        ahead=ahead,
        behind=behind,
    )


# --------------------------------------------------------------------------
# 提交
# --------------------------------------------------------------------------
def _classify_status(lines: List[str]) -> Dict[str, int]:
    """把 `git status --porcelain` 的 XY 码归成 added/modified/deleted/renamed/untracked。

    用**真实码**归类而不是让用户猜：提交前他要看到「将删除 75 个文件」这种
    事实，而不是一个笼统的「78 处改动」。
    """
    counts = {"added": 0, "modified": 0, "deleted": 0, "renamed": 0, "untracked": 0}
    for ln in lines:
        if len(ln) < 2:
            continue
        x, y = ln[0], ln[1]
        if x == "?" and y == "?":
            counts["untracked"] += 1
        elif x == "R" or y == "R":
            counts["renamed"] += 1
        elif x == "A" or y == "A":
            counts["added"] += 1
        elif x == "D" or y == "D":
            counts["deleted"] += 1
        else:
            counts["modified"] += 1
    return {k: v for k, v in counts.items() if v}


def commit_status(path: str) -> Dict[str, Any]:
    """只读：列出待提交的改动清单与分组计数。**不写任何东西**。

    提交是唯一不可逆的本地写操作（能 reset，但用户会怕）。所以界面必须先让
    他看到「哪些文件、各是什么性质」，再问要不要提交。
    """
    resolved = _normalize_path(path)
    if not is_git_repo(resolved):
        return {"ok": False, "error": f"不是 git 仓库：{resolved}", "files": [], "counts": {}}
    rc, out, err = _git(resolved, "status", "--porcelain")
    if rc != 0:
        return {"ok": False, "error": f"读取状态失败：{_first_line(err)}", "files": [], "counts": {}}
    lines = [ln for ln in out.splitlines() if ln.strip()]
    files = []
    for ln in lines:
        code, _, name = ln[:2], ln[2:3], ln[3:]
        files.append({"code": code, "path": name})
    return {
        "ok": True,
        "path": resolved,
        "branch": current_branch(resolved),
        "dirty": bool(lines),
        "files": files,
        "counts": _classify_status(lines),
        "total": len(lines),
    }


def commit_source(
    source_id: str,
    path: str,
    *,
    message: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """把工作区全部改动提交为一个 commit（`git add -A` + `git commit`）。

    ## 为什么是「全部」而不是「让用户挑」

    技能目录的改动通常是成套的（一次技能增删会同时改动目录、lock、索引）。
    只提交一部分会让仓库停在**不可用**的中间态：lock 说装了、目录却没有。
    因此这里固定 `add -A`，并在提交前把清单完整交给用户确认。

    ## 三条约束

    1. **空工作区不制造空提交**：没有改动直接返回 ``nothing-to-commit``。
    2. **作者身份缺失时如实报错**：不动 ``git config``（那是在改用户的全局配置），
       只告诉用户缺什么、怎么配。
    3. **提交信息必须非空**：空信息会生成一个无法解释的 commit，直接拒绝。
    """
    resolved = _normalize_path(path)
    if not is_git_repo(resolved):
        return _result(source_id, "commit", message=f"不是 git 仓库：{resolved}")

    status = commit_status(resolved)
    if not status.get("ok"):
        return _result(source_id, "commit", message=status.get("error", "读取状态失败"))
    if not status["dirty"]:
        return _result(
            source_id,
            "commit",
            ok=True,
            status="nothing-to-commit",
            message="没有需要提交的改动",
            path=resolved,
            branch=status["branch"],
        )

    body = (message or "").strip() or f"chore: 同步技能改动（{status['total']} 个文件）"

    if dry_run:
        return _result(
            source_id,
            "commit",
            ok=True,
            status="dry-run",
            dry_run=True,
            message=f"将提交 {status['total']} 个文件",
            path=resolved,
            branch=status["branch"],
            counts=status["counts"],
            files=status["files"][:200],
        )

    # 作者身份：缺了就别硬来，git 会失败但没有可读原因
    rc_id, out_id, _ = _git(resolved, "config", "user.email")
    rc_name, out_name, _ = _git(resolved, "config", "user.name")
    if rc_id != 0 or not out_id.strip() or rc_name != 0 or not out_name.strip():
        return _result(
            source_id,
            "commit",
            status="no-identity",
            message="未配置 git 作者身份，无法提交（请先设置 user.name / user.email）",
            path=resolved,
            branch=status["branch"],
        )

    before = head_commit(resolved)
    rc, _o, err = _git(resolved, "add", "-A", timeout=180)
    if rc != 0:
        return _result(
            source_id,
            "commit",
            status="add-failed",
            message=f"暂存失败：{_first_line(err)}",
            path=resolved,
        )

    rc2, _o2, err2 = _git(resolved, "commit", "-m", body, timeout=180)
    after = head_commit(resolved)
    if rc2 != 0:
        return _result(
            source_id,
            "commit",
            status="commit-failed",
            message=f"提交失败：{_first_line(err2) or f'退出码 {rc2}'}",
            path=resolved,
            branch=status["branch"],
            before=before,
            after=after,
        )

    # 提交后应该「干净」；若还有残留（例如子模块或被忽略规则挡住的项），如实报出
    rc3, out3, _ = _git(resolved, "status", "--porcelain")
    remaining = [ln for ln in out3.splitlines() if ln.strip()] if rc3 == 0 else []
    return _result(
        source_id,
        "commit",
        ok=True,
        status="committed",
        message=f"已提交 {status['total']} 个文件",
        path=resolved,
        branch=status["branch"],
        counts=status["counts"],
        before=before,
        after=after,
        remaining=len(remaining),
    )


# --------------------------------------------------------------------------
# 推送
# --------------------------------------------------------------------------
def push_source(
    source_id: str,
    path: str,
    *,
    remote: str = "origin",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """把本地提交推到远端同名分支。"""
    resolved = _normalize_path(path)
    if not is_git_repo(resolved):
        return _result(source_id, "push", message=f"不是 git 仓库：{resolved}")
    if not remote_url(resolved, remote):
        return _result(
            source_id,
            "push",
            status="no-remote",
            message="未配置远程，无法推送",
            path=resolved,
        )

    branch = current_branch(resolved)
    if not branch or branch == "HEAD":
        return _result(
            source_id,
            "push",
            status="detached",
            message="处于 detached HEAD，拒绝推送（请先切到分支）",
            path=resolved,
        )

    # 先 fetch 一次判断领先/落后，避免盲目 push（也会让结论里的 ahead 数可信）
    _git(resolved, "fetch", "--prune", remote, timeout=180)
    upstream = f"{remote}/{branch}"
    ahead = behind = 0
    rc, counts, _ = _git(resolved, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if rc == 0 and counts.strip():
        parts = counts.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    if ahead == 0:
        return _result(
            source_id,
            "push",
            ok=True,
            status="nothing-to-push",
            message="没有需要推送的提交",
            path=resolved,
            branch=branch,
            ahead=0,
            behind=behind,
        )

    if behind > 0:
        return _result(
            source_id,
            "push",
            status="behind",
            message=f"远端有 {behind} 个本地没有的提交，请先拉取再推送",
            path=resolved,
            branch=branch,
            ahead=ahead,
            behind=behind,
        )

    if dry_run:
        return _result(
            source_id,
            "push",
            ok=True,
            status="dry-run",
            dry_run=True,
            message=f"将推送 {ahead} 个提交到 {remote}/{branch}",
            path=resolved,
            branch=branch,
            ahead=ahead,
        )

    rc2, _o2, err2 = _git(resolved, "push", remote, branch, timeout=300)
    if rc2 != 0:
        return _result(
            source_id,
            "push",
            status="push-failed",
            message=f"推送失败：{_first_line(err2) or f'退出码 {rc2}'}",
            path=resolved,
            branch=branch,
        )

    return _result(
        source_id,
        "push",
        ok=True,
        status="pushed",
        message=f"已推送 {ahead} 个提交到 {remote}/{branch}",
        path=resolved,
        branch=branch,
        ahead=ahead,
        head=head_commit(resolved),
    )


# --------------------------------------------------------------------------
# 批量
# --------------------------------------------------------------------------
def run_on_all(
    action: str,
    *,
    config_path: Optional[str] = None,
    remote: str = "origin",
    mode: str = "ff-only",
    dry_run: bool = False,
    only: Optional[List[str]] = None,
    message: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """对全部已启用源执行同一动作。返回 ``(逐源结果, 汇总)``。"""
    from git_sources import load_sources

    results: List[Dict[str, Any]] = []
    for entry in load_sources(config_path):
        sid = entry.get("id", "")
        if not entry.get("enabled", True):
            continue
        if only and sid not in only:
            continue
        path = entry.get("path", "")
        if action == "check":
            res = check_source(sid, path, remote=remote)
        elif action == "pull":
            res = pull_source(sid, path, remote=remote, mode=mode, dry_run=dry_run)
        elif action == "push":
            res = push_source(sid, path, remote=remote, dry_run=dry_run)
        elif action == "commit":
            res = commit_source(sid, path, message=message, dry_run=dry_run)
        else:
            res = _result(sid, action, message=f"未知动作：{action}")
        results.append(res)

    summary = {
        "total": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
    }
    return results, summary
