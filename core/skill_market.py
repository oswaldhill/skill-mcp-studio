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

from paths import is_reserved_skill_dir

import paths
from tool_registry import which_with_fallback

# 这三个源来自本机 find-skills 技能的权威说明；A/C 在当前环境不可用，
# 但仍要在清单中呈现，让用户看到「为什么没有结果」而不是静默空白。
_SOURCE_SPECS = (
    ("skills.sh", "skills.sh 社区技能库", True),
    ("qwenwork", "QwenWork 官方市场", False),
    ("enterprise", "企业技能市场 MCP", False),
)

_NPX_TIMEOUT = 60

# GUI 壳（Finder 启动）继承 launchd 的最小 PATH（/usr/bin:/bin:/usr/sbin:/sbin），
# 裸名 `npx` 必然查不到，技能市场会恒报「未找到 npx」。这里复用
# tool_registry.which_with_fallback：PATH 优先，未命中再兜底 /opt/homebrew/bin
# 等常见安装位置——与 CLI 探测、Rust 侧 run_cli 的定位策略保持一致。


def _npx_env(npx: str) -> Dict[str, str]:
    """构造子进程环境：把 npx 所在目录**提到 PATH 首位**。

    npx 是 `#!/usr/bin/env node` 脚本，只用绝对路径启动仍会因 PATH 里没有
    node 而报 `env: node: No such file or directory`，故必须让其同目录可见。

    必须是**首位**而不是「并入某处」：``env node`` 取 PATH 里**第一个** node，
    而 npx 同目录那个才是与它配套的版本。早先写成 ``if npx_dir not in parts:
    parts.insert(0, npx_dir)``，当该目录已在 PATH 中（本机即如此）时不移动，
    于是 PATH 首项仍是别的目录 —— 若那里存在另一个 node（nvm/fnm/volta 装的
    常见如此），npx 会解析到**错误的 node 版本**。本机实测：``/opt/homebrew/bin``
    原本排在 PATH 第 9 位，首项 ``~/.mimocode/bin`` 下没有 node，属侥幸可用。
    现无论是否已存在都移到首位（已存在时先摘除再插入，避免重复项）。
    """
    env = os.environ.copy()
    npx_dir = str(Path(npx).parent)
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p and p != npx_dir]
    parts.insert(0, npx_dir)
    env["PATH"] = os.pathsep.join(parts)
    return env


def _run_npx(args: List[str], timeout: int = _NPX_TIMEOUT) -> Dict[str, Any]:
    """执行 `npx -y skills ...`，返回 {code, stdout, stderr}。不抛异常。"""
    npx = which_with_fallback("npx")
    if not npx:
        return {"code": 127, "stdout": "", "stderr": "npx not found"}
    try:
        proc = subprocess.run(
            [npx, "-y", "skills", *args],
            capture_output=True, text=True, timeout=timeout,
            env=_npx_env(npx),
        )
        return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": "timeout"}
    except OSError as exc:
        return {"code": 126, "stdout": "", "stderr": str(exc)}


def detect_backend() -> Dict[str, Any]:
    """探测 `npx skills` 可用性。缺失时降级，不抛异常。"""
    npx = which_with_fallback("npx")
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
    """市场源清单（v0.31.0 重构：走 market_sources 可配置模型）。

    用户定案（2026-10-22）：QwenWork / 企业 MCP **不是市场源**（它们是特定
    会话工具集成，概念错位）——从源列表移除。skills.sh 为默认源（可删改）；
    支持自定义 github-repo 源。skills-sh 类型的可用性取决于 npx 后端。
    """
    from market_sources import list_sources

    backend = detect_backend()
    configured, fallback, invalid = list_sources()
    out: List[Dict[str, Any]] = []
    for s in configured:
        entry = dict(s)
        if s["type"] == "skills-sh":
            entry["available"] = backend["available"]
            entry["reason"] = "" if backend["available"] else backend["reason"]
        else:
            # github-repo：可用性在更新检查时逐源验证（此处不预发请求）
            entry["available"] = True
            entry["reason"] = ""
        out.append(entry)
    return {
        "backend": backend,
        "sources": out,
        "fallback": fallback,
        "invalid": invalid,
    }


