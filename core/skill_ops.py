"""Skill 级文件操作：备份 / 导出 / 元数据重命名 / 软删除。

这些操作只作用于统一目录（``unified_skills_dir``）内的 **top-level skill 目录**
（与 ``repo_skill_names`` 同源）；嵌套子技能（``scan_skill_nesting`` 命中的深度目录）
仍是只读展示，不接受写操作。

四项操作都遵守同一套约定：

- 接受 ``dry_run``：为真时不落盘，返回将执行的动作；
- 返回结构化 dict（``status`` / ``message`` / ``steps`` / ``backup`` 等），CLI 与 GUI
  各自按需打印或投喂进度；
- skill 名在触碰文件系统前做路径穿越校验，非法时返回 ``error``。

边界（由用户确认）：

- **备份** = 复制该 skill 目录到 ``<unified>/_backup/<name>-<ts>/``；
- **导出** = 打包该 skill 目录为 ``<unified>/_backup/<name>-<ts>.zip``；
- **重命名** = 只改 ``SKILL.md`` frontmatter 的 ``name``/``title`` 与 ``description``
  元数据，**不动目录名、不动客户端 symlink**；
- **删除** = 软删除：先备份到 ``_backup/``，再把目录移入 ``_trash/<name>-<ts>/``。
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _skill_path(unified_dir: str, skill: str) -> str:
    return os.path.join(os.path.expanduser(unified_dir), skill)


def _valid_skill(skill: str) -> bool:
    """Reject empty, dot, and path-traversal names (keep the op confined to top-level)."""
    return bool(skill) and skill not in (".", "..") and "/" not in skill and "\\" not in skill


def _unique_dir(target: str) -> str:
    """Return ``target``; if it already exists, append ``-1``, ``-2``, …"""
    if not os.path.exists(target):
        return target
    base = target
    i = 1
    while os.path.exists(f"{base}-{i}"):
        i += 1
    return f"{base}-{i}"


def _ensure(native_root: str) -> None:
    os.makedirs(native_root, exist_ok=True)


def _error(message: str) -> Dict[str, Any]:
    return {"status": "error", "message": message, "steps": [], "backup": "", "path": ""}


def backup_skill(unified_dir: str, skill: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """Copy a top-level skill dir into ``<unified>/_backup/<name>-<ts>/``."""
    if not _valid_skill(skill):
        return _error(f"非法 skill 名：{skill!r}")
    src = _skill_path(unified_dir, skill)
    if not os.path.isdir(src):
        return _error(f"未找到 skill 目录：{src}")
    bkc_dir = os.path.join(os.path.expanduser(unified_dir), "_backup", f"{skill}-{_now()}")
    if dry_run:
        return {"status": "dry-run", "message": f"将备份 {skill} → {bkc_dir}", "steps": [], "backup": bkc_dir, "path": src}
    try:
        _ensure(os.path.dirname(bkc_dir))
        shutil.copytree(src, bkc_dir)
    except OSError as exc:
        return _error(f"备份失败：{exc}")
    return {"status": "ok", "message": f"已备份 {skill}", "steps": [], "backup": bkc_dir, "path": src}


def export_skill(unified_dir: str, skill: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """Zip a top-level skill dir into ``<unified>/_backup/<name>-<ts>.zip``."""
    if not _valid_skill(skill):
        return _error(f"非法 skill 名：{skill!r}")
    src = _skill_path(unified_dir, skill)
    if not os.path.isdir(src):
        return _error(f"未找到 skill 目录：{src}")
    out_root = os.path.join(os.path.expanduser(unified_dir), "_backup")
    zip_path = _unique_dir(os.path.join(out_root, f"{skill}-{_now()}.zip"))
    if dry_run:
        return {"status": "dry-run", "message": f"将导出 {skill} → {zip_path}", "steps": [], "backup": "", "path": zip_path}
    try:
        _ensure(out_root)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    fp = os.path.join(root, fn)
                    arc = os.path.join(skill, os.path.relpath(fp, src))
                    zf.write(fp, arc)
    except OSError as exc:
        return _error(f"导出失败：{exc}")
    return {"status": "ok", "message": f"已导出 {skill}", "steps": [], "backup": "", "path": zip_path}


_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def rename_skill_meta(
    unified_dir: str,
    skill: str,
    *,
    new_name: Optional[str] = None,
    new_description: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Edit the ``SKILL.md`` frontmatter ``name``/``title`` and ``description`` only.

    The directory name and any client symlinks are left untouched, so the rename is
    safe with respect to mounts. Frontmatter is round-tripped through YAML; the body
    below the closing ``---`` is preserved verbatim.
    """
    if not _valid_skill(skill):
        return _error(f"非法 skill 名：{skill!r}")
    name = (new_name or "").strip()
    desc = new_description.strip() if new_description is not None else None
    if not name and desc is None:
        return _error("重命名需要至少提供 --new-name 或 --new-description")

    md_path = os.path.join(_skill_path(unified_dir, skill), "SKILL.md")
    if not os.path.isfile(md_path):
        return _error(f"未找到 SKILL.md：{md_path}")

    try:
        import yaml
    except Exception:  # pragma: no cover - yaml is a declared dependency
        return _error("缺少 yaml 依赖，无法编辑 frontmatter")

    try:
        with open(md_path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        return _error(f"读取 SKILL.md 失败：{exc}")

    m = _FRONT_RE.match(raw)
    if not m:
        return _error(f"{skill} 的 SKILL.md 没有 frontmatter，无法编辑元数据")

    try:
        data = yaml.safe_load(m.group(1)) or {}
    except Exception as exc:
        return _error(f"frontmatter YAML 解析失败：{exc}")
    if not isinstance(data, dict):
        return _error("frontmatter 不是映射，无法编辑")

    changed: List[str] = []
    if name:
        if "name" in data and data["name"] != name:
            data["name"] = name
            changed.append(f"name → {name}")
        if "title" in data:
            data["title"] = name
            changed.append(f"title → {name}")
        if "name" not in data and "title" not in data:
            data["name"] = name
            changed.append(f"name → {name}")
    if desc is not None:
        if data.get("description") != desc:
            data["description"] = desc
            changed.append("description 已更新")

    if not changed:
        return {"status": "unchanged", "message": "元数据无变化", "steps": [], "backup": "", "path": md_path}

    rendered = yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    new_raw = "---\n" + rendered + "---\n" + raw[m.end():]
    if dry_run:
        return {"status": "dry-run", "message": "；".join(changed), "steps": [], "backup": "", "path": md_path}

    # 写前留一份 SKILL.md 原样备份，防误改。
    bkp = os.path.join(_skill_path(unified_dir, skill), f"SKILL.md.bak-{_now()}")
    try:
        shutil.copyfile(md_path, bkp)
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(new_raw)
    except OSError as exc:
        return _error(f"写入 SKILL.md 失败：{exc}")
    return {"status": "ok", "message": "；".join(changed), "steps": [], "backup": bkp, "path": md_path}


def soft_delete_skill(unified_dir: str, skill: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """Backup then move a top-level skill dir into ``<unified>/_trash/<name>-<ts>/``."""
    if not _valid_skill(skill):
        return _error(f"非法 skill 名：{skill!r}")
    src = _skill_path(unified_dir, skill)
    if not os.path.isdir(src):
        return _error(f"未找到 skill 目录：{src}")

    native_root = os.path.expanduser(unified_dir)
    bkc_dir = os.path.join(native_root, "_backup", f"{skill}-{_now()}")
    ts = _now()
    trash = os.path.join(native_root, "_trash", f"{skill}-{ts}")
    steps = [
        {"status": "ok", "step": "备份", "message": bkc_dir},
        {"status": "ok", "step": "移入回收", "message": trash},
    ]
    if dry_run:
        return {"status": "dry-run", "message": f"将软删除 {skill}", "steps": steps, "backup": bkc_dir, "path": trash}

    try:
        _ensure(os.path.dirname(bkc_dir))
        shutil.copytree(src, bkc_dir)
        _ensure(os.path.dirname(trash))
        shutil.move(src, trash)
    except OSError as exc:
        return _error(f"软删除失败：{exc}")
    return {"status": "ok", "message": f"已软删除 {skill}", "steps": steps, "backup": bkc_dir, "path": trash}