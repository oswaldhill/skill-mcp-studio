"""
自动修复器
- 备份原目录（添加 .bak.<timestamp> 后缀）
- 创建指向统一目录的符号链接
- 支持 --dry-run 预览模式
"""

import os
import shutil
from typing import Dict, Any

from tool_registry import normalized_name
from ops_log import ops_log


def fix_path(
    result: Dict[str, Any],
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    修复单个路径（将真实目录或错误 symlink 转换为正确 symlink）

    Args:
        result: check_path() 的返回结果
        dry_run: 是否仅预览（不实际修改）

    Returns:
        dict: {
            "path": 原始路径,
            "status": 原始状态,
            "fixed": 是否修复成功,
            "backup_path": 备份路径（如果有）,
            "dry_run": 是否是预览模式,
            "error": 错误信息（如果有）,
        }
    """
    path = result.get("path", "")
    expanded_path = result.get("expanded_path", os.path.expanduser(path))
    unified_dir = result.get("unified_dir", "~/.skills")
    expanded_unified = os.path.expanduser(unified_dir)
    status = result.get("status", "missing")

    fix_result = {
        "path": path,
        "expanded_path": expanded_path,
        "status": status,
        "fixed": False,
        "backup_path": None,
        "dry_run": dry_run,
        "error": None,
    }

    # Missing paths are created only for clients with positive installation evidence.
    if status not in ("real_dir", "wrong_link", "broken_link", "missing"):
        if status == "skipped":
            note = result.get("note", "")
            fix_result["error"] = f"跳过（工具自有目录）{ '— ' + note if note else ''}"
        else:
            fix_result["error"] = f"无需修复（状态: {status}）"
        return fix_result

    if status == "missing" and not result.get("is_installed", False):
        fix_result["error"] = "客户端未安装，不创建 Skills 路径"
        return fix_result

    # 生成备份路径
    import time
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"{expanded_path}.bak.{timestamp}"
    if status == "real_dir":
        fix_result["backup_path"] = backup_path
    previous_link_target = (
        os.readlink(expanded_path)
        if status in ("wrong_link", "broken_link") and os.path.islink(expanded_path)
        else None
    )

    if dry_run:
        fix_result["fixed"] = True  # 预览模式标记为"将修复"
        return fix_result

    try:
        # 1. 备份原目录
        if os.path.islink(expanded_path):
            # 如果是错误指向的 symlink，直接删除
            os.unlink(expanded_path)
        elif os.path.lexists(expanded_path):
            # 如果是真实目录，重命名为备份
            shutil.move(expanded_path, backup_path)

        # 2. 创建正确的符号链接。
        # 相对路径便于跨机器迁移，但父目录可能本身是 symlink（如 ~/.vscode 指向
        # NAS 卷）；相对链接会在物理目录上解析，若与统一目录跨卷则断链，须退回
        # 绝对路径。
        parent_dir = os.path.dirname(expanded_path)
        if os.path.islink(parent_dir) and not os.path.exists(parent_dir):
            raise OSError(
                f"父目录 {parent_dir} 是失效符号链接（目标磁盘可能未挂载），"
                "无法创建 Skills 链接"
            )
        os.makedirs(parent_dir, exist_ok=True)
        physical_parent = os.path.realpath(os.path.dirname(expanded_path))
        physical_unified = os.path.realpath(expanded_unified)
        try:
            same_volume = os.stat(physical_parent).st_dev == os.stat(physical_unified).st_dev
        except OSError:
            same_volume = False
        rel_path = (
            os.path.relpath(physical_unified, physical_parent)
            if same_volume
            else physical_unified
        )
        os.symlink(rel_path, expanded_path)

        fix_result["fixed"] = True
        fix_result["target"] = rel_path
    except Exception as e:
        fix_result["error"] = str(e)
        if status == "real_dir" and os.path.exists(backup_path) and not os.path.lexists(expanded_path):
            try:
                shutil.move(backup_path, expanded_path)
                fix_result["error"] += "；原目录已自动恢复"
            except Exception as rollback_error:
                fix_result["error"] += f"；自动恢复失败: {rollback_error}"
        elif previous_link_target is not None and not os.path.lexists(expanded_path):
            try:
                os.symlink(previous_link_target, expanded_path)
                fix_result["error"] += "；原符号链接已自动恢复"
            except Exception as rollback_error:
                fix_result["error"] += f"；自动恢复失败: {rollback_error}"

    return fix_result


def fix_all(
    scan_result: Dict[str, Any],
    dry_run: bool = False,
    client: str = None,
) -> Dict[str, Any]:
    """
    修复所有需要修复的路径

    Args:
        scan_result: run_scan() 的返回结果
        dry_run: 是否仅预览（不实际修改）
        client: 仅修复指定客户端（按 tool_name 归一化匹配）；缺省修复全部

    Returns:
        dict: {
            "total": 需要修复的总数,
            "fixed": 成功修复的数量,
            "errors": 失败的数量,
            "details": 每个路径的修复结果列表,
        }
    """
    wanted = normalized_name(client) if client else None
    results = scan_result.get("results", [])
    to_fix = []
    for r in results:
        tool_name = r.get("tool_name", "")
        tool_key = normalized_name(tool_name)
        needs_fix = (
            r.get("status") in ("real_dir", "wrong_link", "broken_link")
            or (r.get("status") == "missing" and r.get("is_installed", False))
        )
        hit = wanted is None or tool_key == wanted
        if needs_fix and hit:
            to_fix.append(r)
        elif wanted is not None and needs_fix and not hit:
            ops_log("fix_skills_skip", wanted=wanted, tool_name=tool_name, normalized=tool_key, status=r.get("status"))
    ops_log("fix_skills_match", wanted=wanted, candidates=len(results), to_fix=len(to_fix))

    details = []
    fixed_count = 0
    error_count = 0

    for r in to_fix:
        fix_result = fix_path(r, dry_run=dry_run)
        details.append(fix_result)
        ops_log(
            "fix_skills_result",
            tool_name=r.get("tool_name"),
            normalized=normalized_name(r.get("tool_name", "")),
            status=r.get("status"),
            path=r.get("path"),
            fixed=fix_result.get("fixed"),
            error=fix_result.get("error"),
            dry_run=dry_run,
        )
        if fix_result["fixed"]:
            fixed_count += 1
        if fix_result.get("error"):
            error_count += 1

    return {
        "total": len(to_fix),
        "fixed": fixed_count,
        "errors": error_count,
        "details": details,
        "dry_run": dry_run,
    }


def print_fix_report(fix_result: Dict[str, Any]) -> None:
    """
    打印修复报告
    """
    total = fix_result.get("total", 0)
    fixed = fix_result.get("fixed", 0)
    errors = fix_result.get("errors", 0)
    dry_run = fix_result.get("dry_run", False)
    details = fix_result.get("details", [])

    print("")
    print("=" * 60)
    if dry_run:
        print("  预览模式：以下操作将被执行（不实际修改）")
    else:
        print("  修复完成报告")
    print("=" * 60)
    print("")

    if total == 0:
        print("  ✅ 无需修复的路径")
        return

    for d in details:
        path = d.get("path", "")
        status = d.get("status", "")
        was_fixed = d.get("fixed", False)
        backup = d.get("backup_path", "")
        error = d.get("error", "")
        target = d.get("target", "")

        if error:
            if "跳过" in error:
                print(f"  ⏭️ {path}")
                print(f"     {error}")
            else:
                print(f"  ❌ {path}")
                print(f"     错误: {error}")
        elif was_fixed:
            if dry_run:
                print(f"  🔧 将修复: {path} （原状态: {status}）")
                print(f"     备份到: {backup}")
                print(f"     将创建相对路径 symlink → {target or '../.skills-manager/skills'}")
            else:
                print(f"  ✅ 已修复: {path}")
                if backup and status == "real_dir":
                    print(f"     备份: {backup}")
                if target:
                    print(f"     相对路径 symlink: → {target}")

    print("")
    print("-" * 60)
    if dry_run:
        print(f"  预览: 将修复 {fixed} 个路径")
    else:
        print(f"  修复: {fixed} 个成功, {errors} 个失败")
    print("=" * 60)