# 路径不在此处求值：模块级 ``Path.home()`` 常量会在 import 时定死、运行期
# 改不动（评审 P0-4）。统一走 ``paths`` 的访问器，每次调用重新解析。


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
    lock_path = Path(lock_path) if lock_path else paths.default_lock_path()
    skills_dir = Path(skills_dir) if skills_dir else paths.skills_dir()

    lock = _read_lock(lock_path)
    registered = lock.get("skills") or {}

    hashes = set()
    if skills_dir.is_dir():
        # 技能库根目录含 .git 等元数据目录，它们不是技能，必须排除。
        hashes = {
            d.name for d in skills_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
            and not is_reserved_skill_dir(d.name)
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


def _github_token() -> str:
    """GitHub API token：环境变量优先，回落 data/github_token 文件。

    文件通道（v0.31.0）的原因：GUI 从 Finder 启动时是 launchd 最小环境，
    **读不到 shell 的 ~/.zshrc 环境变量**——纯 env 配置对 GUI 无效。
    文件（gitignored，同 market_sources 模式）对 GUI/CLI 一致生效。
    """
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    try:
        path = Path(__file__).resolve().parents[1] / "data" / "github_token"
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _http_get_json(url: str, timeout: int = 20):
    """只读 GET。优先用 curl：本机 Python 的 urllib 拿不到根证书（实测
    CERTIFICATE_VERIFY_FAILED），而 curl 走系统钥匙串可用。失败返回 None。
    """
    token = _github_token()
    headers = ["-H", f"User-Agent: {_UA}", "-H", "Accept: application/vnd.github+json"]
    if token:
        headers += ["-H", f"Authorization: Bearer {token}"]
    curl = shutil.which("curl")
    if curl:
        try:
            proc = subprocess.run(
                [curl, "-sS", "-w", "\n%{http_code}", "--max-time", str(timeout),
                 *headers, url],
                capture_output=True, text=True, timeout=timeout + 10,
            )
            body, _, code = proc.stdout.rpartition("\n")
            try:
                status = int(code.strip())
            except ValueError:
                status = 0
            if proc.returncode == 0 and body.strip() and status == 200:
                try:
                    return json.loads(body), status
                except ValueError:
                    # 200 但正文不是 JSON：状态码已知，保留它，
                    # 不要与「连不上」混为一谈。
                    return None, status
            return None, status
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None, 0
    # 回退：无 curl 时试 urllib（可能因根证书而失败）。
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept": "application/vnd.github+json",
        })
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as exc:
        return None, exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None, 0


