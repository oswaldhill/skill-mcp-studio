"""配置导入/导出（v0.30.0 路线图 §4c P0#3：本地 + iCloud 先行）。

## 定位

换机器 / 团队分享时，配置分散在三处：trunk ``config.yaml``（版本受控）、
``data/local_overrides.yaml``（gitignored 个人拓扑 overlay）、
``data/discovered_tools.yaml``（自动发现客户端）。本模块把它们打包为
单个 JSON（**密钥脱敏**）并支持合并导入。

## 通道纪律（为什么导入要分流）

各键的**正典写入通道**不同，导入必须走同一条通道，否则写了不生效：

| 键 | 通道 | 依据 |
|---|---|---|
| ``active_profile`` / ``auto_discover`` / ``unified_skills_dir`` / ``disabled_tools`` / ``profiles`` | overlay（``apply_profile_sources`` 合并生效） | ``--set-active-profile`` / ``--set-auto-discover`` / ``--set-unified-dir`` 同通道 |
| ``settings.*`` / ``hooks.default_command`` / ``hooks.clients[].template`` | text-rewrite trunk ``config.yaml``（保注释） | ``--set-setting`` / ``--set-hook-template`` 同通道（``core/config_text.py``） |
| ``discovered_tools`` | ``data/discovered_tools.yaml`` | ``--add-client`` 同通道 |

## 安全

- 导出：``profiles.*.auth_token`` 非空 → ``"<redacted>"``（导出文件可能进
  iCloud / 被分享，密钥不落盘）；
- 导入：遇 ``"<redacted>"`` 的字段**跳过**（保留本地值），结果里提示需手动补；
- 导入前对将被修改的每个文件生成 ``.bak-<ts>`` 备份（``file_atomic.backup_path``
  约定，可被 ``--list-config-backups`` 列出）；
- 合并语义：**导入值优先、不删除本地已有键**（template / profiles 逐条合并，
  其余顶层键覆盖）。

## 明确不做（设计 2026-10-21 §5）

WebDAV 远程同步、导出加密压缩、GUI 文件选择器。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import yaml

from config_text import (
    _find_client_template_span,
    _rewrite_client_template,
    _set_default_command_in_text,
    _set_setting_in_text,
)
from file_atomic import atomic_write, backup_path

EXPORT_KIND = "skill-mcp-studio-config-export"
EXPORT_SCHEMA_VERSION = 1
REDACTED = "<redacted>"
ICLOUD_ALIAS = "icloud"
ICLOUD_REL_PATH = os.path.join(
    "Library", "Mobile Documents", "com~apple~CloudDocs",
    "skill-mcp-studio", "config-export.json",
)

# 导出「生效视图」包含的 config 顶层键（与导入分流表对应）。
_EXPORT_CONFIG_KEYS = (
    "active_profile",
    "auto_discover",
    "unified_skills_dir",
    "settings",
    "hooks",
    "disabled_tools",
)
# settings 段里允许 text-rewrite 的键（与 --set-setting 的白名单一致）。
_IMPORTABLE_SETTINGS_KEYS = ("patrol_enabled", "patrol_interval_minutes", "hook_events")


def _default_config_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")
    )


def _discovered_file() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "discovered_tools.yaml")
    )


def _app_version() -> str:
    version_json = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "version.json")
    )
    try:
        with open(version_json, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return str(data.get("version", "unknown"))
    except (OSError, ValueError):
        return "unknown"


def resolve_port_path(dest: str) -> str:
    """解析导出/导入目标：``icloud`` 别名 → iCloud Drive 固定路径；其余原样展开。

    非 macOS 上 ``icloud`` 显式报错（不静默写错地方——设计 §7）。
    """
    if dest.strip().lower() == ICLOUD_ALIAS:
        if sys.platform != "darwin":
            raise ValueError(
                "「icloud」别名仅在 macOS 可用（iCloud Drive 路径）；"
                "其他平台请传绝对路径"
            )
        return os.path.join(os.path.expanduser("~"), ICLOUD_REL_PATH)
    return os.path.expanduser(dest.strip())


def _redact_profiles(profiles: Dict[str, Any]) -> Dict[str, Any]:
    """深拷贝并把每个端点的非空 ``auth_token`` 替换为 ``<redacted>``。"""
    out = copy.deepcopy(profiles)
    for profile in out.values():
        if isinstance(profile, dict) and profile.get("auth_token"):
            profile["auth_token"] = REDACTED
    return out


def export_config(
    dest: str,
    *,
    config_path: Optional[str] = None,
    include_discovered: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """导出生效配置 + 端点库（脱敏）+ 自动发现清单为单个 JSON。

    生效视图取 ``scanner.load_config``（trunk + overlay 合并，与审计同源），
    保证「导出的就是当前生效的」。
    """
    from scanner import load_config

    cfg_path = os.path.normpath(config_path or _default_config_path())
    config = load_config(cfg_path)

    payload: Dict[str, Any] = {
        "kind": EXPORT_KIND,
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "app_version": _app_version(),
        "config": {k: config.get(k) for k in _EXPORT_CONFIG_KEYS},
        "profiles": _redact_profiles(config.get("profiles") or {}),
    }
    if include_discovered:
        discovered: List[Any] = []
        disc_path = _discovered_file()
        if os.path.isfile(disc_path):
            try:
                with open(disc_path, "r", encoding="utf-8") as fh:
                    discovered = yaml.safe_load(fh) or []
            except (OSError, yaml.YAMLError):
                discovered = []
        payload["discovered_tools"] = discovered if isinstance(discovered, list) else []

    out_path = resolve_port_path(dest)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if dry_run:
        return {
            "status": "dry-run",
            "path": out_path,
            "message": f"[dry-run] 将导出到 {out_path}（{len(rendered)} 字节，"
                       f"profiles {len(payload['profiles'])} 个，"
                       f"discovered {len(payload.get('discovered_tools') or [])} 条）",
            "payload": payload,
        }

    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    backup = ""
    if os.path.isfile(out_path):
        backup = backup_path(out_path)
    atomic_write(out_path, rendered, 0o644)
    return {
        "status": "ok",
        "path": out_path,
        "backup": backup,
        "message": f"已导出到 {out_path}（profiles {len(payload['profiles'])} 个"
                   f"（auth_token 已脱敏），discovered {len(payload.get('discovered_tools') or [])} 条）",
    }


def _read_export(src: str) -> Dict[str, Any]:
    """读取并校验导出包（kind / schema_version 不符直接拒绝，不做部分导入）。"""
    src_path = resolve_port_path(src)
    if not os.path.isfile(src_path):
        raise ValueError(f"导入文件不存在: {src_path}")
    try:
        with open(src_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError(f"导入文件无法解析为 JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != EXPORT_KIND:
        raise ValueError(
            f"不是 skill-mcp-studio 配置导出包（kind 不符）：{src_path}"
        )
    version = data.get("schema_version")
    if version != EXPORT_SCHEMA_VERSION:
        raise ValueError(
            f"不支持的导出包 schema_version: {version!r}（当前支持 {EXPORT_SCHEMA_VERSION}）"
        )
    return data


def _merge_dict_shallow(local: Any, imported: Any) -> Any:
    """dict 浅合并：导入键覆盖，本地其余键保留；非 dict 时导入值整体替换。

    ``imported`` 为 ``None``（导出包里该键未设置）时返回 ``local`` 原值——
    「未设置」不等于「清空」，不能拿 None 覆盖掉本地已有值（实测教训：
    导出端没有 disabled_tools 时，导入曾把本地 overlay 的停用清单覆盖成
    null）。
    """
    if imported is None:
        return local
    if isinstance(local, dict) and isinstance(imported, dict):
        merged = dict(local)
        merged.update(imported)
        return merged
    return imported


def _split_profiles_for_overlay(
    imported_profiles: Dict[str, Any],
    local_profiles: Dict[str, Any],
) -> tuple:
    """拆分导入端点：redacted 的 auth_token 跳过（保留本地值）。

    返回 ``(to_write, skipped_tokens)``：``to_write`` 是写入 overlay 的
    profiles 字典（redacted 字段已剔除）；``skipped_tokens`` 是需要手动补
    密钥的端点名列表。
    """
    to_write: Dict[str, Any] = {}
    skipped: List[str] = []
    for key, profile in imported_profiles.items():
        if not isinstance(profile, dict):
            to_write[key] = profile
            continue
        cleaned = dict(profile)
        if cleaned.get("auth_token") == REDACTED:
            cleaned.pop("auth_token", None)
            local_profile = local_profiles.get(key)
            if isinstance(local_profile, dict) and local_profile.get("auth_token"):
                # 本地已有密钥：保留本地值（写回 cleaned 供合并）
                cleaned["auth_token"] = local_profile["auth_token"]
            else:
                skipped.append(key)
        to_write[key] = cleaned
    return to_write, skipped


def import_config(
    src: str,
    *,
    config_path: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """合并导入：按各键正典通道分流写入（见模块 docstring 的通道纪律表）。

    - overlay 键 → ``_overlay_target``（与 ``--set-unified-dir`` 同通道）；
    - settings / hooks → text-rewrite trunk（保注释）；
    - discovered → 按 name 去重合并；
    - 导入值优先、不删除本地已有键；导入前对将改的文件各生成一份备份。
    """
    from config_store import _overlay_target, _ensure_overlay_registered, _atomic_write

    cfg_path = os.path.normpath(config_path or _default_config_path())
    data = _read_export(src)
    imported_config: Dict[str, Any] = data.get("config") or {}
    changes: List[str] = []
    skipped_tokens: List[str] = []
    backups: Dict[str, str] = {}

    # ── 1. overlay 键（active_profile / auto_discover / unified_skills_dir /
    #        disabled_tools / profiles）────────────────────────────────────
    overlay_path = _overlay_target(cfg_path)
    overlay: Dict[str, Any] = {}
    if os.path.isfile(overlay_path):
        try:
            with open(overlay_path, "r", encoding="utf-8") as fh:
                overlay = yaml.safe_load(fh) or {}
            if not isinstance(overlay, dict):
                overlay = {}
        except (OSError, yaml.YAMLError):
            overlay = {}

    for key in ("active_profile", "auto_discover", "unified_skills_dir", "disabled_tools"):
        if key in imported_config:
            merged = _merge_dict_shallow(overlay.get(key), imported_config[key])
            if overlay.get(key) != merged:
                overlay[key] = merged
                changes.append(f"overlay.{key}")

    imported_profiles = data.get("profiles") or {}
    if isinstance(imported_profiles, dict) and imported_profiles:
        local_profiles = overlay.get("profiles") or {}
        if not isinstance(local_profiles, dict):
            local_profiles = {}
        to_write, skipped = _split_profiles_for_overlay(imported_profiles, local_profiles)
        skipped_tokens.extend(skipped)
        merged_profiles = dict(local_profiles)
        merged_profiles.update(to_write)
        if merged_profiles != local_profiles:
            overlay["profiles"] = merged_profiles
            changes.append(f"overlay.profiles（{len(to_write)} 个端点）")

    overlay_dirty = bool(changes)

    # ── 2. settings / hooks → text-rewrite trunk（保注释）────────────────
    #    语义值相同则跳过（不做 text-rewrite）：既避免 changes 虚报，也避免
    #    引号风格差异（'' → ""）造成的无意义写盘与备份。
    trunk_raw = ""
    if os.path.isfile(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as fh:
            trunk_raw = fh.read()
    try:
        trunk_parsed = yaml.safe_load(trunk_raw) or {}
    except yaml.YAMLError:
        trunk_parsed = {}
    if not isinstance(trunk_parsed, dict):
        trunk_parsed = {}

    new_raw = trunk_raw
    imported_settings = imported_config.get("settings") or {}
    current_settings = trunk_parsed.get("settings") or {}
    if isinstance(imported_settings, dict) and isinstance(current_settings, dict):
        for key in _IMPORTABLE_SETTINGS_KEYS:
            if key in imported_settings and imported_settings[key] != current_settings.get(key):
                new_raw = _set_setting_in_text(new_raw, key, imported_settings[key])
                changes.append(f"settings.{key}")

    imported_hooks = imported_config.get("hooks") or {}
    current_hooks = trunk_parsed.get("hooks") or {}
    if isinstance(imported_hooks, dict) and isinstance(current_hooks, dict):
        if (
            "default_command" in imported_hooks
            and imported_hooks.get("default_command") != current_hooks.get("default_command")
        ):
            new_raw = _set_default_command_in_text(
                new_raw, str(imported_hooks.get("default_command") or "")
            )
            changes.append("hooks.default_command")
        imported_clients = imported_hooks.get("clients") or []
        if isinstance(imported_clients, list):
            for client in imported_clients:
                if not isinstance(client, dict) or not client.get("name"):
                    continue
                cname = str(client["name"])
                template = client.get("template") or {}
                if not isinstance(template, dict) or not template:
                    continue
                # 逐事件合并（导入事件覆盖同名，本地其他事件保留——「不删除」原则）；
                # 全部事件值均已一致时跳过（不写盘）。
                span = _find_client_template_span(new_raw, cname)
                current = dict(span[2]) if span else {}
                merged_tpl = dict(current)
                merged_tpl.update(template)
                if merged_tpl == current:
                    continue
                new_raw = _rewrite_client_template(new_raw, cname, merged_tpl)
                changes.append(f"hooks.clients[{cname}].template（{len(template)} 事件）")

    trunk_dirty = new_raw != trunk_raw

    # ── 3. discovered_tools → 按 name 去重合并 ───────────────────────────
    disc_path = _discovered_file()
    imported_discovered = data.get("discovered_tools") or []
    disc_dirty = False
    merged_discovered: List[Any] = []
    if isinstance(imported_discovered, list) and imported_discovered:
        if os.path.isfile(disc_path):
            try:
                with open(disc_path, "r", encoding="utf-8") as fh:
                    merged_discovered = yaml.safe_load(fh) or []
            except (OSError, yaml.YAMLError):
                merged_discovered = []
        if not isinstance(merged_discovered, list):
            merged_discovered = []
        by_name = {
            (e.get("name") if isinstance(e, dict) else str(e)): e
            for e in merged_discovered
        }
        for entry in imported_discovered:
            name = entry.get("name") if isinstance(entry, dict) else str(entry)
            if name not in by_name:
                merged_discovered.append(entry)
                by_name[name] = entry
                disc_dirty = True
        if not disc_dirty:
            merged_discovered = []  # 无新增则不写

    # ── 4. dry-run：只报告将做的变更 ─────────────────────────────────────
    if dry_run:
        plan = list(changes)
        if disc_dirty:
            plan.append("discovered_tools（按 name 去重合并）")
        return {
            "status": "dry-run",
            "changes": plan,
            "skipped_tokens": skipped_tokens,
            "message": "[dry-run] 将导入：" + ("；".join(plan) if plan else "（无变更）")
                       + (f"；{len(skipped_tokens)} 个端点的 auth_token 需手动补" if skipped_tokens else ""),
        }

    # ── 5. 落盘（先备份）─────────────────────────────────────────────────
    #    注意：``backup_path`` 只生成路径名，**复制必须自己做**（``shutil.copy2``，
    #    与 ``config_store.set_unified_dir`` 同款）——只调 backup_path 不复制
    #    会得到「报了备份路径但文件不存在」的假备份（实测教训）。
    def _backup_existing(path: str) -> str:
        if os.path.isfile(path):
            bak = backup_path(path)
            shutil.copy2(path, bak)
            return bak
        return ""

    if overlay_dirty:
        backups["overlay"] = _backup_existing(overlay_path)
        rendered = yaml.safe_dump(overlay, allow_unicode=True, default_flow_style=False)
        _atomic_write(overlay_path, rendered, 0o644)
        if overlay_path.endswith("local_overrides.yaml"):
            _ensure_overlay_registered(cfg_path, overlay_path)

    if trunk_dirty:
        backups["config"] = _backup_existing(cfg_path)
        atomic_write(cfg_path, new_raw, 0o644)

    if disc_dirty:
        backups["discovered"] = _backup_existing(disc_path)
        rendered_disc = yaml.safe_dump(
            merged_discovered, allow_unicode=True, default_flow_style=False
        )
        parent = os.path.dirname(disc_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        atomic_write(disc_path, rendered_disc, 0o644)

    return {
        "status": "ok",
        "changes": changes + (["discovered_tools"] if disc_dirty else []),
        "skipped_tokens": skipped_tokens,
        "backups": backups,
        "message": "已导入：" + ("；".join(changes) if changes else "（无变更）")
                   + ("；discovered_tools 合并" if disc_dirty else "")
                   + (f"；{len(skipped_tokens)} 个端点的 auth_token 需手动补（导出包已脱敏）" if skipped_tokens else ""),
    }
