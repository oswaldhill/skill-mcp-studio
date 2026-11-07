"""Git 技能源管理：把「一个 Git 目录」当作一等公民来登记、发现与检查。

## 为什么需要（2026-11-07 需求）

此前的仓库形态能力（``skill_repo_source``）只认**统一库本身**是 git 仓库这一
种情况。实际使用中技能会来自**多个** Git 目录：有人直接从远端 clone，有人
把已有本地目录加进来——两者在数据模型上是同一件事：**一个 git 工作区**。

本模块负责「登记与观测」，**不负责写入**：

- 登记（add / remove / update）只管 ``data/git_sources.yaml`` 这份配置；
- 发现（``discover_skills``）递归找 ``SKILL.md``；
- 检查（``inspect`` / ``check_all``）**只读**，全部是只读 git 子命令。

真正的网络动作（fetch / pull / merge / push）在 ``git_sync_ops``，两者分开
是为了让「看一眼状态」永远不会意外改动仓库——这是本项目既有的纪律
（``skill_repo_source`` 模块头三条纪律的第 1 条）。

## 技能发现口径

**必须与统一库一致**，否则同一个技能在两个页面会算出两个数：

- **顶层技能**：仓库根下的直接子目录（含 ``SKILL.md``）→ 计入 ``skill_count``；
- **嵌套技能**：更深处含 ``SKILL.md`` 的目录 → 单独列进 ``nested``，
  **不计入** ``skill_count``（与 ``management_snapshot.skill_nesting`` 同口径）。

``.git`` / ``node_modules`` / 以 ``.`` 开头的目录一律跳过。

## 配置位置

``data/git_sources.yaml``（gitignored，同 ``discovered_tools`` / ``market_sources``
模式）：每个人挂的 Git 目录不同，属于本机个人配置，不该进版本库。

文件不存在时返回空列表（不是错误）；文件损坏则抛错并点名文件，绝不静默
当成「没有源」——那会让用户以为自己的配置丢了。
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import yaml

from file_atomic import atomic_write, backup_path

# git 子命令统一超时：relay 远端时多打一点余量，但不能无限等
_GIT_TIMEOUT = 30

# 发现技能时跳过的目录名（前缀 "." 的另外统一跳过）。
# `_trash` 是本项目 `--delete-skill` 的软删除回收站：里面的 SKILL.md 是**已删除**
# 技能的残骸，绝不能算成技能（实测会凭空多出 17 个「嵌套技能」）。
_SKIP_DIRS = frozenset(
    {"node_modules", "__pycache__", "dist", "build", ".venv", "venv", "_trash"}
)

# 源的来源标记：只用于展示「它是怎么来的」，对行为无影响
ORIGINS = ("clone", "local")


# --------------------------------------------------------------------------
# 配置读写
# --------------------------------------------------------------------------
def sources_file() -> str:
    """``data/git_sources.yaml`` 的绝对路径。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "data", "git_sources.yaml"))


def _normalize_path(path: str) -> str:
    """展开 ``~`` 并规范化为绝对路径（不解析 symlink——用户加的就是那个路径）。"""
    if not path:
        return ""
    return os.path.abspath(os.path.expanduser(path))


