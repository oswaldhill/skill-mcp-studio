"""iCloud 完整备份（macOS 专属）。

## 与 config_porter 的分工（不要混用）

| 能力 | 用途 | 密钥 | 位置 | 版本 |
| --- | --- | --- | --- | --- |
| ``config_porter`` 导出 | 换机 / 团队分享 | **脱敏** | 任意路径或 ``icloud`` 别名 | 单份，覆盖写 |
| 本模块备份 | 灾难恢复（磁盘坏 / 换机 / 误删） | **原样含密钥** | iCloud Drive ``backups/`` | 按时间戳多份，保留 7 份 |

两者刻意不合并：导出的产物可能被分享，必须脱敏；备份的产物只给自己恢复，
脱敏会让「恢复完还要手补密钥」——那不是备份。

## 备份范围（仅配置与数据，不含技能内容）

- ``config.yaml``（trunk，唯一事实来源）
- ``data/local_overrides.yaml``（个人拓扑 overlay）
- ``data/discovered_tools.yaml``（自动发现客户端）
- ``data/git_sources.yaml``（技能来源）
- ``data/market_sources.yaml``（市场源，存在才备）
- ``data/github_token``（仓库 token，存在才备；恢复时保持 0600）

不含：技能目录（体积大，且可从市场/仓库重装）、``last_snapshot.yaml``（派生
数据，可由审计重建）、``market_check_cache.json``（缓存）。

## 存储形态

单文件 JSON，文件名 ``backup-<YYYYmmdd-HHMMSS>.json``：``files`` 键是
「相对仓库根的路径 → 文件原文」。选 JSON 而不是 zip 的理由：备份只有几十 KB，
zip 会引入解压路径穿越的校验负担；JSON 可直接肉眼审阅与 diff。

## 安全

- **内容加密**（schema 2，2026-11-16 用户要求）：备份含明文密钥，落盘必须是密文。
  文件名保持可读（用户明确「名称可以识别，只是内容不可识别」），内容用
  AES-256-CBC + PBKDF2 加密，密钥存 macOS 登录钥匙串
  （service ``io.skillmcp.studio.cloud-backup``）。用系统 ``openssl`` 而不是引入
  ``cryptography`` 依赖 —— 本项目的依赖刻意保持极小（PyYAML + certifi）。
- 早期 schema 1 的**明文**备份仍可读取（向后兼容），恢复逻辑按 schema 分流。
- 恢复只写白名单内的文件，路径必须是相对仓库根、且不含 ``..``；
- 恢复前对每个将被覆盖的文件生成 ``.bak-<ts>`` 备份（沿用 ``file_atomic`` 约定）。
- 密钥丢失（换机 / 清空钥匙串）时无法解密：明确报错并指向「导出配置」迁移，
  而不是给出含糊的解析失败。
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from file_atomic import atomic_write, backup_path

BACKUP_KIND = "skill-mcp-studio-cloud-backup"
# schema 2（2026-11-16）：内容加密；schema 1 是早期明文格式，仍可读取。
BACKUP_SCHEMA_VERSION = 2
LEGACY_PLAINTEXT_SCHEMA = 1
ENCRYPTION_ALG = "aes-256-cbc-pbkdf2"
# 只保留最新一份（2026-11-16 用户要求）：多版本对灾难恢复没有实际收益，
# 却让 iCloud 里长期堆着含凭据的历史副本。
DEFAULT_KEEP = 1
# 加密密钥的钥匙串坐标（复用 auth_secret 的封装，不重复实现 security 调用）。
_KEYCHAIN_SERVICE = "io.skillmcp.studio.cloud-backup"
_KEYCHAIN_ACCOUNT = "default"
# 环境变量覆盖（测试与无人值守场景用；优先级高于钥匙串）。
_KEY_ENV = "SMS_BACKUP_KEY"

ICLOUD_BACKUP_REL = os.path.join(
    "Library", "Mobile Documents", "com~apple~CloudDocs",
    "skill-mcp-studio", "backups",
)

# 备份白名单：相对仓库根的路径。顺序即恢复顺序（config.yaml 先落）。
BACKUP_FILES = (
    "config.yaml",
    os.path.join("data", "local_overrides.yaml"),
    os.path.join("data", "discovered_tools.yaml"),
    os.path.join("data", "git_sources.yaml"),
    os.path.join("data", "market_sources.yaml"),
    os.path.join("data", "github_token"),
)
# 可选文件：不存在时跳过（首次使用可能还没有）。
OPTIONAL_FILES = {
    os.path.join("data", "market_sources.yaml"),
    os.path.join("data", "github_token"),
}
# 恢复时保持的权限（github_token 是凭据，其余按常规 0644）。
_SECRET_FILES = {os.path.join("data", "github_token")}


def _repo_root() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )


def backup_root() -> str:
    """iCloud 备份根目录。

    非 macOS 显式报错（与 ``config_porter.resolve_port_path`` 的 ``icloud``
    别名同一纪律：不静默写到错误位置）。
    """
    if sys.platform != "darwin":
        raise ValueError(
            "iCloud 备份仅在 macOS 可用（iCloud Drive 路径）；"
            "其他平台请用 --export-config 导出到自定义路径"
        )
    return os.path.join(os.path.expanduser("~"), ICLOUD_BACKUP_REL)


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _app_version() -> str:
    try:
        with open(os.path.join(_repo_root(), "version.json"), "r", encoding="utf-8") as fh:
            return str(json.load(fh).get("version", "unknown"))
    except (OSError, ValueError):
        return "unknown"


def _resolve_key(*, create: bool) -> str:
    """取备份加密密钥：环境变量优先，其次登录钥匙串；``create`` 时缺失则生成。

    为什么用钥匙串而不是「固定密钥」：备份里含明文 ``github_token`` 等凭据，
    固定密钥等于没有加密（源码就是密钥）。钥匙串由系统按登录用户保护，
    是本机能做到的最低成本方案。

    失败语义刻意区分「读不到」与「没有」：读不到（钥匙串被拒/超时）时给出
    可诊断的原因；没有且不要求创建时，明确告诉用户这份备份无法解密、应改用
    导出迁移 —— 而不是让后续解密报一个含糊的 padding error。
    """
    env_key = (os.environ.get(_KEY_ENV) or "").strip()
    if env_key:
        return env_key

    from auth_secret import keychain_read, keychain_write

    try:
        existing = keychain_read(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
        if existing:
            return existing
    except RuntimeError as exc:
        if not create:
            raise ValueError(
                f"无法读取备份密钥（{exc}）。换机器或清空过钥匙串的备份无法解密，"
                "请改用「导出配置」迁移。"
            ) from exc
        # 创建路径继续往下走：可能是条目不存在，由 keychain_write 新建。

    if not create:
        raise ValueError(
            "本机钥匙串里没有备份密钥，这份备份无法解密。"
            "换机器或清空过钥匙串后请改用「导出配置」迁移。"
        )

    key = secrets.token_hex(32)
    keychain_write(_KEYCHAIN_SERVICE, key, _KEYCHAIN_ACCOUNT)
    return key


def _openssl(args: list, data: str, key: str) -> str:
    """跑一次 ``openssl enc``，密码经环境变量传入（不进进程参数）。"""
    env = {**os.environ, _KEY_ENV: key}
    proc = subprocess.run(
        ["openssl", "enc", *args, "-pass", f"env:{_KEY_ENV}"],
        input=data, capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        reason = (proc.stderr or "").strip() or f"退出码 {proc.returncode}"
        raise ValueError(f"openssl 失败：{reason}")
    return proc.stdout


def _encrypt(plaintext: str, key: str) -> str:
    return _openssl(["-aes-256-cbc", "-pbkdf2", "-salt", "-base64"], plaintext, key)


def _decrypt(ciphertext: str, key: str) -> str:
    return _openssl(["-d", "-aes-256-cbc", "-pbkdf2", "-base64"], ciphertext, key)


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def _collect_files() -> Dict[str, str]:
    """读取白名单文件，返回「相对路径 → 原文」。缺失的可选文件跳过。"""
    root = _repo_root()
    files: Dict[str, str] = {}
    for rel in BACKUP_FILES:
        content = _read_text(os.path.join(root, rel))
        if content is None:
            if rel in OPTIONAL_FILES:
                continue
            raise ValueError(f"备份源文件缺失或不可读：{rel}")
        files[rel.replace(os.sep, "/")] = content
    return files


def create_backup(*, dry_run: bool = False) -> Dict[str, Any]:
    """把配置与数据打包成一份 iCloud 备份。

    返回字段：``status`` / ``path`` / ``files``（条数）/ ``bytes`` / ``message``。
    """
    root = backup_root()
    files = _collect_files()
    payload = {
        "kind": BACKUP_KIND,
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "app_version": _app_version(),
        "files": files,
    }
    # 明文只存在于内存：落盘的是信封（kind / schema / encoding / payload 密文）。
    # 文件名仍带可读时间戳（用户明确要求「名称可以识别」），排序也依赖它。
    plain = json.dumps(payload, ensure_ascii=False, indent=2)
    envelope = {
        "kind": BACKUP_KIND,
        "schema_version": BACKUP_SCHEMA_VERSION,
        "encoding": ENCRYPTION_ALG,
        "payload": _encrypt(plain, _resolve_key(create=True)),
    }
    rendered = json.dumps(envelope, ensure_ascii=False, indent=2) + "\n"
    out_path = os.path.join(root, f"backup-{_now_stamp()}.json")

    if dry_run:
        return {
            "status": "dry-run",
            "path": out_path,
            "files": len(files),
            "bytes": len(rendered.encode("utf-8")),
            "message": f"[dry-run] 将备份 {len(files)} 个文件到 {out_path}",
        }

    os.makedirs(root, exist_ok=True)
    atomic_write(out_path, rendered, 0o600)  # 含密钥：仅属主可读

    # 只保留最新一份：写完立刻清理旧份，避免 iCloud 里长期堆着含凭据的历史副本。
    # 失败不阻断备份本身（备份已落盘），但要把原因带回给调用方。
    pruned = 0
    prune_error = ""
    try:
        pruned = prune_backups(keep=DEFAULT_KEEP)["removed"]
    except (OSError, ValueError) as exc:
        prune_error = str(exc)

    message = (
        f"已备份 {len(files)} 个文件到 iCloud（{len(rendered.encode('utf-8'))} 字节，已加密）"
        "。解密密钥存放在本机登录钥匙串，换机后需改用「导出配置」迁移。"
    )
    if pruned:
        message += f" 已清理 {pruned} 份旧备份（只保留最新一份）。"
    if prune_error:
        message += f" 旧备份清理失败：{prune_error}"

    return {
        "status": "ok",
        "path": out_path,
        "files": len(files),
        "bytes": len(rendered.encode("utf-8")),
        "pruned": pruned,
        "message": message,
    }


def _parse_backup_name(name: str) -> Optional[str]:
    """从 ``backup-YYYYmmdd-HHMMSS.json`` 提取时间戳（用于排序）。"""
    if not (name.startswith("backup-") and name.endswith(".json")):
        return None
    stamp = name[len("backup-"):-len(".json")]
    try:
        datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return stamp


def list_backups() -> List[Dict[str, Any]]:
    """列出 iCloud 上的备份，按时间倒序（新的在前）。"""
    root = backup_root()
    if not os.path.isdir(root):
        return []
    found: List[Dict[str, Any]] = []
    for name in os.listdir(root):
        stamp = _parse_backup_name(name)
        if stamp is None:
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        info = os.stat(full)
        found.append(
            {
                "id": name,
                "path": full,
                "stamp": stamp,
                "size": info.st_size,
                "mtime": info.st_mtime,
                "mtime_text": datetime.fromtimestamp(info.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    # 以文件名时间戳为主键：它是写入时生成的单调序号，不受文件系统 mtime
    # 分辨率影响（与 config_backups.list_config_backups 同一教训）。
    found.sort(key=lambda item: (item["stamp"], item["path"]), reverse=True)
    return found


def _load_backup(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise ValueError(f"备份文件不存在：{path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError(f"备份文件无法解析为 JSON：{exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != BACKUP_KIND:
        raise ValueError("不是 skill-mcp-studio 的 iCloud 备份文件（kind 不符）")

    version = data.get("schema_version")
    if version == BACKUP_SCHEMA_VERSION:
        # schema 2：信封格式，内容加密。
        if data.get("encoding") != ENCRYPTION_ALG:
            raise ValueError(f"不支持的备份编码：{data.get('encoding')!r}")
        payload = data.get("payload")
        if not isinstance(payload, str) or not payload.strip():
            raise ValueError("备份文件缺少加密内容（payload 为空）")
        try:
            inner = json.loads(_decrypt(payload, _resolve_key(create=False)))
        except ValueError as exc:
            # 包含「密钥取不到」与「解密失败」两类，都指向同一处置：换导出迁移。
            raise ValueError(f"备份解密失败（密钥不匹配或文件损坏）：{exc}") from exc
        if not isinstance(inner, dict):
            raise ValueError("解密后的备份内容不是对象")
        data = inner
    elif version != LEGACY_PLAINTEXT_SCHEMA:
        raise ValueError(
            f"不支持的备份 schema_version：{version!r}"
            f"（当前支持 {BACKUP_SCHEMA_VERSION}，兼容早期明文 {LEGACY_PLAINTEXT_SCHEMA}）"
        )

    if not isinstance(data.get("files"), dict) or not data["files"]:
        raise ValueError("备份文件里没有可恢复的文件")
    return data


def _safe_target(rel: str) -> str:
    """把备份里的相对路径解析为仓库内绝对路径，拒绝越界。"""
    if rel not in {p.replace(os.sep, "/") for p in BACKUP_FILES}:
        raise ValueError(f"备份里含白名单之外的文件：{rel}")
    root = _repo_root()
    target = os.path.normpath(os.path.join(root, rel))
    if not target.startswith(root + os.sep):
        raise ValueError(f"备份路径越界：{rel}")
    return target


def restore_backup(backup_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """按备份恢复配置与数据。

    ``backup_id`` 可以是文件名（如 ``backup-20261116-113000.json``）或绝对路径。
    写前对每个目标文件生成 ``.bak-<ts>``，恢复失败时可回退。
    """
    root = backup_root()
    path = backup_id if os.path.isabs(backup_id) else os.path.join(root, backup_id)
    data = _load_backup(path)
    files: Dict[str, str] = data["files"]

    targets: List[Dict[str, Any]] = []
    for rel, content in files.items():
        target = _safe_target(rel)
        targets.append(
            {
                "rel": rel,
                "target": target,
                "content": content,
                "exists": os.path.isfile(target),
            }
        )

    if dry_run:
        return {
            "status": "dry-run",
            "path": path,
            "files": [t["rel"] for t in targets],
            "message": f"[dry-run] 将恢复 {len(targets)} 个文件（写前各自备份）",
        }

    restored: List[str] = []
    backups: List[str] = []
    for item in targets:
        target = item["target"]
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if item["exists"]:
            # backup_path 只生成路径名，复制必须自己做 —— 只调不复制会得到
            # 「报了备份路径但文件不存在」的假备份（config_porter 同款教训）。
            bak = backup_path(target)
            shutil.copy2(target, bak)
            backups.append(bak)
        mode = 0o600 if item["rel"] in {p.replace(os.sep, "/") for p in _SECRET_FILES} else 0o644
        atomic_write(target, item["content"], mode)
        restored.append(item["rel"])

    return {
        "status": "ok",
        "path": path,
        "files": restored,
        "backups": backups,
        "message": (
            f"已从备份恢复 {len(restored)} 个文件"
            + (f"（恢复前已备份 {len(backups)} 个原文件）" if backups else "")
        ),
    }


def prune_backups(*, keep: int = DEFAULT_KEEP, dry_run: bool = False) -> Dict[str, Any]:
    """只保留最近 ``keep`` 份备份，删除更早的。"""
    if keep < 1:
        raise ValueError("keep 必须 >= 1")
    items = list_backups()
    victims = items[keep:]
    if dry_run:
        return {
            "status": "dry-run",
            "removed": len(victims),
            "kept": len(items) - len(victims),
            "paths": [v["path"] for v in victims],
            "message": f"[dry-run] 将删除 {len(victims)} 份旧备份，保留 {len(items) - len(victims)} 份",
        }
    removed: List[str] = []
    for item in victims:
        try:
            os.remove(item["path"])
            removed.append(item["path"])
        except OSError:
            continue
    return {
        "status": "ok",
        "removed": len(removed),
        "kept": len(items) - len(removed),
        "paths": removed,
        "message": f"已删除 {len(removed)} 份旧备份，保留 {len(items) - len(removed)} 份",
    }


def backup_status() -> Dict[str, Any]:
    """汇总：根目录、备份份数、总字节、最近一份时间（GUI 只读展示用）。"""
    try:
        root = backup_root()
    except ValueError as exc:
        return {"available": False, "reason": str(exc), "root": "", "count": 0,
                "bytes": 0, "latest": None}
    items = list_backups()
    return {
        "available": True,
        "root": root,
        "count": len(items),
        "bytes": sum(item["size"] for item in items),
        "latest": items[0] if items else None,
        # 一并返回完整列表：GUI 一次调用即可渲染「状态行 + 最近备份」，
        # 不必再发一次 --list-icloud-backups。
        "items": items,
    }