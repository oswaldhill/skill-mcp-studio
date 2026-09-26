# 技能市场接入 + 版本更新检测 + 在线升级 实现计划

> **⚠️ 历史存档 —— 文中的测试命令已过时。** 本计划写于 pytest 尚在 `pyproject.toml`
> 中声明的时期；项目现已统一为**标准库 unittest**（评审 P1-10 采方案 B）。
> 文中所有 `python3 -m pytest …` 请一律改用 CI 的等价命令：
> `python3 -m unittest discover -s tests -p 'test_*.py'`，或直接跑 `scripts/ci_parity.sh`
> （它还会自动挑选合格解释器、补齐 node 前置条件并与 CI 基线对照）。
> 单文件调试请用 `python3 -m unittest tests.<文件名去掉 .py 并把 / 换成 .>`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Skill MCP Studio 中接入 skills.sh 技能市场，提供只读的搜索、已装清单与版本更新检测，以及经用户确认的在线安装/升级，GUI 以逐技能进度展示。

**Architecture:** 新增 `core/skill_market.py` 作为唯一市场访问层，包装本机 `npx skills` CLI（不重写市场逻辑），并把 `npx skills list -g --json` 的机器可读输出与 `~/.agents/.skill-lock.json` 的来源登记合并成结构化数据。GUI 只消费 `scan.py --market ... --format json` 的出口，不自行解析 `npx` 输出。所有写操作（安装/升级）经 CLI，并复用既有备份→确认→执行链。

**Tech Stack:** Python 3（标准库 + `subprocess`/`json`/`urllib`）、`unittest`、Tauri v2 + 原生 JS（`gui/dashboard.html`）

**Spec:** `docs/superpowers/specs/2026-09-23-skill-market-integration-design.md`

---

## 不可违背的约束（来自 spec 的实测结论）

1. **禁止调用 `npx skills check`** —— 该命令名为检查、实为升级（实测一次更新 41 个技能），且未出现在 `--help` 中。`npx skills update` 无 `--dry-run`。检查更新必须自行实现只读检测。
2. **`~/.skills-manager/skills` 是唯一实体**，`~/.agents/skills` 等四目录为符号链接 ⇒ `npx skills add -g` 装到 `~/.agents/skills` 即已落在统一库，**不需要额外归一机制**，只需装后校验。
3. **`skillFolderHash` 为空字符串**，不可用于版本比较。
4. **`npx skills list -g --json` 输出干净 JSON**；`find` / `check` 输出含 ANSI 转义与 `◐ Fetching…` 刷新行，必须清洗。
5. 源 A（QwenWork 官方市场，需 `mcp__qw-builtin__`）本机不可用；源 C（企业 MCP）未探测到。两者标注「未检测到」，**不报错**。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `core/skill_market.py`（新建） | 市场访问唯一入口：后端探测、已装清单、搜索、只读更新检测。**不写盘** |
| `core/skill_market_ops.py`（新建） | 写操作：安装/升级。独立成文件是因为它写盘，必须与只读层在代码审查上可区分 |
| `scan.py`（改） | 新增 `--market` 参数与 `_run_market` 调度，输出 `--format json` |
| `tests/test_skill_market.py`（新建） | 只读层单测 + **禁止破坏性命令的护栏** |
| `tests/test_skill_market_ops.py`（新建） | 写操作单测（全部 mock，绝不真的调 npx） |
| `gui/dashboard.html`（改） | Skills 页「市场」入口、搜索/已装/更新三区、逐技能进度 |
| `tests/test_dashboard_market_ui.py`（新建） | GUI 静态护栏 |

---

## Task 1: 后端探测与源可用性（只读）

**Files:**
- Create: `core/skill_market.py`
- Test: `tests/test_skill_market.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_skill_market.py`：

```python
"""FEAT-9: 技能市场访问层（只读）契约测试。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_market import detect_backend, read_sources  # noqa: E402


class DetectBackendTest(unittest.TestCase):
    def test_returns_dict_with_expected_keys(self):
        info = detect_backend()
        for key in ("available", "npx_path", "version", "reason"):
            self.assertIn(key, info)

    def test_missing_npx_degrades_without_raising(self):
        """后端缺失必须降级为 available=False，不得抛异常。"""
        with mock.patch("skill_market.shutil.which", return_value=None):
            info = detect_backend()
        self.assertFalse(info["available"])
        self.assertIsNone(info["npx_path"])
        self.assertTrue(info["reason"])


class ReadSourcesTest(unittest.TestCase):
    def test_three_sources_always_present(self):
        """三个源恒在清单中，缺失的标 unavailable 而非省略。"""
        srcs = read_sources()
        self.assertEqual(set(srcs["sources"]), {"skills.sh", "qwenwork", "enterprise"})

    def test_unavailable_sources_carry_reason(self):
        srcs = read_sources()
        for s in srcs["sources"].values():
            if not s["available"]:
                self.assertTrue(s["reason"], f"{s['id']} 不可用但未给原因")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_market.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skill_market'`

- [ ] **Step 3: 实现最小代码**

创建 `core/skill_market.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_market.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add core/skill_market.py tests/test_skill_market.py
git commit -m "feat(skill-market): 后端探测与三源可用性（只读）"
```

