"""
Git 同步模块
功能：
1. 验证主 skills 目录路径是否为允许的路径（~/.skills 或 ~/.skills-manager/skills）
2. 检查主 skills 目录是否为 git 仓库，若是则在扫描前执行 git pull 保持同步
"""

import os
import subprocess
from typing import Dict, Any, Optional


# 允许的主 skills 目录路径列表
ALLOWED_UNIFIED_DIRS = [
    "~/.skills",
    "~/.skills-manager/skills",
]


def validate_unified_dir(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证 unified_skills_dir 是否为允许的路径。

    Args:
        config: 配置字典

    Returns:
        dict: {
            "valid": bool,          # 是否允许
            "current": str,         # 当前配置值
            "recommended": str,     # 推荐值
            "needs_fix": bool,      # 是否需要修复
            "message": str,         # 状态描述
        }
    """
    unified_dir = config.get("unified_skills_dir", "")
    expanded = os.path.expanduser(unified_dir)
    normalized = os.path.normpath(expanded)

    # 检查是否在允许列表中
    allowed_expanded = [
        os.path.normpath(os.path.expanduser(p))
        for p in ALLOWED_UNIFIED_DIRS
    ]

    recommended = os.path.normpath(os.path.expanduser("~/.skills-manager/skills"))

    result = {
        "current": unified_dir,
        "expanded": normalized,
        "recommended": "~/.skills-manager/skills",
        "recommended_expanded": recommended,
        "valid": False,
        "needs_fix": False,
        "message": "",
    }

    if normalized in allowed_expanded:
        result["valid"] = True
        result["message"] = f"✅ 主 skills 目录路径正确: {unified_dir}"
        return result

    # 不是允许的路径
    if os.path.exists(normalized):
        result["needs_fix"] = True
        result["message"] = (
            f"⚠️ 主 skills 目录路径不在允许列表中: {unified_dir}\n"
            f"   允许的路径: {', '.join(ALLOWED_UNIFIED_DIRS)}\n"
            f"   推荐修复到: ~/.skills-manager/skills"
        )
    else:
        result["needs_fix"] = True
        result["message"] = (
            f"❌ 主 skills 目录路径不存在或不允许: {unified_dir}\n"
            f"   推荐修复到: ~/.skills-manager/skills"
        )

    return result


def fix_unified_dir(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    修复 unified_skills_dir 配置，指向 ~/.skills-manager/skills。

    Args:
        config_path: 配置文件路径

    Returns:
        dict: {"fixed": bool, "message": str}
    """
    import yaml

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "config.yaml"
        )
    config_path = os.path.normpath(config_path)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        old_dir = config.get("unified_skills_dir", "")
        config["unified_skills_dir"] = "~/.skills-manager/skills"

        # 备份原配置文件
        import shutil
        import time
        backup_path = f"{config_path}.bak.{time.strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(config_path, backup_path)

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return {
            "fixed": True,
            "old_dir": old_dir,
            "new_dir": "~/.skills-manager/skills",
            "backup_path": backup_path,
            "message": f"✅ 已修复: {old_dir} → ~/.skills-manager/skills\n   备份: {backup_path}",
        }
    except Exception as e:
        return {
            "fixed": False,
            "message": f"❌ 修复失败: {str(e)}",
        }


def is_git_repo(path: str) -> bool:
    """
    检查指定路径是否为 git 仓库。

    Args:
        path: 目录路径（已展开）

    Returns:
        bool
    """
    git_dir = os.path.join(path, ".git")
    return os.path.isdir(git_dir)


