"""客户端配置文件的备份管理：列出与还原。

备份沿用 ``core/mcp_fixer.py`` 的命名约定 ``<config_path>.bak-<时间戳>``。

**还原是整文件覆盖**——备份是配置文件的完整副本，还原会连带回退该文件的全部
后续改动（不只是 MCP 段落）。因此调用方（GUI）必须在强确认文案里讲清这一点；
本模块只负责安全落地：归属校验 → 解析校验 → 先备份当前 → 原子写 → 复校。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime
from typing import Any, Dict, List

from mcp_fixer import _atomic_write, _backup_path, validate_config_text

BACKUP_MARKER = ".bak-"


def list_config_backups(config_path: str) -> List[Dict[str, Any]]:
    """返回指定配置文件的全部备份，按时间倒序（新的在前）。"""
    path = os.path.expanduser(config_path or "")
    if not path:
        return []
    directory = os.path.dirname(path) or "."
    prefix = os.path.basename(path) + BACKUP_MARKER
    if not os.path.isdir(directory):
        return []

    found: List[Dict[str, Any]] = []
    for name in os.listdir(directory):
        if not name.startswith(prefix):
            continue
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        info = os.stat(full)
        found.append(
            {
                "path": full,
                "size": info.st_size,
                "mtime": info.st_mtime,
                "mtime_text": datetime.fromtimestamp(info.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "suffix": name[len(prefix):],
            }
        )
    # 排序以**文件名里的时间戳**为主键：它是单调递增的权威序号（写入时生成），
    # 而 mtime 会被文件系统分辨率与"同一秒内连续写入"抹平——实测两个备份的 mtime
    # 相同（CI 上写入极快、部分文件系统秒级分辨率），此时仅按 mtime 排序会退化为
    # os.listdir 的任意顺序，让列表里"最上面"的未必是最新备份，用户据此还原就会
    # 选错版本。故：先比后缀时间戳（字符串按字典序即时间序，格式定长零填充），
    # 再比 mtime 兜底，最后用路径做稳定裁决（保证任何输入下顺序唯一确定）。
    found.sort(
        key=lambda item: (item["suffix"], item["mtime"], item["path"]), reverse=True
    )
    return found


def restore_config_backup(
    tool: Dict[str, Any],
    backup_path: str,
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """把指定备份还原到客户端的配置文件。"""
    config_path = os.path.expanduser(tool.get("config_path", "") or "")
    target = os.path.expanduser(backup_path or "")
    result: Dict[str, str] = {
        "status": "error",
        "message": "",
        "path": config_path,
        "backup": "",
    }

    if not config_path or not os.path.isfile(config_path):
        result["status"] = "missing"
        result["message"] = "配置文件缺失，未做改动"
        return result

    expected_prefix = config_path + BACKUP_MARKER
    if not target.startswith(expected_prefix) or not os.path.isfile(target):
        result["status"] = "refused"
        result["message"] = "不是该客户端配置的备份，已拒绝"
        return result

    try:
        with open(target, "r", encoding="utf-8") as handle:
            content = handle.read()
        validate_config_text(tool, content)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result["status"] = "refused"
        result["message"] = "备份内容解析失败，已拒绝（原配置未变）"
        return result

    if dry_run:
        result["status"] = "dry-run"
        result["message"] = "将用该备份覆盖当前配置"
        return result

    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    safety_backup = _backup_path(config_path)
    try:
        shutil.copy2(config_path, safety_backup)
    except OSError:
        result["status"] = "error"
        result["message"] = "无法备份当前配置，未做改动"
        return result

    try:
        _atomic_write(config_path, content, mode)
    except OSError:
        result["status"] = "error"
        result["message"] = "原子写入失败，原配置未变"
        return result

    result["status"] = "updated"
    result["message"] = "已从备份还原（还原前的当前配置也已备份）"
    result["backup"] = safety_backup
    return result