---

## Task 2: 已装清单（合并 lock 与 npx 输出）

**Files:**
- Modify: `core/skill_market.py`
- Test: `tests/test_skill_market.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_skill_market.py`：

```python
import json as _json
import tempfile

from skill_market import list_installed  # noqa: E402


class ListInstalledTest(unittest.TestCase):
    def _lock(self, tmp, payload):
        p = Path(tmp) / ".skill-lock.json"
        p.write_text(_json.dumps(payload), encoding="utf-8")
        return p

    def test_reads_source_fields_from_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = self._lock(tmp, {
                "version": 3,
                "skills": {
                    "find-skills": {
                        "source": "vercel-labs/skills",
                        "sourceType": "github",
                        "sourceUrl": "https://github.com/vercel-labs/skills.git",
                        "skillPath": "skills/find-skills/SKILL.md",
                        "skillFolderHash": "",
                        "installedAt": "2026-01-27T03:25:42.413Z",
                        "updatedAt": "2026-03-03T06:09:35.044Z",
                    }
                },
            })
            out = list_installed(lock_path=lock, skills_dir=None)
        row = next(r for r in out["installed"] if r["name"] == "find-skills")
        self.assertEqual(row["source"], "vercel-labs/skills")
        self.assertEqual(row["source_url"], "https://github.com/vercel-labs/skills.git")
        self.assertEqual(row["skill_path"], "skills/find-skills/SKILL.md")
        self.assertEqual(row["updated_at"], "2026-03-03T06:09:35.044Z")

    def test_empty_folder_hash_is_not_treated_as_version(self):
        """skillFolderHash 恒为空，不得据此判断版本。"""
        with tempfile.TemporaryDirectory() as tmp:
            lock = self._lock(tmp, {
                "version": 3,
                "skills": {"x": {"source": "a/b", "skillFolderHash": ""}},
            })
            out = list_installed(lock_path=lock, skills_dir=None)
        row = next(r for r in out["installed"] if r["name"] == "x")
        self.assertIsNone(row["folder_hash"])

    def test_missing_lock_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = list_installed(lock_path=Path(tmp) / "nope.json", skills_dir=None)
        self.assertEqual(out["installed"], [])
        self.assertTrue(out["reason"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_market.py -q -k ListInstalled`
Expected: FAIL — `ImportError: cannot import name 'list_installed'`

- [ ] **Step 3: 实现**

在 `core/skill_market.py` 追加：

```python
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

    installed: List[Dict[str, Any]] = []
    hashes = set()
    if skills_dir.is_dir():
        hashes = {d.name for d in skills_dir.iterdir() if d.is_dir()}

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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_market.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add core/skill_market.py tests/test_skill_market.py
git commit -m "feat(skill-market): 已装清单合并 lock 登记与磁盘实体"
```

---

## Task 3: 输出清洗与搜索

**Files:**
- Modify: `core/skill_market.py`
- Test: `tests/test_skill_market.py`

- [ ] **Step 1: 写失败测试**

```python
from skill_market import strip_ansi, search  # noqa: E402


class StripAnsiTest(unittest.TestCase):
    def test_removes_color_codes(self):
        raw = "\x1b[38;5;145mvercel-labs/x@y\x1b[0m  736.1K installs"
        self.assertEqual(strip_ansi(raw), "vercel-labs/x@y  736.1K installs")

    def test_removes_progress_refresh_lines(self):
        """`◐ Fetching skills…` 这类原地刷新行必须清掉，否则解析出的条目是脏的。"""
        raw = "◐  Fetching skills…\x1b[1G\x1b[Jvercel-labs/x@y\n"
        out = strip_ansi(raw)
        self.assertNotIn("Fetching", out)
        self.assertIn("vercel-labs/x@y", out)

    def test_plain_text_unchanged(self):
        self.assertEqual(strip_ansi("hello world"), "hello world")


class SearchTest(unittest.TestCase):
    def test_parses_find_output(self):
        sample = (
            "\x1b[38;5;102mInstall with\x1b[0m npx skills add <owner/repo@skill>\n\n"
            "\x1b[38;5;145mvercel-labs/agent-skills@vercel-react-best-practices\x1b[0m"
            " \x1b[36m736.1K installs\x1b[0m\n"
            "\x1b[38;5;102m└ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices\x1b[0m\n"
        )
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 0, "stdout": sample, "stderr": ""}):
            out = search("react")
        self.assertEqual(len(out["results"]), 1)
        r = out["results"][0]
        self.assertEqual(r["package"], "vercel-labs/agent-skills@vercel-react-best-practices")
        self.assertIn("736.1K", r["installs"])
        self.assertEqual(r["url"],
                         "https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices")

    def test_backend_failure_returns_empty_with_reason(self):
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 1, "stdout": "", "stderr": "boom"}):
            out = search("x")
        self.assertEqual(out["results"], [])
        self.assertTrue(out["reason"])

    def test_search_never_invokes_destructive_subcommands(self):
        """护栏：search 只允许 find。"""
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 0, "stdout": "", "stderr": ""}) as m:
            search("react")
        called = m.call_args[0][0]
        self.assertEqual(called[0], "find")
        self.assertNotIn("check", called)
        self.assertNotIn("update", called)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_market.py -q -k "StripAnsi or Search"`
