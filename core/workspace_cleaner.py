"""工作区清洁（写侧）—— 由 workspace_cleaner.py 自身拆分（评审清单 P2-16）。

只读的检查/分类/格式化在 workspace_cleaner_read.py；此处保留写操作，
并把只读侧的公开名字再导出，使 `workspace_cleaner.<name>` 与拆分前一致。
"""
import os
import shutil
import subprocess
from typing import Any, Dict, List

# 再导出：tests/test_highrisk_modules.py 与 scan.py 通过本模块访问这些名字。
# `as` 同名字写法同时避免被 ruff F401 当未使用导入删除（见清单 P1-11）。
from workspace_cleaner_read import TEMP_PATTERNS as TEMP_PATTERNS
from workspace_cleaner_read import _is_temp_file as _is_temp_file
from workspace_cleaner_read import _is_suspicious_file as _is_suspicious_file
from workspace_cleaner_read import _is_large_file as _is_large_file
from workspace_cleaner_read import check_workspace_cleanliness as check_workspace_cleanliness
from workspace_cleaner_read import scan_temp_files as scan_temp_files
from workspace_cleaner_read import classify_untracked as classify_untracked
from workspace_cleaner_read import format_cleanliness_report as format_cleanliness_report
from workspace_cleaner_read import format_clean_result as format_clean_result


def _ask_user(prompt: str, default: str = "y") -> str:
    """交互式询问用户，支持 y/n/s/k/d。返回小写字母。"""
    choices = {"y": "是/添加/提交", "n": "否/跳过", "s": "跳过此项", "k": "保留但暂不处理", "d": "删除"}
    choice_str = "/".join(f"[{k}]{v}" for k, v in choices.items())
    
    try:
        raw = input(f"  {prompt} ({choice_str}) [{default}]: ").strip().lower()
        return raw if raw in choices else default
    except (EOFError, KeyboardInterrupt):
        return default


def interactive_commit_untracked(workspace_dir: str, untracked: List[str],
                                  interactive: bool = True,
                                  commit_msg: str = "") -> Dict[str, Any]:
    """
    对未跟踪文件进行交互式处理（添加/提交/删除/跳过）。

    Returns:
        dict: {
            "added": list, "deleted": list, "skipped": list,
            "committed": bool, "message": str,
        }
    """
    expanded = os.path.expanduser(workspace_dir)
    result = {"added": [], "deleted": [], "skipped": [], "committed": False, "message": ""}

    auto_add, ask, auto_delete = classify_untracked(expanded, untracked)

    # 自动删除
    for fpath in auto_delete:
        full = os.path.join(expanded, fpath)
        try:
            if os.path.isfile(full):
                os.remove(full)
            elif os.path.isdir(full):
                shutil.rmtree(full)
            result["deleted"].append(fpath)
        except Exception:
            ask.append(fpath)  # 删除失败，改为询问

    # 自动添加
    for fpath in auto_add:
        try:
            proc = subprocess.run(
                ["git", "add", fpath], cwd=expanded, capture_output=True, timeout=15
            )
            if proc.returncode != 0:
                # git 非 0 退出（被 .gitignore 忽略、路径失效…）时必须不计入 added：
                # 否则汇总文案与「是否触发二次 commit」都建立在假列表上。
                result["skipped"].append(fpath)
                continue
            result["added"].append(fpath)
        except Exception:
            ask.append(fpath)

    # 交互式确认
    if ask and interactive:
        print(f"\n  ❓ 以下 {len(ask)} 个未跟踪文件需要你确认:")
        for fpath in ask:
            full = os.path.join(expanded, fpath)
            extra = ""
            if _is_suspicious_file(full):
                extra = " ⚠️ 敏感文件"
            elif _is_large_file(full):
                try:
                    size_mb = os.path.getsize(full) / (1024 * 1024)
                    extra = f" ⚠️ 大文件 ({size_mb:.1f}MB)"
                except OSError:
                    extra = " ⚠️ 无法读取大小"
            print(f"      {fpath}{extra}")

        print("")
        for fpath in ask[:]:
            full = os.path.join(expanded, fpath)
            answer = _ask_user(f"如何处理 \"{fpath}\"？")
            if answer == "y":
                try:
                    proc = subprocess.run(
                        ["git", "add", fpath], cwd=expanded, capture_output=True, timeout=15
                    )
                    if proc.returncode != 0:
                        result["skipped"].append(fpath)
                    else:
                        result["added"].append(fpath)
                except Exception:
                    result["skipped"].append(fpath)
            elif answer == "d":
                try:
                    if os.path.isfile(full):
                        os.remove(full)
                    elif os.path.isdir(full):
                        shutil.rmtree(full)
                    result["deleted"].append(fpath)
                except Exception as e:
                    result["skipped"].append(fpath)
                    print(f"    ❌ 删除失败: {e}")
            else:
                result["skipped"].append(fpath)
    elif ask and not interactive:
        # 非交互模式：跳过所有不确定文件
        result["skipped"].extend(ask)

    # 汇总
    parts = []
    if result["added"]:
        parts.append(f"{len(result['added'])} 个添加")
    if result["deleted"]:
        parts.append(f"{len(result['deleted'])} 个删除")
    if result["skipped"]:
        parts.append(f"{len(result['skipped'])} 个跳过")
    result["message"] = f"未跟踪文件处理: {'，'.join(parts)}" if parts else "无未跟踪文件需处理"

    return result


