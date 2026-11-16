"""Well-known 来源技能的更新检测。

**为什么需要这个模块**（2026-11-15 用户反馈）：飞书 `lark-*` 系列从
`open.feishu.cn/.well-known/skills/` 装来，不是 GitHub 仓库。旧代码里它们一律
落 `unknown`「无 GitHub 来源信息，无法比对」——25 个未知里占了 22 个。

上游 `npx skills update` 也不管这类：它把这些技能归为
`cannot be checked automatically (Well-known skill)`。也就是说**没有任何一方
在做这件事**，只能我们自己按协议去比对。

**端点形状**（实测 2026-11-15）::

    GET https://<host>/.well-known/skills/index.json
        → {"skills": [{"name": "...", "description": "...", "files": [...]}]}
    GET https://<host>/.well-known/skills/<name>/SKILL.md
        → SKILL.md 正文

**判定必须用内容哈希，不能用 files 清单**：实测 `lark-doc` 本地 44 个文件、
远端 index 只报了 16 个（清单不完整）。拿文件列表比对会把「本地比远端多」
误读成差异，或者反过来漏掉真正的更新。

**三条纪律**：
1. **查不成绝不当成没问题**：网络失败/404/本地无 SKILL.md 一律 `unknown`，
   绝不静默算 `current`（那正是本次要修的毛病）。
2. **只读**：只发 GET，绝不写盘、不自动升级。
3. **不发多余请求**：一个技能一次 GET，不遍历 references（那是升级动作）。
"""

from __future__ import annotations

import hashlib
import subprocess
from typing import Any, Callable, Dict, Optional, Set

_TIMEOUT = 25


def classify_source(record: Dict[str, Any]) -> Dict[str, Any]:
    """判断一条 lock 记录是不是 well-known 来源。

    返回 ``kind``: ``wellknown`` / ``github`` / ``other``。
    """
    source_type = str(record.get("sourceType") or "").strip().lower()
    if source_type in ("well-known", "wellknown", "well_known"):
        base = str(record.get("sourceBaseUrl") or "").strip()
        if not base:
            host = str(record.get("source") or "").strip()
            base = f"https://{host}" if host else ""
        return {"kind": "wellknown", "base_url": base.rstrip("/")}
    if source_type == "github":
        return {"kind": "github", "base_url": ""}
    return {"kind": "other", "base_url": ""}


def parse_index(payload: Any) -> Set[str]:
    """从 index.json 取出技能名集合。结构异常一律返回空集。"""
    if not isinstance(payload, dict):
        return set()
    items = payload.get("skills")
    if not isinstance(items, list):
        return set()
    names = set()
    for item in items:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return names


def _default_fetch(url: str) -> Optional[bytes]:
    """发 GET 取正文。失败返回 None（由调用方转成 unknown）。

    用 curl 而不是 urllib：本机 Python 的 urllib 拿不到根证书
    （实测 CERTIFICATE_VERIFY_FAILED），curl 走系统钥匙串可用 —— 这与
    `skill_market._http_get_json` 的取舍一致。
    """
    try:
        out = subprocess.run(
            ["curl", "-fsSL", "--max-time", str(_TIMEOUT), url],
            capture_output=True, timeout=_TIMEOUT + 5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def compare_skill(
    name: str,
    local_dir,
    *,
    fetch: Optional[Callable[[str], Optional[bytes]]] = None,
    base_url: str = "",
) -> Dict[str, Any]:
    """比对远端 SKILL.md 与本地内容。

    返回 ``{"state": "current"|"outdated"|"unknown", "detail": str,
    "remote_sha256": str, "local_sha256": str}``。
    """
    fetcher = fetch or _default_fetch
    base = (base_url or "").rstrip("/")
    local_file = local_dir / "SKILL.md" if local_dir else None

    if not local_file or not local_file.is_file():
        return {"state": "unknown", "detail": "本地缺少 SKILL.md，无法比对",
                "remote_sha256": "", "local_sha256": ""}

    try:
        local_body = local_file.read_bytes()
    except OSError:
        return {"state": "unknown", "detail": "本地 SKILL.md 读取失败",
                "remote_sha256": "", "local_sha256": ""}
    local_sha = hashlib.sha256(local_body).hexdigest()

    if not base:
        return {"state": "unknown", "detail": "缺少 well-known 站点地址",
                "remote_sha256": "", "local_sha256": local_sha}

    url = f"{base}/.well-known/skills/{name}/SKILL.md"
    try:
        remote_body = fetcher(url)
    except Exception as exc:                      # 网络层异常不得逃逸
        return {"state": "unknown", "detail": f"远端查询失败：{exc}",
                "remote_sha256": "", "local_sha256": local_sha}

    if not remote_body:
        return {"state": "unknown", "detail": "远端未返回内容（404 或网络失败）",
                "remote_sha256": "", "local_sha256": local_sha}

    remote_sha = hashlib.sha256(remote_body).hexdigest()
    if remote_sha == local_sha:
        return {"state": "current", "detail": "与远端内容一致",
                "remote_sha256": remote_sha, "local_sha256": local_sha}
    return {"state": "outdated", "detail": "远端 SKILL.md 与本地内容不同",
            "remote_sha256": remote_sha, "local_sha256": local_sha}
