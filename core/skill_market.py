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
import re
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


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# `\x1b[1G` 是光标回行首重绘：该行已输出内容被覆盖，应丢弃，而不是连
# 其后被重绘出的真实内容一起删掉。
_CARRIAGE_RE = re.compile(r"[^\n]*\x1b\[1G")
# 独立进度行（以 spinner 开头）才是纯噪声；不含 spinner 前缀的行可能是
# 真实内容，不能按关键词整行删除。
_SPINNER = "\u25d0\u25d3\u25d1\u25d2\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
_PROGRESS_RE = re.compile(
    rf"^[{_SPINNER}\s]*(?:Fetching|Cloning|Updating)[^\n]*\n?", re.M
)
_ENTRY_RE = re.compile(r"^([\w.\-]+/[\w.\-]+@[\w.\-]+)\s+(.*?installs?)\s*$", re.M)
_URL_RE = re.compile(r"^\s*\u2514\s+(https?://\S+)\s*$", re.M)


def strip_ansi(text: str) -> str:
    """剥离 ANSI 颜色码与原地刷新进度行。

    必须先处理 `\x1b[1G` 重绘边界再删 ANSI 码：顺序颠倒时边界信息会随
    ANSI 码一起丢失，导致 spinner 与被重绘出的真实内容被当作同一行删除。
    """
    if not text:
        return ""
    out = _CARRIAGE_RE.sub("", text)
    out = _ANSI_RE.sub("", out)
    out = _PROGRESS_RE.sub("", out)
    return out



def search(query: str, owner: Optional[str] = None) -> Dict[str, Any]:
    """搜索 skills.sh 社区库。只调用 `npx skills find`。"""
    if not query or not query.strip():
        return {"results": [], "reason": "搜索词为空"}

    args = ["find", query.strip()]
    if owner:
        args += ["--owner", owner]

    res = _run_npx(args, timeout=180)
    if res["code"] != 0:
        return {
            "results": [],
            "reason": res["stderr"].strip()[:300] or f"npx skills find 退出码 {res['code']}",
        }

    clean = strip_ansi(res["stdout"])
    urls = _URL_RE.findall(clean)
    results = []
    for idx, (pkg, installs) in enumerate(_ENTRY_RE.findall(clean)):
        results.append({
            "package": pkg,
            "installs": installs.strip(),
            "url": urls[idx] if idx < len(urls) else None,
        })
    return {"results": results, "reason": "" if results else "未找到匹配技能"}