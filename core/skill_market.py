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
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
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
# 真实输出的形态是「条目行 + 紧邻的 └ URL 行」成对出现，因此按块解析，
# 不按出现顺序分别收集再配对 —— 那样一旦某条缺 URL 就会整体错位。
_PAIR_RE = re.compile(
    r"^([\w.\-]+/[\w.\-]+@[\w.\-]+)\s+(.*?installs?)\s*$"
    r"(?:\n\s*\u2514\s+(https?://\S+)\s*$)?",
    re.M,
)
_NO_RESULT_RE = re.compile(r'No skills found for "?([^"\n]*)"?')


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
    results = [
        {"package": pkg, "installs": installs.strip(), "url": url or None}
        for pkg, installs, url in _PAIR_RE.findall(clean)
    ]
    if results:
        return {"results": results, "reason": ""}
    # npx skills find 在无结果时退出码仍为 0，只打印一行说明；原样转述它，
    # 比自造「未找到匹配技能」更有用。
    m = _NO_RESULT_RE.search(clean)
    return {
        "results": [],
        "reason": m.group(0).strip() if m else "未找到匹配技能",
    }


# GitHub API：按 path 取最新提交时间，与 lock 的 updatedAt 比较。
# 未鉴权会限流（实测 `API rate limit exceeded`），支持 GITHUB_TOKEN 提升配额。
_GITHUB_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/.]+?)(?:\.git)?/?$")
_API = "https://api.github.com/repos/{owner}/{repo}/commits"
_UA = "skill-mcp-studio"


def parse_github_source(url: Optional[str]):
    """从 sourceUrl 解析 (owner, repo)。非 GitHub 或无法解析时返回 None。"""
    if not url:
        return None
    m = _GITHUB_RE.search(url.strip())
    return (m.group(1), m.group(2)) if m else None


def _http_get_json(url: str, timeout: int = 20):
    """只读 GET。优先用 curl：本机 Python 的 urllib 拿不到根证书（实测
    CERTIFICATE_VERIFY_FAILED），而 curl 走系统钥匙串可用。失败返回 None。
    """
    token = os.environ.get("GITHUB_TOKEN")
    headers = ["-H", f"User-Agent: {_UA}", "-H", "Accept: application/vnd.github+json"]
    if token:
        headers += ["-H", f"Authorization: Bearer {token}"]
    curl = shutil.which("curl")
    if curl:
        try:
            proc = subprocess.run(
                [curl, "-sS", "--max-time", str(timeout), *headers, url],
                capture_output=True, text=True, timeout=timeout + 10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        return None
    # 回退：无 curl 时试 urllib（可能因根证书而失败）。
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept": "application/vnd.github+json",
        })
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None


def _remote_commit_time(owner: str, repo: str, path: Optional[str],
                        timeout: int = 20) -> Optional[str]:
    """主通道：GitHub API 取该路径最新提交时间（ISO8601）。只读，失败返回 None。"""
    from urllib.parse import urlencode

    q = {"per_page": "1"}
    if path:
        q["path"] = path
    data = _http_get_json(
        _API.format(owner=owner, repo=repo) + "?" + urlencode(q), timeout
    )
    if not isinstance(data, list) or not data:
        return None
    try:
        return data[0]["commit"]["committer"]["date"]
    except (KeyError, TypeError, IndexError):
        return None


def _iso_lt(a: Optional[str], b: Optional[str]) -> bool:
    """字符串化的 ISO8601 可直接比较（同格式同长度）。"""
    return bool(a and b and a < b)


def check_updates(only: Optional[List[str]] = None) -> Dict[str, Any]:
    """只读更新检测。三态：outdated / current / unknown。

    **绝不调用 `npx skills check` 或 `npx skills update`** —— 前者名为检查、
    实为升级（实测一次调用即更新 41 个技能，且未出现在 `--help` 中）。
    本函数只发起 HTTP GET，不写盘、不改动技能库。
    """
    listing = list_installed()
    judged = [r for r in listing["installed"] if r.get("registered")]
    if only:
        wanted = set(only)
        judged = [r for r in judged if r["name"] in wanted]

    counts = {"outdated": 0, "current": 0, "unknown": 0}
    rows: List[Dict[str, Any]] = []
    for row in judged:
        owner_repo = parse_github_source(row.get("source_url"))
        if not owner_repo:
            state, remote = "unknown", None
            note = "非 GitHub 来源或缺少来源信息，无法比对"
        else:
            remote = _remote_commit_time(owner_repo[0], owner_repo[1], row.get("skill_path"))
            if remote is None:
                state, note = "unknown", "远端查询失败（私有/已删除仓库，或 API 限流）"
            elif _iso_lt(row.get("updated_at"), remote):
                state, note = "outdated", ""
            else:
                state, note = "current", ""
        counts[state] += 1
        rows.append(dict(row, state=state, remote_commit=remote, note=note))

    return {"updates": rows, "summary": {"total": len(rows), **counts}}
