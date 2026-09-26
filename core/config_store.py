"""Config write store (stage-5 P7): unified dir + discovered client additions.

Two write targets, both following the safety principle that a write never
rewrites more than it must:

- ``set_unified_dir`` edits the single ``unified_skills_dir:`` line **in place**
  (regex on the text, not a whole-file YAML round-trip) so comments and key order
  in ``config.yaml`` survive;
- ``add_discovered_client`` appends to ``data/discovered_tools.yaml`` (gitignored,
  repo-external like profile_sources) so personal/client-specific client entries
  never pollute the trunk registry.

Both go through the mcp_fixer atomic-write + re-parse + rollback shape.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import yaml

from file_atomic import atomic_write as _atomic_write, backup_path as _backup_path
from mainstream_registry import MAINSTREAM_TOOLS
from names import normalized_name


def _default_config_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")
    )


def _discovered_file() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "discovered_tools.yaml")
    )


def _local_overrides_file() -> str:
    """B3: gitignored overlay sink for personal topology (unified_skills_dir).

    Mirrors ``data/discovered_tools.yaml`` — both under ``data/`` which is in
    ``.gitignore``, so machine-local paths never enter the version-controlled
    trunk ``config.yaml``.
    """
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "local_overrides.yaml")
    )


def _overlay_target(config_path: str) -> str:
    """Pick the write target for personal topology overlays.

    Reuses the first *existing* ``profile_sources`` overlay file (same channel
    as endpoint_store); falls back to the dedicated ``data/local_overrides.yaml``
    which is auto-registered as a profile_source on first write.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        config = {}
    for raw in config.get("profile_sources") or []:
        if isinstance(raw, str) and raw.strip():
            candidate = os.path.expanduser(raw)
            if os.path.isfile(candidate):
                return candidate
    return _local_overrides_file()