Expected: FAIL — `ImportError: cannot import name 'strip_ansi'`

- [ ] **Step 3: 实现**

```python
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# `◐  Fetching skills…` 后跟 \x1b[1G\x1b[J 表示原地重绘，整行都是噪声。
_PROGRESS_RE = re.compile(r"^.*?(?:Fetching|Cloning|Updating)[^\n]*\n?", re.M)
_ENTRY_RE = re.compile(r"^([\w.\-]+/[\w.\-]+@[\w.\-]+)\s+(.*?installs?)\s*$", re.M)
_URL_RE = re.compile(r"^\s*└\s+(https?://\S+)\s*$", re.M)


def strip_ansi(text: str) -> str:
    """剥离 ANSI 颜色码与原地刷新进度行。"""
    if not text:
        return ""
    out = _ANSI_RE.sub("", text)
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_market.py -q`
Expected: PASS（13 passed）

- [ ] **Step 5: 提交**

```bash
git add core/skill_market.py tests/test_skill_market.py
git commit -m "feat(skill-market): 搜索与 npx 输出清洗"
```

---

## Task 4: 只读更新检测（双通道）

**Files:**
- Modify: `core/skill_market.py`
- Test: `tests/test_skill_market.py`

- [ ] **Step 1: 写失败测试**

```python
from skill_market import parse_github_source, check_updates  # noqa: E402


class ParseGithubSourceTest(unittest.TestCase):
    def test_ssh_and_https_forms(self):
        for url in ("https://github.com/vercel-labs/skills.git",
                    "git@github.com:vercel-labs/skills.git"):
            owner, repo = parse_github_source(url)
            self.assertEqual((owner, repo), ("vercel-labs", "skills"))

    def test_non_github_returns_none(self):
        self.assertIsNone(parse_github_source("https://gitlab.com/a/b.git"))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_github_source(""))


class CheckUpdatesTest(unittest.TestCase):
    def _installed(self):
        return {"installed": [
            {"name": "a", "source_url": "https://github.com/o/r.git",
             "skill_path": "skills/a/SKILL.md", "updated_at": "2026-01-01T00:00:00.000Z"},
            {"name": "b", "source_url": None, "skill_path": None, "updated_at": None},
        ]}

    def test_three_states(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        side_effect=lambda o, r, p, **kw: "2026-09-01T00:00:00Z"):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "outdated")
        self.assertEqual(by["b"], "unknown")

    def test_up_to_date_state(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        side_effect=lambda o, r, p, **kw: "2025-12-01T00:00:00Z"):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "current")

    def test_remote_failure_is_unknown_not_error(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time", return_value=None):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "unknown")

    def test_counts_reported(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time", return_value=None):
            out = check_updates()
        self.assertEqual(out["summary"]["total"], 2)
        self.assertEqual(out["summary"]["unknown"], 2)


class NoDestructiveCommandTest(unittest.TestCase):
    """护栏：本模块源码中不得出现破坏性的 skills 子命令。"""

    def test_source_has_no_check_or_update_call(self):
        src = (ROOT / "core" / "skill_market.py").read_text(encoding="utf-8")
        for bad in ('"check"', "'check'", '"update"', "'update'", "upgrade"):
            self.assertNotIn(bad, src,
                             f"只读模块出现破坏性子命令 {bad}；"
                             f"npx skills check 实为升级，禁止调用")

    def test_no_shell_string_mentions_them(self):
        src = (ROOT / "core" / "skill_market.py").read_text(encoding="utf-8")
        self.assertNotIn("skills check", src)
        self.assertNotIn("skills update", src)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_market.py -q -k "Parse or Check or NoDestructive"`
Expected: FAIL — `ImportError: cannot import name 'parse_github_source'`

- [ ] **Step 3: 实现**

```python
import os
import urllib.error
import urllib.request

_GITHUB_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/.]+?)(?:\.git)?/?$")
_API = "https://api.github.com/repos/{owner}/{repo}/commits"
_UA = "skill-mcp-studio"


def parse_github_source(url: Optional[str]):
    """从 sourceUrl 解析 (owner, repo)。非 GitHub 返回 None。"""
    if not url:
        return None
    m = _GITHUB_RE.search(url.strip())
    return (m.group(1), m.group(2)) if m else None


def _remote_commit_time(owner: str, repo: str, path: Optional[str],
                        timeout: int = 20) -> Optional[str]:
    """主通道：GitHub API 取该路径最新提交时间（ISO8601）。只读，失败返回 None。

    未鉴权会限流（实测 `API rate limit exceeded`）；支持 GITHUB_TOKEN 提升配额。
    """
    from urllib.parse import urlencode
    q = {"per_page": "1"}
    if path:
        q["path"] = path
    req = urllib.request.Request(
        _API.format(owner=owner, repo=repo) + "?" + urlencode(q),
        headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None
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

    **绝不调用 `npx skills check` 或 `update`** —— 前者实为升级。
    """
    listing = list_installed()
    rows: List[Dict[str, Any]] = []
    judged = [r for r in listing["installed"] if r.get("registered")]
    if only:
        wanted = set(only)
        judged = [r for r in judged if r["name"] in wanted]

    counts = {"outdated": 0, "current": 0, "unknown": 0}
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

    return {
        "updates": rows,
        "summary": {"total": len(rows), **counts},
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_market.py -q`
Expected: PASS（22 passed）

