"""工作区清洁度检查（只读侧）—— 由 workspace_cleaner.py 拆分（评审清单 P2-16）。

本模块只做检查/分类/格式化，不写盘、不删除；写操作留在 workspace_cleaner.py。
"""
import os
import subprocess
from typing import Any, Dict, List, Set, Tuple


TEMP_PATTERNS: Set[str] = {
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
    "*.bak",
    "*.tmp",
    "*.temp",
    ".coverage",
    "coverage.xml",
    "*.log",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
}


def _is_temp_file(filepath: str) -> bool:
    """判断是不是临时文件，可以直接删除。"""
    basename = os.path.basename(filepath)
    # Check exact match
    if basename in TEMP_PATTERNS:
        return True
    # Check pattern match
    for pattern in TEMP_PATTERNS:
        if pattern.startswith("*."):
            ext = pattern[1:]  # e.g. ".pyc"
            if basename.endswith(ext):
                return True
    # Check temp directories
    if os.path.isdir(filepath):
        temp_dirs = {p for p in TEMP_PATTERNS if not p.startswith("*")}
        if basename in temp_dirs:
            return True
    return False


def _is_suspicious_file(filepath: str) -> bool:
    """判断是否是需要用户确认的敏感/可疑文件。"""
    basename = os.path.basename(filepath)
    suspicious = {".env", ".env.local", ".env.production", "secret", "token", "credentials",
                  "*.key", "*.pem", "*.p12", "*.pfx", "id_rsa", "id_ed25519"}
    if basename in suspicious or any(basename.endswith(ext) for ext in (".key", ".pem", ".p12", ".pfx")):
        return True
    return False


def _is_large_file(filepath: str, threshold_mb: int = 10) -> bool:
    """判断文件是否过大（可能不适合直接提交）。"""
    try:
        size = os.path.getsize(filepath)
        return size > threshold_mb * 1024 * 1024
    except OSError:
        return False


def check_workspace_cleanliness(workspace_dir: str) -> Dict[str, Any]:
    """
    检查工作区整洁情况。

    Returns:
        dict: {
            "is_git_repo": bool,
            "has_uncommitted": bool,
            "is_clean": bool,
            "untracked": list,
            "modified": list,
            "staged": list,
            "temp_files_found": list,
            "temp_file_count": int,
            "message": str,
        }
    """
    expanded = os.path.expanduser(workspace_dir)
    result = {
        "is_git_repo": False,
        "has_uncommitted": False,
        "is_clean": True,
        "untracked": [],
        "modified": [],
        "staged": [],
        "temp_files_found": [],
        "temp_file_count": 0,
        "message": "",
    }

    git_dir = os.path.join(expanded, ".git")
    if not os.path.isdir(git_dir):
        result["message"] = "⏭️ 非 git 仓库，跳过工作区检查"
        return result

    result["is_git_repo"] = True

    try:
        modified = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=expanded, capture_output=True, text=True, timeout=30
        )
        if modified.stdout.strip():
            result["modified"] = modified.stdout.strip().split("\n")
            result["has_uncommitted"] = True

        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=expanded, capture_output=True, text=True, timeout=30
        )
        if untracked.stdout.strip():
            result["untracked"] = untracked.stdout.strip().split("\n")
            result["has_uncommitted"] = True

        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=expanded, capture_output=True, text=True, timeout=30
        )
        if staged.stdout.strip():
            result["staged"] = staged.stdout.strip().split("\n")
            result["has_uncommitted"] = True

        result["is_clean"] = not result["has_uncommitted"]

    except subprocess.TimeoutExpired:
        result["message"] = "⏰ git status 超时"
        return result
    except Exception as e:
        result["message"] = f"❌ git status 异常: {str(e)}"
        return result

    temp_files = scan_temp_files(expanded)
    result["temp_files_found"] = temp_files
    result["temp_file_count"] = len(temp_files)

    if result["is_clean"] and not temp_files:
        result["message"] = "✅ 工作区整洁，无未提交文件，无临时文件"
    elif result["is_clean"] and temp_files:
        result["message"] = f"✅ 无未提交文件，但有 {len(temp_files)} 个临时文件可清理"
    else:
        parts = []
        if result["modified"]:
            parts.append(f"{len(result['modified'])} 个已修改")
        if result["untracked"]:
            parts.append(f"{len(result['untracked'])} 个未跟踪")
        if result["staged"]:
            parts.append(f"{len(result['staged'])} 个已暂存")
        result["message"] = f"⚠️ 工作区有变更: {'，'.join(parts)}"

    return result


def scan_temp_files(workspace_dir: str) -> List[str]:
    """扫描工作区中的临时文件。"""
    temp_files = []
    expanded = os.path.expanduser(workspace_dir)
    ignore_dirs: Set[str] = {".git", ".gitignore", "node_modules", "venv", ".venv"}

    try:
        for root, dirs, files in os.walk(expanded):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".git")]

            for d in dirs[:]:
                full_d = os.path.join(root, d)
                if _is_temp_file(full_d):
                    temp_files.append(full_d)

            for f in files:
                full_f = os.path.join(root, f)
                if _is_temp_file(full_f):
                    temp_files.append(full_f)
    except PermissionError:
        pass

    # 截断只影响**展示**，不再把 "... (更多省略)" 这个提示串塞进返回值：
    # 调用方用 len() 当计数（temp_file_count），塞进去会让计数恒偏大 1，
    # 而且该字符串会被当成一个路径参与后续渲染。
    return temp_files[:50]