def _http_get_text(url: str, timeout: int = 20):
    """只读 GET 纯文本（raw.githubusercontent 返回 markdown 而非 JSON）。

    与 _http_get_json 同样优先 curl（系统证书可用）。返回 (text, status)。
    raw.githubusercontent 不计入 GitHub API 配额（实测 2026-10-23）。
    """
    token = _github_token()
    headers = ["-H", f"User-Agent: {_UA}"]
    if token:
        headers += ["-H", f"Authorization: Bearer {token}"]
    curl = shutil.which("curl")
    if not curl:
        return None, 0
    try:
        proc = subprocess.run(
            [curl, "-sSL", "-w", "\n%{http_code}", "--max-time", str(timeout),
             *headers, url],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        body, _, code = proc.stdout.rpartition("\n")
        try:
            status = int(code.strip())
        except ValueError:
            status = 0
        if proc.returncode == 0 and status == 200:
            return body, status
        return None, status
    except (subprocess.TimeoutExpired, OSError):
        return None, 0


def _remote_skill_version(owner: str, repo: str,
                          skill_path: Optional[str],
                          timeout: int = 20):
    """远端**技能包自身**的版本：拉该技能 SKILL.md 解析 frontmatter version。

    v0.31.0 修复（2026-10-23 用户实测）：多技能 monorepo（如
    larksuite/cli）的 repo tag 是**工具/仓库**版本（v1.0.98），不是技能包
    版本（SKILL.md 里 version: 1.0.0 长期不变）。拿 tag 比技能版本会
    永久误报「有更新」，且升级后仍不消失。

    返回 (version 或 None, 状态 ok / notfound / unavailable)。
    """
    if not skill_path:
        return None, "notfound"
    path = skill_path.lstrip("/")
    # HEAD 指向默认分支，避免硬编码 main/master
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
    text, status = _http_get_text(url, timeout)
    if status in (403, 429):
        return None, "unavailable"
    if text is None:
        return None, "notfound" if status == 404 else "unavailable"
    try:
        from skill_state import parse_frontmatter_text  # 复用 frontmatter 解析
        fm = parse_frontmatter_text(text)
        ver = fm.get("version")
        if ver is None or str(ver).strip() == "":
            return None, "notfound"
        return str(ver).strip(), "ok"
    except (ImportError, AttributeError, ValueError):
        return None, "unavailable"


def _remote_commit_time(owner: str, repo: str, path: Optional[str],
                        timeout: int = 20) -> Optional[str]:
    """主通道：GitHub API 取该路径最新提交时间。

    返回 (ISO8601 时间或 None, 状态)。状态取值 ok / rate_limited /
    no_commits / unavailable —— 限流必须与「仓库不存在」区分。
    """
    from urllib.parse import urlencode

    q = {"per_page": "1"}
    if path:
        q["path"] = path
    data, status = _http_get_json(
        _API.format(owner=owner, repo=repo) + "?" + urlencode(q), timeout
    )
    if status in (403, 429):
        # 未鉴权 GitHub API 每小时 60 次；命中限流时明确区分于「仓库不存在」，
        # 否则用户会把配额问题误读成技能来源失效。
        return None, "rate_limited"
    if data is None:
        return None, "unavailable"
    if not isinstance(data, list) or not data:
        return None, "no_commits"
    try:
        return data[0]["commit"]["committer"]["date"], "ok"
    except (KeyError, TypeError, IndexError):
        return None, "unavailable"


def _iso_lt(a: Optional[str], b: Optional[str]) -> bool:
    """字符串化的 ISO8601 可直接比较（同格式同长度）。"""
    return bool(a and b and a < b)


def check_updates(only: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
    """只读更新检测（v0.31.0 重构：版本号比对 + 缓存 + 新源模型）。

    三态：outdated / current / unknown。**绝不调用 `npx skills check` 或
    `npx skills update`** —— 前者名为检查、实为升级（实测一次调用即更新
    41 个技能）。本函数只发 HTTP GET，不写技能库（缓存文件除外）。

    比对基准（v0.31.0 变更）：**本地版本（SKILL.md frontmatter version:）
    vs 远端版本（GitHub latest release tag）**——此前用安装时间 vs 远端
    commit 时间，既不直观也不可靠。无来源信息的技能 → unknown（带 reason）。

    缓存：data/market_check_cache.json，TTL 1 小时；force=True 跳过。
    """
    # 缓存命中（非 force 且未过期）直接返回
    cached = _load_check_cache()
    if cached is not None and not force:
        payload = cached
        payload["cache_hit"] = True
        if only:
            wanted = set(only)
            payload["updates"] = [r for r in payload.get("updates", [])
                                  if r.get("name") in wanted]
            payload["summary"] = _recount(payload["updates"])
        return payload

    from market_sources import list_sources
    sources, _fb, _inv = list_sources()
    enabled = [s for s in sources if s.get("enabled", True)]
    github_sources = [s for s in enabled if s["type"] == "github-repo"]

    listing = list_installed()
    registered = [r for r in listing["installed"] if r.get("registered")]
    if only:
        wanted = set(only)
        registered = [r for r in registered if r["name"] in wanted]

    # v0.31.1 修复（用户实测「列表只显示 2 个有更新，一键升级弹框却 4 个」）：
    # 判定的候选必须是**真的落在统一库里**的技能。lock 里可能残留「目录早已
    # 不存在」的登记（本机实测 2 例：2026-04 装过、目录已删），它们没有内容
    # 可覆盖、也没有本地版本，却会走下面的「按上游提交时间」兜底被判成
    # outdated——于是检查结果比可见技能多出若干条：列表按磁盘目录生成、渲染
    # 不出这些行（没有「有更新」标签），而一键升级取的是检查结果全量，把它们
    # 一并算进去。这类登记本身就是「安装已失效」，单列 missing 才诚实：
    # 既能解释数量差异，也让用户看见有登记烂在 lock 里。
    # 只有**明确知道不在磁盘上**（on_disk is False）才算登记失效；未提供该
    # 字段的调用方/夹具按「已安装」处理 —— 少一个字段不该被误判成安装失效。
    judged = [r for r in registered if r.get("on_disk") is not False]
    ghosts = [r for r in registered if r.get("on_disk") is False]

    # 本地版本（SKILL.md frontmatter；D2 轨解析）
    from paths import skills_dir as _sd
    from skill_state import read_skill_meta
    local_versions = read_skill_meta(str(_sd()), [r["name"] for r in judged])

    counts = {"outdated": 0, "current": 0, "unknown": 0, "missing": 0}
    rows: List[Dict[str, Any]] = []
    for r in ghosts:
        # 不发任何网络请求：没有本地内容可比，远端查了也无处落地。
        rows.append(dict(r, state="missing", local_version=None,
                         remote_version=None, remote_time=None,
                         note="lock 有登记但统一库中无此目录（安装已失效，"
                              "无内容可升级；可重新安装或清理该登记）"))
        counts["missing"] += 1
    rate_limited = False
    no_source_hint = not github_sources and not any(
        parse_github_source(r.get("source_url")) for r in judged)
    for row in judged:
        name = row["name"]
        local = (local_versions.get(name) or {}).get("version")
        owner_repo = parse_github_source(row.get("source_url"))
        remote, reason = None, ""
        # v0.31.0：无本地 version 的技能回退「时间比对」——上游该技能路径
        # （skillPath）的最新 commit 时间 vs 本地 lock 的 updatedAt/installedAt。
        # 语义弱于版本号（commit 了但内容可能没变），note 必须标注判定依据。
        # 内容哈希（skillFolderHash）不比对：远端无对应 hash 可查（GitHub
        # API 不提供目录 hash 对比；raw 拉文件需多次请求且要处理 ref）。
        local_time = row.get("updated_at") or row.get("installed_at")
        skill_path = row.get("skill_path")
        if local is None and owner_repo and local_time and skill_path:
            state = "unknown"
            if rate_limited:
                reason = "GitHub API 配额已用尽，本轮跳过（可设 GITHUB_TOKEN 提升配额）"
            else:
                remote_time, status = _remote_commit_time(
                    owner_repo[0], owner_repo[1], skill_path)
                if status == "rate_limited":
                    rate_limited = True
                    reason = "GitHub API 配额已用尽（可设 GITHUB_TOKEN 提升配额）"
                elif remote_time and _iso_lt(local_time, remote_time):
                    state = "outdated"
                    reason = "按上游提交时间判定（本地无版本号）：该技能路径有新提交"
                elif remote_time:
                    state = "current"
                    reason = "按上游提交时间判定（本地无版本号）：该技能路径无新提交"
                else:
                    state = "unknown"
                    reason = "上游该路径无提交记录或查询失败"
            counts[state] += 1
            # remote_time 透传（v0.31.0：GUI「最新」tag 显示远端版本号或
            # 提交时间——用户需求「最新版需要显示最新版本是什么时间或者版本号」）
            rows.append(dict(row, state=state, local_version=local,
                             remote_version=None, remote_time=remote_time,
                             note=reason))
            continue

        if local is None:
            reason = "本地无版本号且无安装时间/路径信息，无法比对"
        elif not owner_repo:
            reason = "无 GitHub 来源信息，无法比对"
        elif rate_limited:
            reason = "GitHub API 配额已用尽，本轮跳过（可设 GITHUB_TOKEN 提升配额）"
        else:
            # v0.31.0 修复（2026-10-23 用户实测「升级多次仍显示有更新」）：
            # ① 先拉**远端该技能 SKILL.md 的 version**（同源比对）。多技能
            #    monorepo（如 larksuite/cli）的 repo tag 是工具版本（v1.0.98），
            #    技能包自身版本长期是 1.0.0——拿 tag 比技能版本会永久误报。
            # ② 远端 SKILL.md 无 version 字段时回退 repo tag（单技能仓库
            #    用 tag 标版本的场景）。
            # ③ 都没有则保持 unknown，由上方时间比对分支兜底（本地无版本时）。
            remote, skill_ver_state = _remote_skill_version(
                owner_repo[0], owner_repo[1], skill_path)
            if remote is not None:
                reason = ""  # 技能包级版本，语义与本地 version 同源
            else:
                remote, status = _remote_latest_version(owner_repo[0], owner_repo[1])
                if status == "rate_limited":
                    rate_limited = True
                    reason = "GitHub API 配额已用尽（可设 GITHUB_TOKEN 提升配额）"
                elif remote is None:
                    reason = "远端无技能版本号、无 release/tag"
                else:
                    reason = "按仓库 tag 判定（远端技能无 version 字段）"

        if remote is None or local is None:
            state = "unknown"
        elif _version_lt(local, remote):
            state = "outdated"
        else:
            state = "current"
        counts[state] += 1
        rows.append(dict(row, state=state, local_version=local,
                         remote_version=remote, note=reason))

    summary = {"total": len(rows), **counts}
    if rate_limited:
        summary["rate_limited"] = True
        summary["hint"] = "GitHub 未鉴权查询每小时 60 次；设 GITHUB_TOKEN 可提升配额"
    if no_source_hint and not rows:
        summary["hint"] = "无可用市场源且技能无来源信息；可在设置页配置市场源"
    payload = {
        "kind": "market-check",
        "checked_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "cache_hit": False,
        "updates": rows,
        "summary": summary,
    }
    # 限流结果不写缓存：限流是暂时状态（配额每小时重置），固化 1 小时
    # 会让用户在配额恢复后仍看到全 unknown（实测踩过：两轮检查烧光配额，
    # 第三轮 GUI 读到缓存的限流结果，误以为「没有可升级的技能」）。
    if not rate_limited:
        _save_check_cache(payload)
    else:
        payload["cache_ttl_note"] = "限流结果不缓存；配额每小时重置后重查即可"
    return payload


def _recount(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    # 状态集合必须与 check_updates 保持一致（含 v0.31.1 新增的 missing）。
    # 用 .get 兜底：将来再加状态时这里不会 KeyError 把整个检查炸掉。
    counts = {"outdated": 0, "current": 0, "unknown": 0, "missing": 0}
    for r in rows:
        state = r.get("state", "unknown")
        counts[state] = counts.get(state, 0) + 1
    return {"total": len(rows), **counts}


def _check_cache_path() -> "Path":
    # 缓存与 skill_versions.json 同目录（仓库 data/，gitignored）
    return Path(__file__).resolve().parents[1] / "data" / "market_check_cache.json"


def _load_check_cache() -> Optional[Dict[str, Any]]:
    """TTL 1 小时；过期/损坏/缺失返回 None。"""
    import time as _time
    try:
        raw = _check_cache_path().read_text(encoding="utf-8")
        data = json.loads(raw)
        checked = data.get("checked_at") or ""
        ts = __import__("datetime").datetime.fromisoformat(checked).timestamp()
        if _time.time() - ts > 3600:
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_check_cache(payload: Dict[str, Any]) -> None:
    try:
        path = _check_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    except OSError:
        pass  # 缓存写失败不影响检查结果


def _version_lt(a: str, b: str) -> bool:
    """语义化版本比较：a < b？解析失败退化为字符串不等比对。

    ``1.0`` vs ``1.0.1`` → True；``1.2.0`` vs ``1.10.0`` → True（数值比较，
    非字典序）；``v1.0`` 前缀容忍；非语义化（如 commit hash）退化为
    ``a != b`` 即视为有更新。
    """
    def _parse(v: str) -> Optional[tuple]:
        v = v.strip().lstrip("vV")
        parts = v.split(".")
        try:
            return tuple(int(x) for x in parts)
        except ValueError:
            return None
    pa, pb = _parse(a), _parse(b)
    if pa is not None and pb is not None:
        # 元组比较：1.0 < 1.0.1（长度不等时短的前缀小）——Python 元组序天然如此
        return pa < pb
    return a.strip() != b.strip()


def _remote_latest_version(owner: str, repo: str, timeout: int = 20):
    """GitHub latest release tag（v0.31.0：版本号比对取代 commit 时间）。

    优先 /releases/latest 的 tag_name；无 release 回落 /tags 首个。
    返回 (tag 或 None, 状态 ok / rate_limited / unavailable)。
    """
    data, status = _http_get_json(
        f"https://api.github.com/repos/{owner}/{repo}/releases/latest", timeout)
    if status in (403, 429):
        return None, "rate_limited"
    if isinstance(data, dict) and data.get("tag_name"):
        return str(data["tag_name"]), "ok"
    # 无 release：回落 tags（可能为空）
    data, status = _http_get_json(
        f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=1", timeout)
    if status in (403, 429):
        return None, "rate_limited"
    if isinstance(data, list) and data and data[0].get("name"):
        return str(data[0]["name"]), "ok"
    return None, "unavailable"