def commit_all_modified(workspace_dir: str, modified: List[str], staged: List[str],
                         interactive: bool = True, commit_msg: str = "") -> Dict[str, Any]:
    """
    提交已修改和已暂存的文件（这些是意向明确的变更）。

    Returns:
        dict: {"committed": bool, "hash": str, "count": int, "message": str}
    """
    expanded = os.path.expanduser(workspace_dir)
    result = {"committed": False, "hash": "", "count": 0, "message": ""}

    all_modified = modified + staged
    if not all_modified:
        result["message"] = "无已修改/已暂存文件需提交"
        return result

    result["count"] = len(all_modified)

    print(f"\n  📝 将提交 {len(all_modified)} 个已修改/已暂存文件:")
    for f in all_modified[:10]:
        print(f"      {f}")
    if len(all_modified) > 10:
        print(f"      ... 还有 {len(all_modified) - 10} 个")

    if interactive:
        answer = _ask_user("是否提交以上文件？")
        if answer != "y":
            result["message"] = "用户取消提交"
            return result

    # stage modified/staged files explicitly + commit
    try:
        # Only stage the specific files that were identified as modified/staged
        files_to_stage = list(set(modified + staged))  # deduplicate
        if files_to_stage:
            subprocess.run(
                ["git", "add"] + files_to_stage,
                cwd=expanded, capture_output=True, timeout=15
            )

        msg = commit_msg if commit_msg else "chore: auto-commit workspace changes"

        proc = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=expanded, capture_output=True, text=True, timeout=30
        )

        if proc.returncode == 0:
            # 获取 commit hash
            hash_proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=expanded, capture_output=True, text=True, timeout=10
            )
            result["hash"] = hash_proc.stdout.strip()
            result["committed"] = True
            result["message"] = f"✅ 已提交 {len(all_modified)} 个文件 → {result['hash']}"
        else:
            result["message"] = f"❌ 提交失败: {proc.stderr.strip()}"
    except Exception as e:
        result["message"] = f"❌ 提交异常: {str(e)}"

    return result