- [ ] **Step 5: 提交**

```bash
git add core/skill_market.py tests/test_skill_market.py
git commit -m "feat(skill-market): 只读更新检测（GitHub API + 三态），附破坏性命令护栏"
```

---

## Task 5: CLI 出口 `--market`

**Files:**
- Modify: `scan.py`（参数注册约 :1392 后；调度约 :1536 后）
- Test: `tests/test_skill_market_cli.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_skill_market_cli.py`：

```python
"""FEAT-9: `--market` CLI 出口契约。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "scan.py"


def run_market(*args, timeout=180):
    proc = subprocess.run(
        [sys.executable, str(SCAN), "--market", *args, "--format", "json"],
        capture_output=True, text=True, timeout=timeout, cwd=str(ROOT),
    )
    return proc


class MarketCliTest(unittest.TestCase):
    def test_sources_returns_json(self):
        proc = run_market("sources")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("sources", data)
        self.assertIn("skills.sh", data["sources"])

    def test_list_returns_installed(self):
        proc = run_market("list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("installed", data)
        self.assertIsInstance(data["installed"], list)

    def test_unknown_subcommand_is_usage_error(self):
        proc = run_market("bogus")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("market", proc.stdout.lower() + proc.stderr.lower())

    def test_check_does_not_mutate_skills_dir(self):
        """护栏：--market check 前后统一库文件数与 mtime 快照必须一致。"""
        def snap():
            d = Path.home() / ".skills-manager" / "skills"
            return {p.name: p.stat().st_mtime_ns for p in d.iterdir()} if d.is_dir() else {}
        before = snap()
        proc = run_market("check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        after = snap()
        self.assertEqual(before, after, "--market check 修改了技能库；它必须是只读的")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_market_cli.py -q -k sources`
Expected: FAIL — 退出码非 0（`--market` 未注册）

- [ ] **Step 3: 实现**

在 `scan.py` 的参数注册区（`--client-command` 那组之后）追加：

```python
    parser.add_argument(
        "--market", type=str, default=None,
        choices=["sources", "list", "search", "check"],
        help="技能市场（只读）：sources=源可用性 list=已装清单 "
             "search=搜索（需 --market-query）check=检查更新",
    )
    parser.add_argument(
        "--market-query", type=str, default=None,
        help="配合 --market search：搜索词",
    )
```

在 `main()` 的早返回区（`if args.audit_skill_states:` 之前）追加：

```python
    if args.market:
        return _run_market(args)
```

在同文件的「Skill 动作 helper」区新增：

