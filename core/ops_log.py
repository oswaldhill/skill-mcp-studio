"""后台操作日志（落盘，用于排查 GUI 写操作链路）。

把每次修复/清理/删除等写操作的关键决策点追加到 ``data/operations.log``，
JSON 每行一条，带时间戳。写失败静默：日志是排查辅助，绝不允许它阻断主流程。

用法::

    from ops_log import ops_log
    ops_log("fix_mcp_begin", client="VS Code", normalized="vscode", dry_run=True)
"""

import json
import os
import time
from typing import Any, Dict, Optional

_LOG_RELPATH = os.path.join("data", "operations.log")


def _log_path() -> str:
    # 以 core/ 的上级（项目根）为基准，保证 CLI 与 GUI 子进程都以同一路径落盘。
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", _LOG_RELPATH
    )


def ops_log(event: str, **fields: Any) -> Optional[str]:
    """追加一条操作日志，返回落盘路径（失败时返回 None，不抛异常）。"""
    path = _log_path()
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fields = {key: value for key, value in fields.items() if value is not None}
        fields["t"] = fields.pop("t", None) or time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(fields, ensure_ascii=False, default=str) + "\n")
        return path
    except Exception:
        return None


def format_record(fields: Dict[str, Any]) -> str:
    """把字段渲染成 CLI stderr 友好的一行，供前端「查看详情」展示。"""
    return " ".join(f"{k}={v}" for k, v in fields.items())