def ensure_workspace_clean(workspace_dir: str, interactive: bool = True,
                            commit_msg: str = "", push: bool = False) -> Dict[str, Any]:
    """
    一站式工作区清理流程：
    1. 扫描未提交文件
    2. 提交已修改/已暂存文件
    3. 交互式处理未跟踪文件
    4. 清理临时文件
    5. 验证最终状态

    Returns:
        dict: 汇总所有处理结果
    """
    expanded = os.path.expanduser(workspace_dir)
    result = {
        "workspace_dir": expanded,
        "initial_clean": False,
        "final_clean": False,
        "commit_result": None,
        "untracked_result": None,
        "temp_clean_result": None,
        "message": "",
        "errors": [],
    }

    # Step 1: 初始扫描
    cleanliness = check_workspace_cleanliness(expanded)
    if not cleanliness["is_git_repo"]:
        result["message"] = "⏭️ 非 git 仓库，跳过清理"
        return result

    result["initial_clean"] = cleanliness["is_clean"]

    if cleanliness["is_clean"] and cleanliness["temp_file_count"] == 0:
        result["message"] = "✅ 工作区初始即为干净状态"
        result["final_clean"] = True
        return result

    print(f"\n  📋 初始状态: {cleanliness['message']}")

    # Step 2: 提交已修改/已暂存文件
    if cleanliness["modified"] or cleanliness["staged"]:
        result["commit_result"] = commit_all_modified(
            expanded,
            cleanliness["modified"],
            cleanliness["staged"],
            interactive=interactive,
            commit_msg=commit_msg,
        )
        print(f"\n  {result['commit_result']['message']}")

        # 如果选择推送
        if push and result["commit_result"]["committed"]:
            try:
                push_proc = subprocess.run(
                    ["git", "push"],
                    cwd=expanded, capture_output=True, text=True, timeout=30
                )
                if push_proc.returncode == 0:
                    print("  📤 已推送到远程")
                else:
                    print(f"  ⚠️ 推送失败: {push_proc.stderr.strip()}")
                    result["errors"].append(f"push: {push_proc.stderr.strip()[:100]}")
            except Exception as e:
                result["errors"].append(f"push: {str(e)}")

    # Step 3: 交互式处理未跟踪文件
    if cleanliness["untracked"]:
        result["untracked_result"] = interactive_commit_untracked(
            expanded,
            cleanliness["untracked"],
            interactive=interactive,
            commit_msg=commit_msg,
        )
        print(f"\n  {result['untracked_result']['message']}")

        # 如果有新添加的文件，再做一次 commit
        if result["untracked_result"]["added"]:
            try:
                msg = commit_msg if commit_msg else "chore: add new workspace files"
                proc = subprocess.run(
                    ["git", "commit", "-m", msg],
                    cwd=expanded, capture_output=True, text=True, timeout=30
                )
                if proc.returncode != 0:
                    # 不能无条件打印「已提交」：pre-commit hook 拒绝、user.email 未配、
                    # 索引锁都会走这里。同文件的 commit_all_modified 是检查了 returncode
                    # 的，此处口径不一致 —— 用户会以为改动已入库。
                    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
                    first = lines[0] if lines else f"git exit={proc.returncode}"
                    result["errors"].append(f"commit untracked 失败: {first}")
                    print(f"  ✗ 提交未跟踪文件失败（git exit={proc.returncode}）：{first}")
                else:
                    print("  ✅ 已提交新添加的未跟踪文件")
            except Exception as e:
                result["errors"].append(f"commit untracked: {str(e)}")

    # Step 4: 清理临时文件
    temp_count_before = cleanliness["temp_file_count"]
    if temp_count_before > 0:
        result["temp_clean_result"] = clean_temp_files(expanded, dry_run=False)
        print(f"\n  {result['temp_clean_result']['message']}")
        for err in result["temp_clean_result"].get("errors", []):
            result["errors"].append(f"temp_clean: {err}")

    # Step 5: 最终验证
    final = check_workspace_cleanliness(expanded)
    result["final_clean"] = final["is_clean"] and final["temp_file_count"] == 0

    if result["final_clean"]:
        result["message"] = "✅ 工作区已完全清理干净"
    else:
        remaining = []
        if final["modified"]:
            remaining.append(f"{len(final['modified'])} 个修改")
        if final["untracked"]:
            remaining.append(f"{len(final['untracked'])} 个未跟踪")
        if final["staged"]:
            remaining.append(f"{len(final['staged'])} 个暂存")
        if final["temp_file_count"] > 0:
            remaining.append(f"{final['temp_file_count']} 个临时文件")
        result["message"] = f"⚠️ 清理完成，但仍有遗留 ({'，'.join(remaining)})"

    return result


def clean_temp_files(workspace_dir: str, dry_run: bool = True) -> Dict[str, Any]:
    """
    清理工作区中的临时文件。

    Args:
        workspace_dir: 工作区目录
        dry_run: True=预览模式，False=实际删除

    Returns:
        dict: {
            "removed_count": int,
            "removed": list,
            "errors": list,
            "dry_run": bool,
            "message": str,
        }
    """
    expanded = os.path.expanduser(workspace_dir)
    result = {
        "removed_count": 0,
        "removed": [],
        "errors": [],
        "dry_run": dry_run,
        "message": "",
    }

    target_dirs = [expanded]

    removed = []
    errors = []

    for base in target_dirs:
        if not os.path.isdir(base):
            continue
        try:
            for root, dirs, files in os.walk(base):
                if os.sep + ".git" + os.sep in root or root.endswith(os.sep + ".git"):
                    continue

                for d in dirs:
                    if _is_temp_file(os.path.join(root, d)):
                        full_path = os.path.join(root, d)
                        if dry_run:
                            removed.append(full_path)
                        else:
                            try:
                                shutil.rmtree(full_path)
                                removed.append(full_path)
                            except Exception as e:
                                errors.append(f"{full_path}: {str(e)}")

                for f in files:
                    if _is_temp_file(os.path.join(root, f)):
                        full_path = os.path.join(root, f)
                        if dry_run:
                            removed.append(full_path)
                        else:
                            try:
                                os.remove(full_path)
                                removed.append(full_path)
                            except Exception as e:
                                errors.append(f"{full_path}: {str(e)}")
        except PermissionError:
            continue

    result["removed"] = removed
    result["removed_count"] = len(removed)
    result["errors"] = errors

    if dry_run:
        result["message"] = f"🔍 预览: 将清理 {len(removed)} 个临时文件" if removed else "✅ 无临时文件需要清理"
    else:
        result["message"] = f"🧹 已清理 {len(removed)} 个临时文件" if removed else "✅ 无临时文件需要清理"
        if errors:
            result["message"] += f"，{len(errors)} 个失败"

    return result