def git_pull_if_needed(path: str, auto: bool = False) -> Dict[str, Any]:
    """
    如果路径是 git 仓库且有远程更新，执行 git pull。

    Args:
        path: skills 目录路径（已展开）
        auto: 是否自动执行 pull（True=直接pull, False=先检查更新）

    Returns:
        dict: {
            "is_git_repo": bool,
            "has_updates": bool,
            "pulled": bool,
            "message": str,
            "before_commit": str,
            "after_commit": str,
            "changed_files": list,
        }
    """
    result = {
        "is_git_repo": False,
        "has_updates": False,
        "pulled": False,
        "message": "",
        "before_commit": "",
        "after_commit": "",
        "changed_files": [],
    }

    if not is_git_repo(path):
        result["message"] = "⏭️ 非 git 仓库，跳过同步"
        result["is_git_repo"] = False
        return result

    result["is_git_repo"] = True

    try:
        # 获取当前 commit
        before = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=path, capture_output=True, text=True, timeout=30
        )
        result["before_commit"] = before.stdout.strip()

        # 获取远程仓库信息
        remote_check = subprocess.run(
            ["git", "remote", "-v"],
            cwd=path, capture_output=True, text=True, timeout=30
        )
        has_remote = bool(remote_check.stdout.strip())

        if not has_remote:
            result["message"] = "⏭️ git 仓库无远程配置，跳过同步"
            return result

        # 检查是否有更新
        fetch_result = subprocess.run(
            ["git", "fetch", "--dry-run"],
            cwd=path, capture_output=True, text=True, timeout=60
        )

        if fetch_result.stdout.strip() or fetch_result.stderr.strip():
            result["has_updates"] = True

            if auto:
                # 直接 pull
                pull = subprocess.run(
                    ["git", "pull"],
                    cwd=path, capture_output=True, text=True, timeout=120
                )
                if pull.returncode == 0:
                    # 获取 pull 后的 commit
                    after = subprocess.run(
                        ["git", "rev-parse", "--short", "HEAD"],
                        cwd=path, capture_output=True, text=True, timeout=30
                    )
                    result["after_commit"] = after.stdout.strip()
                    result["pulled"] = True

                    # 获取变更文件列表
                    log = subprocess.run(
                        ["git", "log", f"{result['before_commit']}..HEAD", "--oneline", "--stat"],
                        cwd=path, capture_output=True, text=True, timeout=30
                    )
                    result["changed_files"] = log.stdout.strip().split("\n") if log.stdout.strip() else []

                    result["message"] = (
                        f"✅ git pull 成功\n"
                        f"   变更: {result['before_commit']} → {result['after_commit']}"
                    )
                else:
                    result["message"] = f"❌ git pull 失败:\n   {pull.stderr.strip()}"
            else:
                # 仅报告有更新，不执行 pull
                result["message"] = "📡 检测到远程更新，请执行 --sync 参数同步"
        else:
            result["message"] = "✅ 已是最新，无需同步"

    except subprocess.TimeoutExpired:
        result["message"] = "⏰ git 操作超时"
    except Exception as e:
        result["message"] = f"❌ git 操作异常: {str(e)}"

    return result


def git_status(path: str) -> Dict[str, Any]:
    """
    检查 git 仓库是否有未提交的变更。

    Args:
        path: 仓库路径

    Returns:
        dict: {
            "has_changes": bool,
            "is_clean": bool,
            "untracked": list,
            "modified": list,
            "staged": list,
        }
    """
    result = {
        "has_changes": False,
        "is_clean": True,
        "untracked": [],
        "modified": [],
        "staged": [],
    }

    if not is_git_repo(path):
        return result

    try:
        # 未暂存的变更
        modified = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=path, capture_output=True, text=True, timeout=30
        )
        if modified.stdout.strip():
            result["modified"] = modified.stdout.strip().split("\n")
            result["has_changes"] = True

        # 未跟踪的文件
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=path, capture_output=True, text=True, timeout=30
        )
        if untracked.stdout.strip():
            result["untracked"] = untracked.stdout.strip().split("\n")
            result["has_changes"] = True

        # 已暂存
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=path, capture_output=True, text=True, timeout=30
        )
        if staged.stdout.strip():
            result["staged"] = staged.stdout.strip().split("\n")
            result["has_changes"] = True

        result["is_clean"] = not result["has_changes"]

    except Exception:
        pass

    return result