def _ensure_overlay_registered(config_path: str, overlay_path: str) -> None:
    """Register ``overlay_path`` in trunk config's ``profile_sources`` if absent.

    Only called when falling back to ``data/local_overrides.yaml`` for the first
    time; edits trunk config.yaml additively (a path entry, not personal data).
    """
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return
    overlay_rel = os.path.relpath(overlay_path, os.path.dirname(config_path))
    # avoid duplicate registration
    if overlay_rel in text or overlay_path in text:
        return
    import re

    # 流式写法：profile_sources: [a, b]
    flow = re.compile(r"(?m)^(\s*profile_sources\s*:\s*\[)([^\]]*)\]")
    # 块式写法：profile_sources:\n- a\n- b
    block = re.compile(r"(?m)^(\s*profile_sources\s*:\s*\n)((?:[ \t]*-[^\n]*\n)*)")
    if flow.search(text):
        new = flow.sub(
            lambda m: m.group(1)
            + (m.group(2).rstrip() + ", " if m.group(2).strip() else "")
            + overlay_rel
            + "]",
            text,
        )
    elif block.search(text):
        def _append_item(m):
            head = m.group(1)
            items = m.group(2)
            # 与既有列表项保持相同缩进；无列表项时用 key 缩进 + 两个空格
            if items:
                last = items.rstrip("\n").rsplit("\n", 1)[-1]
                indent = re.match(r"[ \t]*", last).group(0)
            else:
                indent = re.match(r"[ \t]*", head).group(0) + "  "
            return head + items + f"{indent}- {overlay_rel}\n"

        new = block.sub(_append_item, text)
    else:
        new = text.rstrip("\n") + f"\nprofile_sources: [ {overlay_rel} ]\n"
    mode = os.stat(config_path).st_mode & 0o7777
    import shutil

    backup = _backup_path(config_path)
    shutil.copy2(config_path, backup)
    _atomic_write(config_path, new, mode)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def set_unified_dir(
    new_dir: str,
    *,
    config_path: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Write ``unified_skills_dir`` into a gitignored overlay file (B3 fix).

    Never edits the version-controlled trunk ``config.yaml``. The value lands in
    the first existing ``profile_sources`` overlay file (same channel as
    endpoint_store), or in the dedicated ``data/local_overrides.yaml`` which is
    auto-registered as a profile_source on first write. ``apply_profile_sources``
    merges it over the trunk default.
    """
    cfg_path = config_path or _default_config_path()
    if not new_dir or not new_dir.strip():
        return {"status": "error", "message": "统一目录不能为空", "path": cfg_path, "backup": ""}
    target = _overlay_target(cfg_path)

    # load existing overlay data (if any)
    existing = {}
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as handle:
                existing = yaml.safe_load(handle) or {}
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, yaml.YAMLError):
            existing = {}

    current = existing.get("unified_skills_dir")
    if current == new_dir:
        return {"status": "unchanged", "message": f"unified_skills_dir 已是 {new_dir!r}", "path": target, "backup": ""}

    existing["unified_skills_dir"] = new_dir
    rendered = yaml.safe_dump(existing, allow_unicode=True, default_flow_style=False)
    if dry_run:
        return {"status": "dry-run", "message": rendered, "path": target, "backup": ""}

    backup = ""
    mode = os.stat(target).st_mode & 0o7777 if os.path.isfile(target) else 0o644
    try:
        if os.path.isfile(target):
            import shutil

            backup = _backup_path(target)
            shutil.copy2(target, backup)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        _atomic_write(target, rendered, mode)
    except OSError as exc:
        return {"status": "error", "message": f"write failed: {exc}", "path": target, "backup": backup}

    # if we used the dedicated local_overrides.yaml, register it once
    if target == _local_overrides_file():
        _ensure_overlay_registered(cfg_path, target)

    return {"status": "ok", "message": f"unified_skills_dir → {new_dir!r}（写入 {os.path.basename(target)}）", "path": target, "backup": backup}


def load_discovered() -> List[Dict[str, Any]]:
    path = _discovered_file()
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, list) else []


def remove_discovered_client(name: str, *, dry_run: bool = False) -> Dict[str, str]:
    """Remove a client from ``data/discovered_tools.yaml`` by normalized name.

    Only touches the user-added discovered file (never the git-trunk config.yaml
    built-in registry).  Returns ``unchanged`` when no such entry exists.
    """
    path = _discovered_file()
    discovered = load_discovered()
    norm = "".join(c for c in name.lower() if c.isalnum())
    kept = [d for d in discovered if "".join(c for c in str(d.get("name", "")).lower() if c.isalnum()) != norm]
    if len(kept) == len(discovered):
        return {"status": "unchanged", "message": f"discovered 中无 {name!r}", "path": path, "backup": ""}

    rendered = yaml.safe_dump(kept, allow_unicode=True, default_flow_style=False)
    if dry_run:
        return {"status": "dry-run", "message": f"将移除客户端 {name!r}（{len(discovered) - len(kept)} 条）", "path": path, "backup": ""}

    mode = os.stat(path).st_mode & 0o7777 if os.path.isfile(path) else 0o644
    backup = _backup_path(path) if os.path.isfile(path) else ""
    try:
        if backup:
            import shutil

            shutil.copy2(path, backup)
        _atomic_write(path, rendered, mode)
    except OSError as exc:
        return {"status": "error", "message": f"write failed: {exc}", "path": path, "backup": backup}
    return {"status": "ok", "message": f"已移除客户端 {name!r}（{len(discovered) - len(kept)} 条）", "path": path, "backup": backup}


def cleanup_config_only_client(
    config: Dict[str, Any],
    name: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """删除 config_only（仅有配置、无 app/cli）客户端的残留配置文件（带备份）。

    只处理真实存在的配置文件：``install.config_paths``（安装证据里的 config 文件）
    加上主 MCP 配置文件 ``config_path``，二者去重后逐个备份到 ``.bak-时间戳`` 再删除。
    已安装（有 app/cli）或未检测到的客户端一律拒绝，避免误删在用客户端。
    """
    import shutil

    from tool_registry import detect_installation, effective_tools

    wanted = normalized_name(name)
    target = None
    for tool in effective_tools(config):
        if normalized_name(tool.get("name", "")) == wanted:
            target = tool
            break
    if target is None:
        return {"status": "error", "message": f"未找到客户端 {name!r}", "path": "", "files": [], "backup": ""}

    install = detect_installation(target)
    if install["install_state"] == "installed":
        return {"status": "skip", "message": f"{target.get('name')!r} 已安装（有 app/cli），不应清理配置", "path": "", "files": [], "backup": ""}
    if install["install_state"] != "config_only":
        return {"status": "skip", "message": f"{target.get('name')!r} 无配置可清理（{install['install_state']}）", "path": "", "files": [], "backup": ""}

    # 收集去重后的真实配置文件：install.config_paths + 主 MCP config_path
    candidates = list(install.get("config_paths", [])) + [target.get("config_path", "")]
    files = []
    seen = set()
    for path in candidates:
        if not path:
            continue
        full = os.path.expanduser(path)
        if full in seen or not os.path.isfile(full):
            continue
        seen.add(full)
        files.append(full)

    if not files:
        return {"status": "unchanged", "message": "未找到配置文件（可能已被清理）", "path": "", "files": [], "backup": ""}

    if dry_run:
        return {"status": "dry-run", "message": f"将删除 {len(files)} 个配置文件", "path": "", "files": files, "backup": ""}

    backups = []
    try:
        for full in files:
            backup = _backup_path(full)
            shutil.copy2(full, backup)
            backups.append(backup)
            os.remove(full)
    except OSError as exc:
        return {"status": "error", "message": f"删除失败: {exc}", "path": "", "files": files, "backup": ", ".join(backups)}

    return {"status": "ok", "message": f"已删除 {len(files)} 个配置文件", "path": "", "files": files, "backup": ", ".join(backups)}


def _disable_in_overlay(
    config_path: str,
    name: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """记录「本机停用」到 gitignored overlay（profile_sources），而非删 trunk 注册表。

    删除客户端的正确语义：本机不再纳入管理，而不是从版本受控的共享注册表里
    抹掉该客户端的探测定义。停用标记写进 overlay 的 ``disabled_tools`` 列表，
    ``apply_profile_sources`` 合并后由 effective_tools / run_scan 兜底过滤——
    trunk config.yaml 保持不变，其它设备也不会被本机的停用状态干扰。
    """
    cfg_path = config_path or _default_config_path()
    target = _overlay_target(cfg_path)

    wanted = normalized_name(name)
    existing = {}
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as handle:
                existing = yaml.safe_load(handle) or {}
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, yaml.YAMLError):
            existing = {}

    disabled = list(existing.get("disabled_tools") or [])
    if wanted in {normalized_name(n) for n in disabled if isinstance(n, str)}:
        return {"status": "unchanged", "message": f"{name!r} 已在本机停用清单中", "path": target, "backup": ""}

    disabled.append(name)
    existing["disabled_tools"] = disabled
    rendered = yaml.safe_dump(existing, allow_unicode=True, default_flow_style=False)
    if dry_run:
        return {"status": "dry-run", "message": f"将在本机停用 {name!r}（trunk 注册表保留，仅本机不再纳入管理）", "path": target, "backup": ""}

    backup = ""
    mode = os.stat(target).st_mode & 0o7777 if os.path.isfile(target) else 0o644
    try:
        if os.path.isfile(target):
            import shutil

            backup = _backup_path(target)
            shutil.copy2(target, backup)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        _atomic_write(target, rendered, mode)
    except OSError as exc:
        return {"status": "error", "message": f"write failed: {exc}", "path": target, "backup": backup}

    if target == _local_overrides_file():
        _ensure_overlay_registered(cfg_path, target)

    return {"status": "ok", "message": f"已在本机停用 {name!r}（trunk 注册表保留，仅本机不再纳入管理）", "path": target, "backup": backup}


def remove_managed_client(
    config: Dict[str, Any],
    name: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """移除受管客户端：本机停用 + 残留配置 + skills 链接。

    已安装（有 app/cli）的客户端拒绝删除。config_only / none（未检测到）的客户端
    允许移除：从 discovered_tools.yaml 移除本机条目、「本机停用」标记写入 overlay
    （不删 trunk 共享注册表），删除残留配置文件（带备份），并删除指向统一仓库的
    skills 软链接（真实目录不碰）。即「停用」而非「删定义」——其它设备不受影响。
    返回汇总状态与各步骤信息。
    """
    import shutil

    from tool_registry import detect_installation

    wanted = normalized_name(name)
    # 收集**所有** name 匹配的条目（mcp_tools + tools + discovered），而不是用
    # effective_tools 的去重结果——同一客户端可能同时出现在 config.yaml 的
    # mcp_tools（MCP 配置）和 tools（skills 挂载）两段，两段都要删、skills/config
    # 路径要合并收集。
    matches: List[Dict[str, Any]] = []
    for src in (config.get("mcp_tools", []), config.get("tools", []), load_discovered()):
        for tool in src or []:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            if normalized_name(tool.get("name", "")) == wanted:
                matches.append(tool)

    # 安装状态门控：任一匹配条目已安装（有 app/cli）则拒绝删除
    for m in matches:
        install = detect_installation(m)
        if install["install_state"] == "installed":
            return {
                "status": "skip",
                "message": f"{m.get('name')!r} 已安装（有 app/cli），不应删除",
                "path": "", "files": [], "backup": "", "steps": [],
            }

    steps: List[Dict[str, Any]] = []
    backups: List[str] = []

    # 1. 残留配置文件（合并所有匹配条目的 install.config_paths + config_path）
    files: List[str] = []
    for m in matches:
        install = detect_installation(m)
        candidates = list(install.get("config_paths", [])) + [m.get("config_path", "")]
        for path in candidates:
            if not path:
                continue
            full = os.path.expanduser(path)
            if full in files or not os.path.isfile(full):
                continue
            files.append(full)
    if files and not dry_run:
        for full in files:
            try:
                backup = _backup_path(full)
                shutil.copy2(full, backup)
                backups.append(backup)
                os.remove(full)
            except OSError as exc:
                steps.append({"step": "config", "status": "error", "message": f"删除 {full} 失败: {exc}"})
    steps.append({
        "step": "config",
        "status": "ok" if files and not dry_run else ("dry-run" if files else "unchanged"),
        "message": f"残留配置 {len(files)} 个" if not dry_run else f"将删除残留配置 {len(files)} 个",
        "files": files,
    })

    # 2. skills 链接（合并所有匹配条目的 skills_paths，只删 symlink，真实目录不碰）
    skills_links: List[str] = []
    for m in matches:
        for raw in m.get("skills_paths") or []:
            if not raw:
                continue
            full = os.path.expanduser(raw)
            if os.path.islink(full) and full not in skills_links:
                skills_links.append(full)
    if skills_links and not dry_run:
        for full in skills_links:
            try:
                os.remove(full)
            except OSError as exc:
                steps.append({"step": "skills", "status": "error", "message": f"删除链接 {full} 失败: {exc}"})
    steps.append({
        "step": "skills",
        "status": "ok" if skills_links and not dry_run else ("dry-run" if skills_links else "unchanged"),
        "message": f"skills 链接 {len(skills_links)} 个" if not dry_run else f"将删除 skills 链接 {len(skills_links)} 个",
        "files": skills_links,
    })

    # 3. discovered_tools.yaml
    disc = remove_discovered_client(name, dry_run=dry_run)
    steps.append({"step": "discovered", **disc})

    # 4. 本机停用（overlay），不再删 trunk 配置的共享注册表条目
    disabled = _disable_in_overlay(_default_config_path(), name, dry_run=dry_run)
    steps.append({"step": "disable", **disabled})

    # 汇总状态：error > ok > dry-run > unchanged
    statuses = [s.get("status") for s in steps]
    if any(s == "error" for s in statuses):
        status = "error"
    elif any(s == "ok" for s in statuses):
        status = "ok"
    elif any(s == "dry-run" for s in statuses):
        status = "dry-run"
    else:
        status = "unchanged"

    return {
        "status": status,
        "message": f"移除客户端 {name!r}（discovered: {disc['status']}，本机停用: {disabled['status']}）",
        "path": "", "files": files, "backup": ", ".join(backups), "steps": steps,
    }


def add_discovered_client(
    name: str,
    *,
    skills_path: Optional[str] = None,
    client_type: Optional[str] = None,
    config_path: Optional[str] = None,
    mcp_format: Optional[str] = None,
    mcp_key_path: Optional[str] = None,
    mcp_attach: Optional[List[str]] = None,
    install: Optional[Dict[str, Any]] = None,
    aliases: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Append one manually-added client to ``data/discovered_tools.yaml``.

    De-duplicates by normalized name against the existing discovered list.  The
    entry shape matches ``scanner.scan_for_new_tools`` output so ``run_scan``
    picks it up on the next pass without further marshalling.

    FEAT-1: optional MCP-side fields (config_path/mcp_format/mcp_key_path/
    mcp_attach) let the user register a full MCP-capable client, not just a
    skills-only one; mcp_inventory/mcp_fixer then recognize it.

    整改: ``install`` passes through the app_bundles/commands/config_paths
    detection block, and ``aliases`` is persisted so custom/默认 clients are
    detected exactly like built-in registry entries.
    """
    path = _discovered_file()
    discovered = load_discovered()
    norm = "".join(c for c in name.lower() if c.isalnum())
    for existing in discovered:
        if "".join(c for c in str(existing.get("name", "")).lower() if c.isalnum()) == norm:
            return {"status": "unchanged", "message": f"客户端 {name!r} 已存在", "path": path, "backup": ""}

    entry: Dict[str, Any] = {
        "name": name,
        "type": client_type or "AI Agent",
        "backup_suffix": ".bak",
        "auto_discovered": False,
    }
    if skills_path:
        entry["skills_paths"] = [skills_path]
    if aliases:
        entry["aliases"] = list(aliases)
    # FEAT-1: MCP-side registration so mcp_inventory/mcp_fixer recognize it
    if config_path:
        entry["config_path"] = config_path
        entry["format"] = mcp_format or "json"
        entry["mcp_key_path"] = (mcp_key_path or "mcpServers").split(".") if mcp_key_path else ["mcpServers"]
    if mcp_attach:
        entry["mcp_attach"] = list(mcp_attach)
    # 整改: persist install detection block (app_bundles/commands/config_paths)
    if install:
        entry["install"] = install

    new_list = discovered + [entry]
    rendered = yaml.safe_dump(new_list, allow_unicode=True, default_flow_style=False)
    if dry_run:
        return {"status": "dry-run", "message": rendered, "path": path, "backup": ""}

    mode = os.stat(path).st_mode & 0o7777 if os.path.isfile(path) else 0o644
    backup = _backup_path(path) if os.path.isfile(path) else ""
    try:
        if backup:
            import shutil

            shutil.copy2(path, backup)
        _atomic_write(path, rendered, mode)
    except OSError as exc:
        return {"status": "error", "message": f"write failed: {exc}", "path": path, "backup": backup}
    return {"status": "ok", "message": f"已添加客户端 {name!r}", "path": path, "backup": backup}


def update_discovered_client(
    name: str,
    *,
    app_bundles: Optional[List[str]] = None,
    commands: Optional[List[str]] = None,
    config_paths: Optional[List[str]] = None,
    skills_path: Optional[str] = None,
    mcp_config_path: Optional[str] = None,
    scan_dir: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Update a client recorded in ``data/discovered_tools.yaml`` in place.

    Backs the ``--update-client`` management action ("编辑客户端" in the GUI):
    a user edits the default install evidence (app bundles / CLI commands /
    config paths), the Skills dir, the MCP config path, or the scan dir of an
    already-registered client.  Falls back to ``add_discovered_client`` when no
    matching entry exists, so the same action can also create it (idempotent).
    """
    path = _discovered_file()
    discovered = load_discovered()
    norm = "".join(c for c in name.lower() if c.isalnum())

    idx = None
    for i, existing in enumerate(discovered):
        if "".join(c for c in str(existing.get("name", "")).lower() if c.isalnum()) == norm:
            idx = i
            break

    if idx is None:
        # Not present yet: delegate to add (builds install block from the args).
        install: Optional[Dict[str, Any]] = None
        if app_bundles or commands or config_paths:
            install = {
                "app_bundles": list(app_bundles or []),
                "commands": list(commands or []),
                "config_paths": list(config_paths or []),
            }
        return add_discovered_client(
            name,
            skills_path=skills_path,
            config_path=mcp_config_path,
            install=install,
            dry_run=dry_run,
        )

    entry = dict(discovered[idx])
    # Install evidence block (app_bundles/commands/config_paths).
    if app_bundles is not None or commands is not None or config_paths is not None:
        install = dict(entry.get("install") or {})
        if app_bundles is not None:
            install["app_bundles"] = list(app_bundles)
        if commands is not None:
            install["commands"] = list(commands)
        if config_paths is not None:
            install["config_paths"] = list(config_paths)
        entry["install"] = install
    # Skills dir (single value; stored as skills_paths list).
    if skills_path is not None:
        entry["skills_paths"] = [skills_path]
    # MCP config path (single primary config_path + format/mcp_key_path stay).
    if mcp_config_path is not None:
        entry["config_path"] = mcp_config_path
    # Scan dir (FEAT-1 extension; persisted verbatim).
    if scan_dir is not None:
        entry["scan_dir"] = scan_dir

    discovered[idx] = entry
    rendered = yaml.safe_dump(discovered, allow_unicode=True, default_flow_style=False)
    if dry_run:
        return {"status": "dry-run", "message": rendered, "path": path, "backup": ""}

    mode = os.stat(path).st_mode & 0o7777 if os.path.isfile(path) else 0o644
    backup = _backup_path(path) if os.path.isfile(path) else ""
    try:
        if backup:
            import shutil

            shutil.copy2(path, backup)
        _atomic_write(path, rendered, mode)
    except OSError as exc:
        return {"status": "error", "message": f"write failed: {exc}", "path": path, "backup": backup}
    return {"status": "ok", "message": f"已更新客户端 {name!r}", "path": path, "backup": backup}


def add_default_clients(dry_run: bool = False) -> Dict[str, Any]:
    """一键「默认添加」主流 IDE/Agent 到 discovered 持久化（整改）。

    遍历 ``mainstream_registry.MAINSTREAM_TOOLS``，逐个调用
    ``add_discovered_client``（按归一化名去重），返回逐条目结果与汇总。
    """
    results: List[Dict[str, str]] = []
    for tool in MAINSTREAM_TOOLS:
        install = tool.get("install") or {}
        res = add_discovered_client(
            tool["name"],
            skills_path=(tool.get("skills_paths") or [""] or [None])[0],
            client_type=tool.get("type"),
            config_path=tool.get("config_path"),
            mcp_format=tool.get("format"),
            mcp_key_path=(".".join(tool["mcp_key_path"]) if isinstance(tool.get("mcp_key_path"), list) else tool.get("mcp_key_path")),
            install=install,
            aliases=tool.get("aliases"),
            dry_run=dry_run,
        )
        # roll name back into the result for per-entry reporting
        results.append({"name": tool["name"], **res})

    added = [r for r in results if r["status"] == "ok"]
    unchanged = [r for r in results if r["status"] == "unchanged"]
    dry = [r for r in results if r["status"] == "dry-run"]
    # dry-run 模式下所有拟新增均返回 "dry-run"，需单独计数为 would_add
    would_add = len(dry) if dry_run else len(added)
    return {
        "status": "dry-run" if dry_run else "ok",
        "added": would_add,
        "unchanged": len(unchanged),
        "total": len(results),
        "results": results,
    }