def load_sources(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取全部 Git 源。文件不存在 → 空列表；损坏 → 抛 ``ValueError``。"""
    target = path or sources_file()
    if not os.path.exists(target):
        return []
    try:
        with open(target, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Git 源配置无法解析：{target}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Git 源配置格式错误（顶层应为映射）：{target}")
    items = raw.get("sources") or []
    if not isinstance(items, list):
        raise ValueError(f"Git 源配置格式错误（sources 应为列表）：{target}")
    return [s for s in items if isinstance(s, dict)]


def save_sources(sources: List[Dict[str, Any]], path: Optional[str] = None) -> str:
    """原子写 + 备份。返回备份路径（无旧文件时为空串）。"""
    target = path or sources_file()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    payload = yaml.safe_dump(
        {"schema_version": 1, "sources": sources},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    backup = ""
    if os.path.exists(target):
        backup = backup_path(target)
    # 0600：配置里可能有私有的远端地址，按本机个人配置文件对待
    atomic_write(target, payload, 0o600)
    return backup


# --------------------------------------------------------------------------
# 登记（纯配置操作，不联网、不动仓库内容）
# --------------------------------------------------------------------------
def _find_by_id(sources: List[Dict[str, Any]], source_id: str) -> Optional[Dict[str, Any]]:
    for item in sources:
        if item.get("id") == source_id:
            return item
    return None


def derive_id(path: str) -> str:
    """由目录名派生稳定 id（``~/.skills-manager/skills`` → ``skills``）。"""
    base = os.path.basename(_normalize_path(path)) or "source"
    return base


def add_source(
    path: str,
    *,
    source_id: str = "",
    label: str = "",
    enabled: bool = True,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """把一个 Git 目录登记为源。

    **不 clone、不 pull**：``path`` 必须已经是本机存在的 git 工作区。
    「从 Git 拉取」与「本地添加」在这一步没有区别——都只是登记一个已有目录。
    （远端 clone 动作见 ``git_sync_ops.clone_source``。）
    """
    resolved = _normalize_path(path)
    if not resolved:
        return {"ok": False, "error": "路径为空"}
    if not os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{resolved}"}
    if not is_git_repo(resolved):
        return {"ok": False, "error": f"不是 git 仓库（缺少 .git）：{resolved}"}

    sid = (source_id or derive_id(resolved)).strip()
    if not sid:
        return {"ok": False, "error": "无法派生 id，请用 --git-source-id 指定"}

    sources = load_sources(config_path)
    existing = _find_by_id(sources, sid)
    if existing and _normalize_path(existing.get("path", "")) == resolved:
        return {"ok": False, "error": f"该目录已登记为源「{sid}」", "id": sid}
    if existing:
        return {
            "ok": False,
            "error": f"id「{sid}」已被另一个目录占用：{existing.get('path')}",
            "id": sid,
        }

    entry: Dict[str, Any] = {
        "id": sid,
        "label": label or sid,
        "path": resolved,
        "enabled": bool(enabled),
    }
    sources.append(entry)
    backup = save_sources(sources, config_path)
    return {"ok": True, "id": sid, "entry": entry, "backup": backup}


def remove_source(source_id: str, *, config_path: Optional[str] = None) -> Dict[str, Any]:
    """从登记表移除。**只移除登记，磁盘目录原样保留**（删目录是破坏性动作，不在此封装）。"""
    sources = load_sources(config_path)
    target = _find_by_id(sources, source_id)
    if not target:
        return {"ok": False, "error": f"未找到源「{source_id}」"}
    remaining = [s for s in sources if s.get("id") != source_id]
    backup = save_sources(remaining, config_path)
    return {"ok": True, "id": source_id, "removed": target, "backup": backup}


def update_source(
    source_id: str,
    *,
    label: Optional[str] = None,
    enabled: Optional[bool] = None,
    path: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """局部更新（只改传入的字段）。"""
    sources = load_sources(config_path)
    target = _find_by_id(sources, source_id)
    if not target:
        return {"ok": False, "error": f"未找到源「{source_id}」"}
    if label is not None:
        target["label"] = label
    if enabled is not None:
        target["enabled"] = bool(enabled)
    if path is not None:
        resolved = _normalize_path(path)
        if not os.path.isdir(resolved):
            return {"ok": False, "error": f"目录不存在：{resolved}"}
        if not is_git_repo(resolved):
            return {"ok": False, "error": f"不是 git 仓库：{resolved}"}
        target["path"] = resolved
    backup = save_sources(sources, config_path)
    return {"ok": True, "id": source_id, "entry": target, "backup": backup}


# --------------------------------------------------------------------------
# git 只读探测
# --------------------------------------------------------------------------
def _git(cwd: str, *args: str, timeout: int = _GIT_TIMEOUT) -> Tuple[int, str, str]:
    """跑一条 git 子命令，返回 ``(退出码, stdout, stderr)``。永不抛异常。"""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "git 未安装（PATH 中找不到 git）"
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)} 超时（{timeout}s）"
    except Exception as exc:  # noqa: BLE001
        return 1, "", f"git {' '.join(args)} 失败: {exc}"


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0]


def is_git_repo(path: str) -> bool:
    """``path`` 是否为 git 工作区根（只看元数据，不联网）。"""
    if not path or not os.path.isdir(path):
        return False
    rc, out, _ = _git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


def current_branch(path: str) -> str:
    rc, out, _ = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if rc == 0 else ""


def remote_url(path: str, remote: str = "origin") -> str:
    rc, out, _ = _git(path, "remote", "get-url", remote)
    return out.strip() if rc == 0 else ""


def head_commit(path: str, short: bool = True) -> str:
    args = ["rev-parse"]
    if short:
        args.append("--short")
    args.append("HEAD")
    rc, out, _ = _git(path, *args)
    return out.strip() if rc == 0 else ""


# --------------------------------------------------------------------------
# 技能发现（口径与统一库一致）
# --------------------------------------------------------------------------
def discover_skills(path: str) -> Dict[str, Any]:
    """递归发现技能，返回 ``{"top_level": [...], "nested": {...}}``。

    口径与 ``management_snapshot`` 完全一致：
    顶层子目录含 ``SKILL.md`` 计入 ``top_level``；更深处的直接进 ``nested``，
    以顶层目录名为键（``{"apple": ["apple/apple-notes", ...]}``）。
    """
    root = _normalize_path(path)
    result: Dict[str, Any] = {"top_level": [], "nested": {}}
    if not os.path.isdir(root):
        return result

    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return result

    top_names = []
    for name in entries:
        if name.startswith(".") or name in _SKIP_DIRS:
            continue
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        if os.path.isfile(os.path.join(full, "SKILL.md")):
            result["top_level"].append(name)
        top_names.append(name)

    for top in top_names:
        if top in result["top_level"]:
            continue  # 顶层已登记，不再往下找（避免重复计入）
        found: List[str] = []
        base = os.path.join(root, top)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [
                d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS
            ]
            if "SKILL.md" in filenames:
                rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
                found.append(rel)
        if found:
            result["nested"][top] = sorted(found)

    return result


# --------------------------------------------------------------------------
# 检查（只读；不发网络请求）
# --------------------------------------------------------------------------
def inspect(path: str, *, count_skills: bool = True) -> Dict[str, Any]:
    """只读检查单个目录的 git 状态。**绝不 fetch / pull**。"""
    resolved = _normalize_path(path)
    out: Dict[str, Any] = {
        "path": resolved,
        "exists": os.path.isdir(resolved),
        "is_repo": False,
        "branch": "",
        "head": "",
        "remote": "",
        "dirty": False,
        "dirty_files": 0,
        "ahead": 0,
        "behind": 0,
        "upstream": "",
        "skill_count": 0,
        "nested_count": 0,
        "error": "",
    }
    if not out["exists"]:
        out["error"] = "目录不存在"
        return out
    if not is_git_repo(resolved):
        out["error"] = "不是 git 仓库"
        return out

    out["is_repo"] = True
    out["branch"] = current_branch(resolved)
    out["head"] = head_commit(resolved)
    out["remote"] = remote_url(resolved)

    rc, status_out, _ = _git(resolved, "status", "--porcelain")
    if rc == 0:
        lines = [ln for ln in status_out.splitlines() if ln.strip()]
        out["dirty_files"] = len(lines)
        out["dirty"] = bool(lines)

    # 上游比较：只在已存在 upstream ref 时比较，**不触发 fetch**
    rc, up, _ = _git(resolved, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if rc == 0 and up.strip():
        out["upstream"] = up.strip()
        rc2, counts, _ = _git(resolved, "rev-list", "--left-right", "--count", f"HEAD...{up.strip()}")
        if rc2 == 0 and counts.strip():
            parts = counts.split()
            if len(parts) == 2:
                out["ahead"], out["behind"] = int(parts[0]), int(parts[1])

    if count_skills:
        found = discover_skills(resolved)
        out["skill_count"] = len(found["top_level"])
        out["nested_count"] = sum(len(v) for v in found["nested"].values())

    return out


def check_all(*, config_path: Optional[str] = None, include_disabled: bool = False) -> List[Dict[str, Any]]:
    """逐个检查已登记的源。禁用源默认跳过（仍可通过 include_disabled 查看）。"""
    results: List[Dict[str, Any]] = []
    for entry in load_sources(config_path):
        if not include_disabled and not entry.get("enabled", True):
            results.append(
                {
                    "id": entry.get("id", ""),
                    "label": entry.get("label", ""),
                    "path": entry.get("path", ""),
                    "enabled": False,
                    "skipped": True,
                    "error": "",
                }
            )
            continue
        info = inspect(entry.get("path", ""))
        info["id"] = entry.get("id", "")
        info["label"] = entry.get("label", "") or entry.get("id", "")
        info["enabled"] = bool(entry.get("enabled", True))
        info["skipped"] = False
        results.append(info)
    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """给概览用的汇总计数。"""
    total = len(results)
    enabled = sum(1 for r in results if r.get("enabled") and not r.get("skipped"))
    ok = sum(1 for r in results if r.get("is_repo"))
    dirty = sum(1 for r in results if r.get("dirty"))
    behind = sum(1 for r in results if (r.get("behind") or 0) > 0)
    ahead = sum(1 for r in results if (r.get("ahead") or 0) > 0)
    skills = sum(int(r.get("skill_count") or 0) for r in results if not r.get("skipped"))
    failed = sum(1 for r in results if r.get("error"))
    return {
        "total": total,
        "enabled": enabled,
        "ok": ok,
        "failed": failed,
        "dirty": dirty,
        "behind": behind,
        "ahead": ahead,
        "skills": skills,
    }
