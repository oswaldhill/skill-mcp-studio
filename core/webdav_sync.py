"""WebDAV 远程同步（v0.31.1，#3 后半）。

## 同步什么

只同步**个人配置层**，不碰 trunk、不碰技能包本体：

| 文件 | 是否同步 | 理由 |
|---|---|---|
| ``data/local_overrides.yaml`` | ✅ | 个人端点拓扑 |
| ``data/market_sources.yaml`` | ✅ | 市场源偏好 |
| ``data/skill_versions.json`` | ✅ | 版本基准（多设备一致） |
| ``data/discovered_tools.yaml`` | ✅ | 自动发现清单 |
| ``data/github_token`` | ❌ | 凭据不同步，且各设备可独立配置 |
| ``data/webdav_credential`` | ❌ | 凭据本身不能被同步 |
| ``data/skill_backups/`` | ❌ | 体积大且是本机回滚用途 |
| 技能包目录 | ❌ | 已由 git / 各设备自管 |

## 通道纪律

沿用 ``data/github_token`` 的模式：**凭据走文件**，因为 GUI 从 launchd
启动读不到 shell 环境变量。凭据与配置分两个文件：

- ``data/webdav_config.yaml``：``url``（远端根，如
  ``https://dav.example.com/remote.php/dav/files/me/studio``）+ ``enabled``
- ``data/webdav_credential``：``user:pass`` 单行（0600 权限）

## 冲突策略（不做自动合并）

YAML/JSON 的语义合并容易产生「看起来对但语义错」的结果，本版走
**显式覆盖 + 双向备份**：

- **push**：先把远端现值下载存本地 ``<file>.remote-<时间戳>``，再上传本地
- **pull**：先把本地现值另存 ``<file>.bak-<时间戳>``，再下载远端覆盖
- 冲突（两端都改）不自动解决，但**每次覆盖都留了两边的旧值**，
  用户可手工比对后重推/重拉

## 网络

用 ``curl``（与 ``skill_market._http_get_text`` 同因：本机 Python 的
urllib 拿不到根证书）。仅用 GET / PUT / PROPFIND 三个动词，不做递归遍历
目录（文件清单由本地常量决定，避免远端被写入意外路径）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_UA = "skill-mcp-studio-webdav/1.0"

# 同步清单（相对 data/）。顺序即上传顺序，pull 时也按此顺序覆盖。
SYNC_FILES: List[str] = [
    "local_overrides.yaml",
    "market_sources.yaml",
    "discovered_tools.yaml",
    "skill_versions.json",
]

CONFIG_NAME = "webdav_config.yaml"
CRED_NAME = "webdav_credential"


def _root() -> Path:
    """仓库根（独立成函数便于测试替换）。"""
    return Path(__file__).resolve().parents[1]


def _data_dir() -> Path:
    return _root() / "data"


def config_path() -> Path:
    return _data_dir() / CONFIG_NAME


def credential_path() -> Path:
    return _data_dir() / CRED_NAME


# ── 配置与凭据读写 ──────────────────────────────────────────────


def read_config() -> Dict[str, Any]:
    """读 WebDAV 配置（缺文件/坏 YAML 一律返回空 dict，不抛异常）。"""
    path = config_path()
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_url(url: str) -> Dict[str, Any]:
    """设置远端根 URL。空字符串表示清除。"""
    import yaml

    clean = (url or "").strip().rstrip("/")
    path = config_path()
    if not clean:
        if path.exists():
            path.unlink()
        return {"ok": True, "cleared": True}

    if not (clean.startswith("https://") or clean.startswith("http://")):
        return {"ok": False, "reason": "URL 必须以 https:// 或 http:// 开头"}
    if clean.startswith("http://"):
        # 明文传输凭据是安全问题，但内网自建 DAV 常见；这里只警告不阻断
        note = "警告：http:// 会明文传输凭据，建议改用 https://"
    else:
        note = ""

    payload = {"url": clean, "enabled": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# WebDAV 远程同步配置（v0.31.1）\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "url": clean, "note": note}


def read_credential() -> str:
    """读 ``user:pass``（不存在返回空串）。"""
    path = credential_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_credential(value: str) -> Dict[str, Any]:
    """设置 WebDAV 凭据（``user:pass``）。空字符串表示清除。

    文件权限设 0600：凭据不该被同机其他用户读到。
    """
    path = credential_path()
    raw = (value or "").strip()
    if not raw:
        if path.exists():
            path.unlink()
        return {"ok": True, "cleared": True}
    if ":" not in raw:
        return {"ok": False, "reason": "凭据格式应为 user:pass"}
    user, _, _ = raw.partition(":")
    if not user:
        return {"ok": False, "reason": "用户名不能为空"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return {"ok": True, "user": user, "masked": _mask_credential(raw)}


def _mask_credential(raw: str) -> str:
    """脱敏：只露用户名与密码末 2 位。"""
    user, _, secret = (raw or "").partition(":")
    if not secret:
        return user or ""
    tail = secret[-2:] if len(secret) > 2 else "*" * len(secret)
    return f"{user}:***{tail}"


def status() -> Dict[str, Any]:
    """只读状态：配置是否完整、凭据是否存在（不泄露内容）。"""
    cfg = read_config()
    url = str(cfg.get("url") or "")
    cred = read_credential()
    return {
        "kind": "webdav-status",
        "configured": bool(url and cred),
        "url": url,
        "has_credential": bool(cred),
        "credential": _mask_credential(cred) if cred else "",
        "files": [f for f in SYNC_FILES if (_data_dir() / f).is_file()],
        "missing": [f for f in SYNC_FILES if not (_data_dir() / f).is_file()],
    }


# ── 网络动作 ────────────────────────────────────────────────────


def _curl(args: List[str], timeout: int = 60) -> Tuple[Optional[bytes], int, str]:
    """跑 curl，返回 (body, status, err)。只有 curl 可用（同 skill_market）。"""
    curl = shutil.which("curl")
    if not curl:
        return None, 0, "未找到 curl"
    try:
        proc = subprocess.run(
            [curl, "-sS", "--max-time", str(timeout), *args],
            capture_output=True, timeout=timeout + 10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, 0, str(exc)
    err = proc.stderr.decode("utf-8", "replace").strip()
    return proc.stdout, proc.returncode, err


def _auth_args() -> List[str]:
    cred = read_credential()
    return ["-u", cred] if cred else []


def _file_url(name: str) -> str:
    base = str(read_config().get("url") or "").rstrip("/")
    return f"{base}/{name}"


def _http_status(url: str, *, method: str = "GET") -> int:
    """取状态码（HEAD 或 GET 的 -w 输出）。"""
    args = _auth_args() + ["-o", "/dev/null", "-w", "%{http_code}"]
    if method == "HEAD":
        args.insert(0, "-I")
    body, code, err = _curl(args + [url], timeout=30)
    if code != 0 or body is None:
        return 0
    try:
        return int(body.decode("utf-8", "replace").strip() or 0)
    except ValueError:
        return 0


def check_remote() -> Dict[str, Any]:
    """探测远端可达性与认证（只读）。"""
    cfg = read_config()
    url = str(cfg.get("url") or "")
    if not url:
        return {"ok": False, "reason": "未配置远端 URL（先 --set-webdav-url）"}
    if not read_credential():
        return {"ok": False, "reason": "未配置凭据（先 --set-webdav-credential）"}
    status_code = _http_status(url.rstrip("/") + "/", method="HEAD")
    if status_code == 0:
        return {"ok": False, "reason": "无法连接远端（网络或 URL 错误）"}
    if status_code in (401, 403):
        return {"ok": False, "reason": f"认证失败（HTTP {status_code}），检查凭据"}
    # 判据只看「连通 + 认证」：DAV 服务对根目录的响应差异很大
    # （Nextcloud 给 207、部分实现 405 或 404 表示「目录存在但无索引」），
    # 用 >=400 一律判失败会把可用配置误报成不可用（实测踩到）。
    if status_code >= 500:
        return {"ok": False, "reason": f"远端服务异常（HTTP {status_code}）"}
    return {"ok": True, "http_status": status_code}


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def push(*, dry_run: bool = False) -> Dict[str, Any]:
    """本地 → 远端。上传前把远端现值存本地 ``<file>.remote-<时间戳>``。"""
    check = check_remote()
    if not check.get("ok"):
        return {"ok": False, "reason": check.get("reason"), "results": []}

    results: List[Dict[str, Any]] = []
    for name in SYNC_FILES:
        local = _data_dir() / name
        if not local.is_file():
            results.append({"file": name, "action": "skipped", "reason": "本地无此文件"})
            continue
        url = _file_url(name)
        # 先保远端旧值（存在才下载）
        if _http_status(url) == 200:
            if not dry_run:
                body, code, err = _curl(_auth_args() + ["-o", "-", url], timeout=60)
                if code == 0 and body is not None:
                    backup = local.with_name(f"{name}.remote-{_stamp()}")
                    try:
                        backup.write_bytes(body)
                    except OSError:
                        pass
        if dry_run:
            results.append({"file": name, "action": "would-upload",
                            "bytes": local.stat().st_size})
            continue
        body, code, err = _curl(
            _auth_args() + ["-T", str(local), url], timeout=120)
        if code == 0:
            results.append({"file": name, "action": "uploaded",
                            "bytes": local.stat().st_size})
        else:
            results.append({"file": name, "action": "failed", "reason": err or f"curl {code}"})
    ok = all(r["action"] in ("uploaded", "skipped", "would-upload") for r in results)
    return {"ok": ok, "results": results}


def pull(*, dry_run: bool = False) -> Dict[str, Any]:
    """远端 → 本地。覆盖前把本地现值另存 ``<file>.bak-<时间戳>``。"""
    check = check_remote()
    if not check.get("ok"):
        return {"ok": False, "reason": check.get("reason"), "results": []}

    results: List[Dict[str, Any]] = []
    for name in SYNC_FILES:
        url = _file_url(name)
        status_code = _http_status(url)
        if status_code == 404:
            results.append({"file": name, "action": "skipped", "reason": "远端无此文件"})
            continue
        if status_code != 200:
            results.append({"file": name, "action": "failed",
                            "reason": f"远端 HTTP {status_code}"})
            continue
        body, code, err = _curl(_auth_args() + ["-o", "-", url], timeout=120)
        if code != 0 or body is None:
            results.append({"file": name, "action": "failed", "reason": err or "下载失败"})
            continue
        if dry_run:
            results.append({"file": name, "action": "would-download", "bytes": len(body)})
            continue
        dest = _data_dir() / name
        if dest.is_file():
            backup = dest.with_name(f"{name}.bak-{_stamp()}")
            try:
                shutil.copy2(dest, backup)
            except OSError:
                pass
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(body)
        except OSError as exc:
            results.append({"file": name, "action": "failed", "reason": str(exc)})
            continue
        results.append({"file": name, "action": "downloaded", "bytes": len(body)})
    ok = all(r["action"] in ("downloaded", "skipped", "would-download") for r in results)
    return {"ok": ok, "results": results}