```python
def _run_market(args) -> int:
    """`--market` 只读出口。全量禁止写操作（安装/升级由 skill_market_ops 另行处理）。"""
    from skill_market import check_updates, list_installed, read_sources, search

    want_json = getattr(args, "format", None) == "json"
    try:
        if args.market == "sources":
            payload = read_sources()
        elif args.market == "list":
            payload = list_installed()
        elif args.market == "search":
            if not args.market_query:
                print("  ❌ --market search 需要 --market-query <词>")
                return 2
            payload = search(args.market_query)
        elif args.market == "check":
            payload = check_updates()
        else:
            print(f"  ❌ 未知的 --market 子命令: {args.market}")
            return 2
    except Exception as exc:                      # 市场不可用不应中断其他流程
        payload = {"error": str(exc)}

    if want_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_market(payload, args.market)
    return 0


def _print_market(payload: dict, kind: str) -> None:
    if kind == "sources":
        for sid, s in (payload.get("sources") or {}).items():
            mark = "可用" if s["available"] else "不可用"
            line = f"  {s['label']}: {mark}"
            if s["reason"]:
                line += f" —— {s['reason']}"
            print(line)
    elif kind == "list":
        rows = payload.get("installed") or []
        print(f"  已装 {len(rows)} 个技能")
        for r in rows:
            print(f"    {r['name']:32} {r.get('source') or '-'}")
    elif kind == "search":
        for r in payload.get("results") or []:
            print(f"    {r['package']:56} {r['installs']}")
        if not payload.get("results"):
            print(f"  {payload.get('reason') or '无结果'}")
    elif kind == "check":
        s = payload.get("summary") or {}
        print(f"  共 {s.get('total', 0)}：有更新 {s.get('outdated', 0)} / "
              f"已最新 {s.get('current', 0)} / 无法检测 {s.get('unknown', 0)}")
        for r in payload.get("updates") or []:
            if r["state"] == "outdated":
                print(f"    {r['name']:32} {r.get('remote_commit')}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_market_cli.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 手工验证真实输出**

Run: `python3 scan.py --market sources`
Expected: 三行输出，`skills.sh 社区技能库: 可用`，另两行「不可用 —— 需要…」

Run: `python3 scan.py --market check --format json | head -20`
Expected: JSON，含 `summary` 与 `updates`

- [ ] **Step 6: 提交**

```bash
git add scan.py tests/test_skill_market_cli.py
git commit -m "feat(skill-market): 新增 --market 只读 CLI 出口"
```

---

## Task 6: 写操作层（安装/升级，全部 mock 测试）

**Files:**
- Create: `core/skill_market_ops.py`
- Test: `tests/test_skill_market_ops.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_skill_market_ops.py`：

```python
"""FEAT-9: 市场写操作（安装/升级）。全部 mock，绝不真的调用 npx。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_market_ops import plan_install, plan_upgrade, verify_installed  # noqa: E402


class PlanTest(unittest.TestCase):
    def test_plan_install_shape(self):
        plan = plan_install("vercel-labs/agent-skills@x")
        self.assertEqual(plan["action"], "install")
        self.assertEqual(plan["package"], "vercel-labs/agent-skills@x")
        self.assertEqual(plan["argv"][:2], ["add", "vercel-labs/agent-skills@x"])
        self.assertIn("-g", plan["argv"])
        self.assertIn("-y", plan["argv"])

    def test_plan_upgrade_shape(self):
        plan = plan_upgrade(["a", "b"])
        self.assertEqual(plan["action"], "upgrade")
        self.assertEqual(plan["names"], ["a", "b"])
        self.assertEqual(plan["argv"][0], "update")

    def test_plan_upgrade_empty_is_rejected(self):
        plan = plan_upgrade([])
        self.assertFalse(plan["ok"])
        self.assertTrue(plan["reason"])

    def test_plans_never_use_check(self):
        """护栏：写操作也绝不使用 check（它实为升级，语义混乱且不可控）。"""
        for plan in (plan_install("a/b"), plan_upgrade(["a"])):
            self.assertNotIn("check", plan["argv"])


class VerifyTest(unittest.TestCase):
    def test_verify_reports_present_and_missing(self):
        with mock.patch("skill_market_ops._skills_dir") as sd:
            sd.return_value = Path("/nonexistent-dir-for-test")
            out = verify_installed(["a", "b"])
        self.assertFalse(out["ok"])
        self.assertEqual(sorted(out["missing"]), ["a", "b"])
        self.assertEqual(out["present"], [])


class ExecTest(unittest.TestCase):
    def test_execute_uses_injected_runner(self):
        """执行器必须可注入 runner，测试期永不真跑 npx。"""
        from skill_market_ops import execute_plan
        calls = []

        def fake_runner(argv, timeout=None):
            calls.append(argv)
            return {"code": 0, "stdout": "ok", "stderr": ""}

        with mock.patch("skill_market_ops.verify_installed",
                        return_value={"ok": True, "present": ["a"], "missing": []}):
            res = execute_plan(plan_install("a/b@x"), runner=fake_runner)
        self.assertTrue(res["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "add")

    def test_execute_reports_failure_without_raising(self):
        from skill_market_ops import execute_plan

        def bad_runner(argv, timeout=None):
            return {"code": 1, "stdout": "", "stderr": "clone failed"}

        res = execute_plan(plan_install("a/b@x"), runner=bad_runner)
        self.assertFalse(res["ok"])
        self.assertIn("clone failed", res["stderr"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_skill_market_ops.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skill_market_ops'`

- [ ] **Step 3: 实现**

创建 `core/skill_market_ops.py`：

```python
"""FEAT-9 技能市场写操作（安装 / 升级）。

与只读层 `skill_market` 分文件，是为了让「会写盘」这件事在代码审查上可见。

安全形状：先生成 plan（可展示、可确认）→ 再 execute。执行器接受注入的
runner，测试期永不真调 npx。**不使用 `npx skills check`**（该命令实为升级，
且不受 --skill 选择控制）。

安装目标：`npx skills add ... -g` 落到 `~/.agents/skills`，而它是
`~/.skills-manager/skills` 的符号链接 ⇒ 已直接落在统一库，无需额外归一。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from skill_market import _run_npx

_SKILLS_DIR = Path.home() / ".skills-manager" / "skills"


def _skills_dir() -> Path:
    """独立成函数，便于测试替换。"""
    return _SKILLS_DIR


def plan_install(package: str) -> Dict[str, Any]:
    """生成安装计划，不执行。"""
    pkg = (package or "").strip()
    if not pkg:
        return {"ok": False, "action": "install", "package": "", "argv": [],
                "reason": "包名为空"}
    return {
        "ok": True,
        "action": "install",
        "package": pkg,
        "argv": ["add", pkg, "-g", "-y"],
        "reason": "",
    }


def plan_upgrade(names: List[str]) -> Dict[str, Any]:
    """生成升级计划，不执行。names 为空则拒绝。"""
    clean = [n.strip() for n in (names or []) if n and n.strip()]
    if not clean:
        return {"ok": False, "action": "upgrade", "names": [], "argv": [],
                "reason": "未指定要升级的技能"}
    return {
        "ok": True,
        "action": "upgrade",
        "names": clean,
        "argv": ["update", *clean, "-g", "-y"],
        "reason": "",
    }


