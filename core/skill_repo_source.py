"""仓库形态技能源（repo-form）：统一库本身是 git 仓库时的更新判定。

**为什么需要这个模块**（2026-10-25 实测）：本机 192 个技能里只有 39 个在
`~/.agents/.skill-lock.json` 有来源登记，其余 153 个永远查不到更新——它们不
属于任何「单技能来源」，而是**整仓库形态**：统一库目录本身就是一个 git 工作
区（实测 origin `my-agent-skills`、branch `master`）。这类技能的「上游」是
该仓库的远端分支，判定单位也因此不是技能包 version，而是「本地 HEAD 与
origin/<branch> 之间，该技能目录有没有差异」。此前它们全部落进 `unknown`，
用户看到的是一个巨大的「无法检测」桶——那不是结论，是缺口。

**三条纪律**（沿用 v0.31.2 的计数口径与 git_status 的教训）：

1. **只读**：全部是 git 只读子命令（`rev-parse` / `diff` / `status` / `log`），
   绝不 `pull` / `fetch` / `checkout`。升级动作仍只有 `--sync` 与市场升级。
2. **不发网络请求**：基准取本地**已有**的 `origin/<branch>` ref（由 `--sync`
   或用户手动 fetch 更新），并把基准提交时间写进 note 与
   `upstream_time`——否则「很久没 fetch」会被读成「远端没变」，那是把查不成
   当成了没问题。
3. **查不成绝不当成没问题**：git 不存在、目录不是仓库、detached HEAD、
   上游 ref 缺失、任何子命令非 0，一律回 `ok=False` + `error`，由调用方落成
   `unknown`（绝不静默算 `current`）。
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Iterable, Optional, Set, Tuple

_GIT_TIMEOUT = 20

# 本模块产出的状态：仓库形态判定出的「上游有新提交」，与单技能来源的
# outdated 分开命名——两者的升级方式完全不同（一个走仓库同步，一个走
# npx 重装），混成一个状态会让「一键升级」去重装一个仓库形态的技能并失败。
REPO_OUTDATED = "repo_outdated"


def _git(cwd: str, *args: str) -> Tuple[int, str, str]:
    """跑一条只读 git 子命令，返回 (退出码, stdout, stderr)。不抛异常。"""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "git 未安装（PATH 中找不到 git）"
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)} 超时（{_GIT_TIMEOUT}s）"
    except Exception as exc:  # noqa: BLE001 —— 任何异常都必须转成 error，不许冒泡
        return 1, "", f"git {' '.join(args)} 失败: {exc}"


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0]


def is_repo(path: str) -> bool:
    """``path`` 是否为 git 工作区（只看元数据，不联网）。"""
    rc, out, _err = _git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


def _resolve_rename(line: str) -> str:
    """把 git 的重命名行还原成「新路径」。

    两种形态都要处理：
    - 整路径重命名：``old/path => new/path``
    - 紧凑形态（同目录内改文件名）：``dir/{old.md => new.md}``
      此时目录前缀在 ``{`` **之前**，直接按 ``=>`` 切会把目录丢掉，
      于是把技能名判错（丢掉 ``alpha/`` 只剩 ``new.md``）。
    """
    if "{" in line and "}" in line:
        prefix, rest = line.split("{", 1)
        inside, suffix = rest.split("}", 1)
        new_part = inside.split("=>")[-1].strip()
        return f"{prefix}{new_part}{suffix}"
    return line.split("=>")[-1].strip()


def _top_dirs_from_diff(paths: Iterable[str], known: Set[str]) -> Set[str]:
    """把 diff 里的文件路径收敛成技能目录名。

    只认**已知技能目录**：仓库根还有 README.md / LICENSE / _core / _trash 等
    非技能条目，若不收口会把它们算成「技能待同步」，凭空多出条目——这正是
    v0.31.1「列表 2 个、弹框 4 个」那类矛盾的来源。
    """
    hit: Set[str] = set()
    for raw in paths:
        line = raw.strip()
        if not line:
            continue
        if "=>" in line:
            line = _resolve_rename(line)
        top = line.split("/")[0]
        if top in known:
            hit.add(top)
    return hit


def snapshot(unified_dir: str, known_skills: Iterable[str]) -> Dict[str, Any]:
    """采集仓库形态的更新判定快照（只读、不联网）。

    Args:
        unified_dir: 统一库目录（通常是 `paths.skills_dir()`）。
        known_skills: 当前磁盘上的技能名集合，用于把 diff 路径收敛到技能。

    Returns:
        dict: {
            "ok": bool,            # 是否成功判定（False 时调用方必须落 unknown）
            "branch": str | None,  # 当前分支
            "upstream": str | None,# 比对基准，如 origin/master
            "upstream_time": str | None,  # 基准提交时间（ISO8601），写进 note
            "changed": set[str],   # 上游有新提交的技能名
            "dirty": set[str],     # 本地有未提交修改的技能名
            "error": str,          # ok=False 时的原因
        }
    """
    known = set(known_skills)
    empty: Dict[str, Any] = {
        "ok": False,
        "branch": None,
        "upstream": None,
        "upstream_time": None,
        "changed": set(),
        "dirty": set(),
        "error": "",
    }

    if not is_repo(unified_dir):
        empty["error"] = "统一库不是 git 工作区，不适用仓库形态判定"
        return empty

    rc, out, err = _git(unified_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        empty["error"] = f"读取当前分支失败: {_first_line(err) or rc}"
        return empty
    branch = out.strip()
    if not branch or branch == "HEAD":
        empty["error"] = "工作区处于 detached HEAD，无法确定比对分支"
        return empty

    upstream = f"origin/{branch}"
    rc, out, err = _git(unified_dir, "rev-parse", "--verify", "--quiet", upstream)
    if rc != 0 or not out.strip():
        empty["branch"] = branch
        empty["error"] = f"缺少比对基准 {upstream}（尚未 fetch 过该分支）"
        return empty

    rc, out, err = _git(unified_dir, "log", "-1", "--format=%cI", upstream)
    upstream_time = out.strip() if rc == 0 and out.strip() else None

    # 上游有、本地 HEAD 没有的变更 —— 即"该技能可以同步下来"
    rc, out, err = _git(unified_dir, "diff", "--name-only", "HEAD", upstream)
    if rc != 0:
        empty["branch"] = branch
        empty["upstream"] = upstream
        empty["error"] = f"对比 {upstream} 失败: {_first_line(err) or rc}"
        return empty
    changed = _top_dirs_from_diff(out.splitlines(), known)

    # 本地未提交修改：这些技能同步会冲突，不能笼统说"可同步"
    rc, out, err = _git(unified_dir, "status", "--porcelain")
    dirty_paths = []
    if rc == 0:
        for line in out.splitlines():
            if len(line) > 3:
                dirty_paths.append(line[3:])
    dirty = _top_dirs_from_diff(dirty_paths, known)

    return {
        "ok": True,
        "branch": branch,
        "upstream": upstream,
        "upstream_time": upstream_time,
        "changed": changed,
        "dirty": dirty,
        "error": "",
    }


def classify(name: str, snap: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    """把一个技能判成 (state, note, remote_time)。

    state 取值：`repo_outdated` / `current` / `unknown`。注意本函数**不产出**
    单技能来源那套 `outdated`——调用方按来源形态分流，两种 outdated 的升级
    通道不同。
    """
    error = snap.get("error") or ""
    if not snap.get("ok"):
        return "unknown", f"仓库形态来源：{error or '无法判定'}", None

    upstream = snap.get("upstream") or "上游分支"
    branch = snap.get("branch") or "?"
    base = snap.get("upstream_time")
    base_note = f"，基准 {base}" if base else "，基准提交时间未知"

    if name in (snap.get("dirty") or set()):
        return (
            "unknown",
            "仓库形态来源：本地有未提交修改，同步前需先提交或还原",
            base,
        )
    if name in (snap.get("changed") or set()):
        return (
            REPO_OUTDATED,
            f"仓库形态来源（{branch}）：{upstream} 上该技能目录有新提交"
            f"{base_note}；请在仓库里同步，不走市场升级",
            base,
        )
    return (
        "current",
        f"仓库形态来源（{branch}）：与 {upstream} 基准一致{base_note}",
        base,
    )