def classify_untracked(workspace_dir: str, untracked: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """
    将未跟踪文件分类：
    - auto_add: 看起来是正常源码 → 自动添加
    - ask: 不确定的，需要用户确认
    - auto_delete: 临时/缓存文件 → 自动删除
    """
    auto_add = []
    ask = []
    auto_delete = []

    for fpath in untracked:
        full = os.path.join(os.path.expanduser(workspace_dir), fpath)

        # 临时文件 → 自动删除
        if _is_temp_file(full):
            auto_delete.append(fpath)
            continue

        # 敏感文件 → 必须问
        if _is_suspicious_file(full):
            ask.append(fpath)
            continue

        # 大文件 → 必须问
        if _is_large_file(full):
            ask.append(fpath)
            continue

        # 正常源码文件 → 自动添加
        ext = os.path.splitext(fpath)[1].lower()
        if ext in {".py", ".md", ".yaml", ".yml", ".json", ".sh", ".txt", ".toml", ".cfg", ".ini",
                   ".rs", ".go", ".ts", ".tsx", ".jsx", ".js", ".java", ".c", ".cpp", ".h", ".hpp",
                   ".rb", ".php", ".swift", ".kt", ".scala", ".lua", ".r", ".sql", ".html", ".css",
                   ".xml", ".csv", ".lock", ".editorconfig", ".prettierrc", ".eslintrc",
                   ".ps1", ".psm1", ".bat", ".cmd", ".makefile", ".mk"}:
            auto_add.append(fpath)
        else:
            # 未知扩展名 → 询问
            ask.append(fpath)

    return auto_add, ask, auto_delete


def format_cleanliness_report(cleanliness: Dict[str, Any]) -> str:
    """将整洁检查结果格式化为可读字符串。"""
    lines = []
    lines.append("-" * 60)

    if not cleanliness.get("is_git_repo"):
        lines.append(f"  {cleanliness.get('message', '')}")
        lines.append("-" * 60)
        return "\n".join(lines)

    lines.append(f"  {'✅' if cleanliness.get('is_clean') else '⚠️'} Git 工作区状态:")
    lines.append("")

    modified = cleanliness.get("modified", [])
    untracked = cleanliness.get("untracked", [])
    staged = cleanliness.get("staged", [])
    temp_count = cleanliness.get("temp_file_count", 0)

    if modified:
        lines.append(f"    已修改 ({len(modified)}):")
        for f in modified[:5]:
            lines.append(f"      📝 {f}")
        if len(modified) > 5:
            lines.append(f"      ... 还有 {len(modified) - 5} 个")

    if untracked:
        lines.append(f"    未跟踪 ({len(untracked)}):")
        for f in untracked[:5]:
            lines.append(f"      ❓ {f}")
        if len(untracked) > 5:
            lines.append(f"      ... 还有 {len(untracked) - 5} 个")

    if staged:
        lines.append(f"    已暂存 ({len(staged)}):")
        for f in staged[:5]:
            lines.append(f"      📦 {f}")
        if len(staged) > 5:
            lines.append(f"      ... 还有 {len(staged) - 5} 个")

    if temp_count > 0:
        lines.append(f"    临时文件: {temp_count} 个")

    if not modified and not untracked and not staged:
        lines.append("    ✅ 无未提交文件")

    if temp_count == 0:
        lines.append("    ✅ 无临时文件")

    lines.append("")
    lines.append(f"  {cleanliness.get('message', '')}")
    lines.append("-" * 60)

    return "\n".join(lines)


def format_clean_result(result: Dict[str, Any]) -> str:
    """将 ensure_workspace_clean 结果格式化输出。"""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("  工作区清理报告")
    lines.append("=" * 60)
    lines.append(f"  工作区: {result.get('workspace_dir', '')}")
    lines.append(f"  初始状态: {'✅ 干净' if result.get('initial_clean') else '⚠️ 有变更'}")
    lines.append("")

    commit = result.get("commit_result")
    if commit:
        lines.append(f"  已修改文件提交: {commit.get('message', '')}")

    unt = result.get("untracked_result")
    if unt:
        lines.append(f"  未跟踪文件处理: {unt.get('message', '')}")

    temp = result.get("temp_clean_result")
    if temp:
        lines.append(f"  临时文件清理: {temp.get('message', '')}")

    lines.append("")
    lines.append(f"  最终状态: {'✅ 干净' if result.get('final_clean') else '⚠️ 仍有遗留'}")
    lines.append(f"  {result.get('message', '')}")

    errors = result.get("errors", [])
    if errors:
        lines.append(f"  ⚠️ 错误 ({len(errors)}):")
        for e in errors[:5]:
            lines.append(f"    - {e}")

    lines.append("=" * 60)
    return "\n".join(lines)