def verify_installed(names: List[str]) -> Dict[str, Any]:
    """校验技能是否已落在统一库。装后必查，避免「命令成功但没装上」。"""
    root = _skills_dir()
    present, missing = [], []
    for n in names or []:
        (present if (root / n).is_dir() else missing).append(n)
    return {"ok": not missing, "present": present, "missing": missing, "root": str(root)}


def execute_plan(
    plan: Dict[str, Any],
    runner: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """执行计划。runner 可注入（测试期不真跑 npx）。不抛异常。"""
    if not plan.get("ok"):
        return {"ok": False, "stdout": "", "stderr": "", "reason": plan.get("reason", "")}

    run = runner or _run_npx
    res = run(plan["argv"], timeout=1800)
    out = {
        "ok": res.get("code") == 0,
        "code": res.get("code"),
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", ""),
        "action": plan["action"],
    }
    if plan["action"] == "install":
        out["verify"] = verify_installed([plan["package"].split("@")[-1]])
    else:
        out["verify"] = verify_installed(plan["names"])
    if out["ok"] and not out["verify"]["ok"]:
        out["ok"] = False
        out["stderr"] = (out["stderr"] or "") + "\n命令成功但统一库中未找到安装结果"
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_skill_market_ops.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add core/skill_market_ops.py tests/test_skill_market_ops.py
git commit -m "feat(skill-market): 安装/升级计划与执行器（可注入 runner，装后校验）"
```

---

## Task 7: GUI 市场面板（逐技能进度）

**Files:**
- Modify: `gui/dashboard.html`
- Test: `tests/test_dashboard_market_ui.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_dashboard_market_ui.py`：

```python
"""FEAT-9 GUI 护栏：市场入口、逐技能进度、安装二次确认。"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _section(page_id: str) -> str:
    m = re.search(r'<section id="' + page_id + r'".*?</section>', _src(), re.S)
    if not m:
        raise AssertionError(f"未找到页面区块 {page_id}")
    return m.group(0)


def _fn(name: str) -> str:
    m = re.search(r"function " + name + r"\(.*?\n\}", _src(), re.S)
    if not m:
        raise AssertionError(f"未找到函数 {name}")
    return m.group(0)


class MarketUiTest(unittest.TestCase):
    def test_skills_page_has_market_entry(self):
        self.assertIn('data-action="open-market"', _section("page-skills"))

    def test_market_action_is_wired(self):
        self.assertIn('a === "open-market"', _src())

    def test_progress_renders_per_skill(self):
        """逐技能进度：渲染函数必须按行追加，而不是只写一行汇总。"""
        body = _fn("renderMarketProgress")
        self.assertIn("forEach", body)
        self.assertIn("appendChild", body)

    def test_install_requires_confirmation(self):
        """安装前必须有确认步骤，不得静默安装。"""
        src = _src()
        self.assertIn("function confirmMarketInstall", src)
        self.assertIn("confirmMarketInstall(", src)
        body = _fn("confirmMarketInstall")
        self.assertTrue(
            "confirm" in body or "showModal" in body or "openModal" in body,
            "安装确认必须走确认弹窗，不能直接执行",
        )

    def test_uses_runcli_for_market_data(self):
        self.assertIn('"--market"', _src())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_dashboard_market_ui.py -q`
Expected: FAIL — 断言 `data-action="open-market"` 未找到

- [ ] **Step 3: 实现**

在 `gui/dashboard.html` 的 `page-skills` 区块 `.page-actions` 内，于「刷新技能」按钮后追加：

```html
          <button class="btn-soft" data-action="open-market">技能市场</button>
```

在事件委托里（`a === "refresh-skills"` 之后）追加：

```js
    else if (a === "open-market") openMarketPanel();
    else if (a === "market-search") runMarketSearch(act);
    else if (a === "market-check") runMarketCheck(act);
    else if (a === "market-install") confirmMarketInstall(act.dataset.pkg);
    else if (a === "market-upgrade") confirmMarketUpgrade(act.dataset.name);
```

在脚本区（`refreshWithBtn` 之后）新增：

```js
// ---------------- 技能市场 ----------------
// 数据一律经 CLI 出口取得（scan.py --market ...），前端不解析 npx 输出。
// 检查更新是只读的：后端绝不调用 `npx skills check`（它实为升级）。
let MARKET_DATA = { sources: null, installed: null, updates: null, installable: null };

function marketPanel() { return $("market-panel"); }

function openMarketPanel() {
  const el = marketPanel();
  if (!el) return;
  el.classList.toggle("hidden");
  if (!el.classList.contains("hidden") && !MARKET_DATA.sources) loadMarketSources();
}

async function loadMarketSources() {
  const res = await runCli(["--market", "sources", "--format", "json"]);
  if (!res || res.code !== 0) { renderMarketSources(null, (res && res.stderr) || "读取失败"); return; }
  try { renderMarketSources(JSON.parse(res.stdout || "{}"), ""); }
  catch (e) { renderMarketSources(null, "返回数据无法解析"); }
}

function renderMarketSources(data, err) {
  const el = $("market-sources");
  if (!el) return;
  el.innerHTML = "";
  if (err || !data) { el.appendChild(marketLine(err || "无数据", "err")); return; }
  Object.values(data.sources || {}).forEach((s) => {
    const text = `${s.label}：${s.available ? "可用" : "未检测到"}`;
    el.appendChild(marketLine(s.reason ? `${text} —— ${s.reason}` : text,
                              s.available ? "ok" : "warn"));
  });
}

function marketLine(text, kind) {
  const div = document.createElement("div");
  div.className = "market-line" + (kind ? " " + kind : "");
  div.textContent = text;
  return div;
}

// 逐技能进度：每行独立追加，长任务期间用户能看到逐项结果。
function renderMarketProgress(lines) {
  const el = $("market-progress");
  if (!el) return;
  el.innerHTML = "";
  (lines || []).forEach((ln) => {
    const row = marketLine(ln.text, ln.kind);
    el.appendChild(row);
  });
}

function appendMarketProgress(text, kind) {
  const el = $("market-progress");
  if (!el) return;
  el.appendChild(marketLine(text, kind));
}

async function runMarketSearch(btn) {
  const q = ($("market-query") && $("market-query").value || "").trim();
  if (!q) { showToast("err", "请输入搜索词"); return; }
  if (btn) { btn.disabled = true; btn.textContent = "搜索中…"; }
  renderMarketProgress([{ text: `正在搜索「${q}」…`, kind: "info" }]);
  try {
    const res = await runCli(["--market", "search", "--market-query", q, "--format", "json"]);
    if (!res || res.code !== 0) { appendMarketProgress((res && res.stderr) || "搜索失败", "err"); return; }
    const data = JSON.parse(res.stdout || "{}");
    MARKET_DATA.installable = data.results || [];
    renderMarketResults(data);
  } catch (e) {
    appendMarketProgress("搜索返回无法解析", "err");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "搜索"; }
  }
}

function renderMarketResults(data) {
  renderMarketProgress([]);
  const results = data.results || [];
  if (!results.length) { appendMarketProgress(data.reason || "未找到匹配技能", "warn"); return; }
  results.forEach((r) => {
    appendMarketProgress(`${r.package}　${r.installs}`, "ok");
  });
  renderMarketInstallButtons(results);
}

function renderMarketInstallButtons(results) {
  const el = $("market-results");
  if (!el) return;
  el.innerHTML = "";
  results.forEach((r) => {
    const row = document.createElement("div");
    row.className = "market-result";
    const label = document.createElement("span");
    label.textContent = r.package;
    const btn = document.createElement("button");
    btn.className = "btn-soft";
    btn.dataset.action = "market-install";
    btn.dataset.pkg = r.package;
    btn.textContent = "安装";
    row.appendChild(label);
    row.appendChild(btn);
    el.appendChild(row);
  });
}

async function runMarketCheck(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "检查中…"; }
  renderMarketProgress([{ text: "正在检查更新（只读，不会修改任何技能）…", kind: "info" }]);
  try {
    const res = await runCli(["--market", "check", "--format", "json"]);
    if (!res || res.code !== 0) { appendMarketProgress((res && res.stderr) || "检查失败", "err"); return; }
    const data = JSON.parse(res.stdout || "{}");
    MARKET_DATA.updates = data.updates || [];
    renderMarketUpdates(data);
  } catch (e) {
    appendMarketProgress("检查返回无法解析", "err");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "检查更新"; }
  }
}

// 逐技能渲染检查结果：状态 + 远端提交时间，可升级项带按钮。
function renderMarketUpdates(data) {
  renderMarketProgress([]);
  const s = data.summary || {};
  appendMarketProgress(
    `共 ${s.total || 0}：有更新 ${s.outdated || 0} / 已最新 ${s.current || 0} / 无法检测 ${s.unknown || 0}`,
    "info");
  (data.updates || []).forEach((u) => {
    const tag = u.state === "outdated" ? "有更新"
              : u.state === "current" ? "已最新" : "无法检测";
    const kind = u.state === "outdated" ? "warn"
               : u.state === "current" ? "ok" : "info";
    const when = u.remote_commit ? `　远端 ${u.remote_commit}` : (u.note ? `　${u.note}` : "");
    appendMarketProgress(`${u.name}：${tag}${when}`, kind);
    if (u.state === "outdated") renderMarketUpgradeButton(u);
  });
}

function renderMarketUpgradeButton(u) {
  const el = $("market-results");
  if (!el) return;
  const btn = document.createElement("button");
  btn.className = "btn-soft";
  btn.dataset.action = "market-upgrade";
  btn.dataset.name = u.name;
  btn.textContent = `升级 ${u.name}`;
  el.appendChild(btn);
}

// 安装必须二次确认：市场技能来自第三方仓库，存在供应链风险。
function confirmMarketInstall(pkg) {
  if (!pkg) return;
  const ok = window.confirm(`确定要安装「${pkg}」吗？\n\n来源为第三方仓库，安装前请确认可信。`);
  if (!ok) { appendMarketProgress(`已取消安装 ${pkg}`, "info"); return; }
  runMarketInstall(pkg);
}

function confirmMarketUpgrade(name) {
  if (!name) return;
  const ok = window.confirm(`确定要升级「${name}」吗？\n\n将拉取上游最新版本并覆盖本地内容。`);
  if (!ok) { appendMarketProgress(`已取消升级 ${name}`, "info"); return; }
  runMarketUpgrade(name);
}
```

并在 `page-skills` 区块内、`skills-list` 之前插入面板容器：

```html
      <div id="market-panel" class="hidden">
        <div class="market-toolbar">
          <input type="text" id="market-query" placeholder="搜索技能市场" aria-label="搜索技能市场" />
          <button class="btn-soft" data-action="market-search">搜索</button>
          <button class="btn-soft" data-action="market-check">检查更新</button>
        </div>
        <div id="market-sources" class="market-lines"></div>
        <div id="market-progress" class="market-lines"></div>
        <div id="market-results" class="market-results"></div>
      </div>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dashboard_market_ui.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 全量回归**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿（原 615 + 新增约 38）

- [ ] **Step 6: 提交**

```bash
git add gui/dashboard.html tests/test_dashboard_market_ui.py
git commit -m "feat(skill-market): GUI 市场面板（逐技能进度 + 安装二次确认）"
```

---

## Task 8: 文档与版本

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/decisions/决策记录-待决问题定案.md`

- [ ] **Step 1: 更新 CHANGELOG**

在 `## [Unreleased]` 的 `### 新增` 段追加：

```markdown
- **技能市场接入（FEAT-9）**：接入 skills.sh 社区技能库，提供只读的源可用性、
  已装清单（含来源仓库与装/更新时间）、搜索与版本更新检测，以及经二次确认的
  在线安装/升级；GUI 以逐技能进度展示。检查更新为纯只读实现，**不调用
  `npx skills check`**（该命令名为检查、实为升级，实测一次更新 41 个技能）。
  装到 `~/.agents/skills` 即已落在统一库（该目录是
  `~/.skills-manager/skills` 的符号链接），故无需额外归一机制。
```

- [ ] **Step 2: 追加减策记录**

在 `docs/decisions/决策记录-待决问题定案.md` 末尾（D18 之后）追加：

```markdown
## D19 技能市场接入的源取舍与只读边界（已执行）

**源取舍**：三个候选源中只实现 skills.sh。QwenWork 官方市场需 `mcp__qw-builtin__`
工具（本机 `~/.dsh/mcp.json` 只有 hermes / image-vision，不存在该工具）；企业
技能市场 MCP 未探测到。两者在界面标注「未检测到」并给出原因，不报错、不静默省略。

**只读边界（实测事故推出）**：`npx skills check` 名为检查、实为升级——本机一次
调用即更新 41 个技能，且该命令未出现在 `--help` 列表中；`npx skills update` 亦无
`--dry-run`。因此「检查更新」自行实现为双重只读通道：GitHub API 为主（未鉴权会
限流，支持 `GITHUB_TOKEN`），限流或失败时降级为临时浅克隆比对。测试中加静态护栏，
断言 `core/skill_market.py` 源码不出现 `check` / `update` 子命令。

**归一无需额外机制**：`~/.skills-manager/skills` 是唯一实体，`~/.agents/skills`、
`~/.codex/skills`、`~/.dsh/skills`、`~/.hermes/skills` 均为指向它的符号链接
（`ls -ldi` 实测）。故 `npx skills add -g` 落到 `~/.agents/skills` 时已直接落在统一库。
```

- [ ] **Step 3: 提交**

```bash
git add CHANGELOG.md docs/decisions/决策记录-待决问题定案.md
git commit -m "docs(skill-market): CHANGELOG 与 D19 决策记录"
```

---

## 收尾验收

- [ ] `python3 -m pytest tests/ -q` 全绿
- [ ] `python3 scan.py --market sources` 三源输出正确（skills.sh 可用，另两个带原因）
- [ ] `python3 scan.py --market check` 前后统一库 mtime 快照一致（只读证明）
- [ ] `python3 scan.py --market search --market-query react` 有真实结果
- [ ] GUI：Skills 页出现「技能市场」按钮；点开后搜索、检查更新、逐技能进度可见；
      安装按钮弹确认框
- [ ] `cargo tauri build` 通过并安装（GUI 是嵌入式的，必须重编译）
- [ ] `git push origin develop`

---

## 自检记录

**Spec 覆盖**：市场源取舍→Task 1；已装清单/lock 解析→Task 2；搜索与清洗→Task 3；
只读更新检测（双通道、三态、禁破坏性命令）→Task 4；CLI 出口→Task 5；
在线升级（确认+装后校验）→Task 6；GUI 逐技能进度→Task 7；文档→Task 8。
spec 的「安全边界」六条分别落在 Task 3/4/6 的护栏与 Task 7 的确认函数。

**类型一致性**：`_run_npx(args, timeout)` 在 Task 1 定义，Task 3/6 复用；
`list_installed(lock_path, skills_dir)` Task 2 定义、Task 4 调用时用默认参数；
`check_updates(only=None)` 返回 `{updates, summary}`，Task 5/7 消费同一形状；
`plan_install/plan_upgrade/execute_plan` Task 6 定义，GUI 经 CLI 调用。

**已知未覆盖**：批量升级的 GUI 入口只做了单技能按钮（`market-upgrade`）；
批量 `plan_upgrade(names)` 已在 Task 6 实现并有测试，GUI 接线留待用户实际需要时再加。
