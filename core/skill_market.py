"""FEAT-9 技能市场访问层（只读）。

包装本机 `npx skills` CLI，不重写市场逻辑。

**硬约束**：本模块及其调用方**禁止**执行 `npx skills check` 与
`npx skills update`。前者名为检查、实为升级（实测一次更新 41 个技能，
且未出现在 `--help` 列表中），后者无 `--dry-run`。检查更新一律走本模块的
只读检测（见 check_updates），由 tests/test_skill_market.py 的护栏锁定。

设计依据：docs/superpowers/specs/2026-09-23-skill-market-integration-design.md
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# 这三个源来自本机 find-skills 技能的权威说明；A/C 在当前环境不可用，
# 但仍要在清单中呈现，让用户看到「为什么没有结果」而不是静默空白。
_SOURCE_SPECS = (
    ("skills.sh", "skills.sh 社区技能库", True),
    ("qwenwork", "QwenWork 官方市场", False),
    ("enterprise", "企业技能市场 MCP", False),
)

_NPX_TIMEOUT = 60


def _run_npx(args: List[str], timeout: int = _NPX_TIMEOUT) -> Dict[str, Any]:
    """执行 `npx -y skills ...`，返回 {code, stdout, stderr}。不抛异常。"""
    npx = shutil.which("npx")
    if not npx:
        return {"code": 127, "stdout": "", "stderr": "npx not found"}
    try:
        proc = subprocess.run(
            [npx, "-y", "skills", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": "timeout"}
    except OSError as exc:
        return {"code": 126, "stdout": "", "stderr": str(exc)}


def detect_backend() -> Dict[str, Any]:
    """探测 `npx skills` 可用性。缺失时降级，不抛异常。"""
    npx = shutil.which("npx")
    if not npx:
        return {
            "available": False,
            "npx_path": None,
            "version": None,
            "reason": "未找到 npx；技能市场需要 Node.js（含 npx）",
        }
    res = _run_npx(["--help"], timeout=120)
    if res["code"] != 0:
        return {
            "available": False,
            "npx_path": npx,
            "version": None,
            "reason": f"npx skills 不可用：{res['stderr'].strip()[:200]}",
        }
    return {"available": True, "npx_path": npx, "version": None, "reason": ""}


def read_sources() -> Dict[str, Any]:
    """三个市场源的可用性汇总。缺失源带 reason，不抛异常。"""
    backend = detect_backend()
    sources: Dict[str, Any] = {}
    for sid, label, _ in _SOURCE_SPECS:
        if sid == "skills.sh":
            sources[sid] = {
                "id": sid, "label": label,
                "available": backend["available"],
                "reason": "" if backend["available"] else backend["reason"],
            }
        else:
            sources[sid] = {
                "id": sid, "label": label, "available": False,
                "reason": (
                    "需要 QwenWork 客户端的 mcp__qw-builtin__ 工具；当前会话未检测到"
                    if sid == "qwenwork"
                    else "未检测到提供 searchSkills 能力的企业 MCP 服务"
                ),
            }
    return {"backend": backend, "sources": sources}


_AGENTS_DIR = Path.home() / ".agents"
_DEFAULT_LOCK = _AGENTS_DIR / ".skill-lock.json"
_SKILLS_DIR = Path.home() / ".skills-manager" / "skills"


def _read_lock(lock_path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}


def list_installed(
    lock_path: Optional[Path] = None,
    skills_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """已装技能清单：lock 的来源登记 + 统一库实体目录。

    folder_hash 归一为 None —— 实测该字段恒为空字符串，若原样透出会被
    调用方误当作版本标识。
    """
    lock_path = Path(lock_path) if lock_path else _DEFAULT_LOCK
    skills_dir = Path(skills_dir) if skills_dir else _SKILLS_DIR

    lock = _read_lock(lock_path)
    registered = lock.get("skills") or {}

    hashes = set()
    if skills_dir.is_dir():
        # 技能库根目录含 .git 等元数据目录，它们不是技能，必须排除。
        hashes = {
            d.name for d in skills_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        }

    installed: List[Dict[str, Any]] = []
    for name in sorted(hashes | set(registered)):
        meta = registered.get(name) or {}
        raw_hash = meta.get("skillFolderHash") or ""
        installed.append({
            "name": name,
            "source": meta.get("source"),
            "source_type": meta.get("sourceType"),
            "source_url": meta.get("sourceUrl"),
            "skill_path": meta.get("skillPath"),
            "installed_at": meta.get("installedAt"),
            "updated_at": meta.get("updatedAt"),
            "folder_hash": raw_hash or None,
            "on_disk": name in hashes,
            "registered": name in registered,
        })

    reason = ""
    if not lock_path.exists():
        reason = f"未找到来源登记 {lock_path}；仅列出磁盘上的技能"
    return {"installed": installed, "reason": reason, "lock_path": str(lock_path)}