"""Hook 配置修复：写入 / 移除标准 ai-memory 生命周期 hook 模板。

参照 ``mcp_fixer.fix_mcp_tool`` 的 backup → atomic-write → validate → rollback
安全链（``file_atomic`` 三件套）。模板来自 ``config.yaml`` 的
``hooks.clients[].template`` 段（事件 → ai-memory hook 命令）。

写入结构（Claude Code / WorkBuddy / Codex 风格）::

    {"hooks": {"SessionStart": [
        {"matcher": "*", "hooks": [{"type": "command", "command": "ai-memory hook --event session_start"}]}
    ]}}
"""

import json
import os
import shutil
from typing import Any, Dict, List

from file_atomic import atomic_write, backup_path, restore_backup
from legacy_checker import _load_json_file, _norm_tool_name
from ai_memory_checker import _find_in_dict
from hooks_inventory import hooks_client_config, list_client_hook_entries, _is_ai_memory_hook_cmd


def _result(name: str, status: str, message: str, **extra: Any) -> Dict[str, Any]:
    """构造返回 dict（仿 ``mcp_fixer_render._result``）。

    status 枚举与 mcp_fixer 对齐：missing / unsupported / error / unchanged /
    dry-run / updated / created。
    """
    return {"name": name, "status": status, "message": message, **extra}


def _build_hook_entry(command: str) -> Dict[str, Any]:
    """构造单个 hook 事件的标准写入结构。

    ``{"matcher": "*", "hooks": [{"type": "command", "command": "..."}]}``
    """
    return {
        "matcher": "*",
        "hooks": [{"type": "command", "command": command}],
    }


def _ensure_hook_section(data: Dict[str, Any], hook_keys: List[str]) -> Dict[str, Any]:
    """沿 hook_keys 深入取 hooks 段（不存在则创建）。

    与 ``ai_memory_checker._find_json_mcp_section`` 同语义：键不存在才创建，
    键存在但非 dict 则抛 ``TypeError``（由调用方捕获转 error）。
    """
    current = data
    for key in hook_keys:
        if not isinstance(current, dict):
            raise TypeError(f"hook 路径 {'.'.join(hook_keys)} 上有非对象内容")
        if key not in current:
            current[key] = {}
        elif not isinstance(current[key], dict):
            raise TypeError(f"hook 路径 {'.'.join(hook_keys)} 上 '{key}' 已存在且非对象")
        current = current[key]
    return current


def fix_hooks_tool(
    tool: Dict[str, Any],
    config: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """为单个客户端写入标准 ai-memory hook 模板。

    安全链：读原配置 → 渲染模板 → dry-run 判断 → 备份 → 原子写 → 重新解析校验 → 失败回滚。
    """
    name = tool.get("name", "")
    hc = hooks_client_config(config, name)
    if not hc:
        return _result(name, "missing", "未在 hooks 段声明，跳过")

    if not hc.get("fix_supported", False):
        return _result(name, "unsupported", f"不支持模板注入（{hc.get('note', '')}）")

    config_path = os.path.expanduser(hc.get("config_path", ""))
    template: Dict[str, str] = hc.get("template", {}) or {}
    if not template:
        return _result(name, "missing", "无 template 定义，跳过")

    # 读原配置（不存在则新建空 dict）
    had_file = os.path.isfile(config_path)
    data = _load_json_file(config_path) if had_file else {}
    if data is None:
        return _result(name, "error", "配置文件无法解析为 JSON，跳过")
    if not isinstance(data, dict):
        return _result(name, "error", "配置文件非 JSON 对象，跳过")

    # 定位 / 创建 hooks 段
    hook_keys = hc.get("hook_key_path") or hc.get("hook_keys") or ["hooks"]
    try:
        hook_section = _ensure_hook_section(data, hook_keys)
    except TypeError as e:
        return _result(name, "error", f"hooks 段结构异常：{e}")

    # 检查已配置事件（避免重复写入）
    existing_entries = list_client_hook_entries(tool, config)
    existing_ai_events = {e.event for e in existing_entries if e.is_ai_memory}
    to_write = {ev: cmd for ev, cmd in template.items() if ev not in existing_ai_events}

    if not to_write:
        return _result(name, "unchanged", "所有 template 事件已配置，跳过")

    # 渲染：把 template 事件写入 hook_section
    for event, command in to_write.items():
        if event not in hook_section or not isinstance(hook_section[event], list):
            hook_section[event] = []
        hook_section[event].append(_build_hook_entry(command))

    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    if dry_run:
        return _result(name, "dry-run", f"[dry-run] 将写入 {len(to_write)} 个 hook 事件：{', '.join(to_write)}")

    # 备份
    mode = 0o600
    if had_file:
        try:
            mode = os.stat(config_path).st_mode & 0o777
        except OSError:
            pass
        bak = backup_path(config_path)
        shutil.copy2(config_path, bak)
    else:
        bak = ""
        parent = os.path.dirname(config_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    # 原子写 + 重新解析校验
    try:
        atomic_write(config_path, rendered, mode)
        verify = _load_json_file(config_path)
        if verify is None:
            raise RuntimeError("写入后重新解析 JSON 失败")
    except Exception as e:
        # 回滚
        if had_file and bak:
            restore_backup(bak, config_path, mode)
        elif not had_file:
            try:
                os.unlink(config_path)
            except OSError:
                pass
        return _result(name, "error", f"写入失败已回滚：{e}", backup=bak)

    return _result(
        name,
        "updated" if had_file else "created",
        f"已写入 {len(to_write)} 个 hook 事件（备份 {bak}）" if bak else f"已创建配置并写入 {len(to_write)} 个 hook 事件",
        backup=bak,
        path=config_path,
    )


def fix_hooks_all(
    config: Dict[str, Any],
    tools: List[Dict[str, Any]],
    *,
    dry_run: bool = False,
    client: str = "",
) -> List[Dict[str, Any]]:
    """批量写入 hook 模板。

    ``--client`` 过滤按 ``normalized_name`` 匹配（仿 ``fix_mcp_clients``）。
    """
    wanted = _norm_tool_name(client) if client else None
    results: List[Dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name", "")
        if wanted is not None and _norm_tool_name(name) != wanted:
            continue
        if not hooks_client_config(config, name):
            continue
        results.append(fix_hooks_tool(tool, config, dry_run=dry_run))
    return results


def _filter_ai_memory_from_event(event_hooks: Any) -> tuple:
    """从事件的 hooks 数组过滤 ai-memory 条目，返回 (新数组, 移除数)。

    保留非 ai-memory 的 hook 条目；若整个 entry 的 hooks 全是 ai-memory 且
    无其他字段，则整个 entry 移除。
    """
    if not isinstance(event_hooks, list):
        return event_hooks, 0

    new_entries: List[Any] = []
    removed = 0
    for entry in event_hooks:
        if not isinstance(entry, dict):
            new_entries.append(entry)
            continue
        hooks_arr = entry.get("hooks")
        if isinstance(hooks_arr, list):
            kept_hooks = []
            for h in hooks_arr:
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                if _is_ai_memory_hook_cmd(cmd):
                    removed += 1
                else:
                    kept_hooks.append(h)
            if kept_hooks:
                entry["hooks"] = kept_hooks
                new_entries.append(entry)
            else:
                # 整个 entry 的 hooks 都是 ai-memory（或空），丢弃 entry
                pass
        else:
            # 非 hooks 数组结构，检查 command 字段
            cmd = entry.get("command", "")
            if isinstance(cmd, str) and _is_ai_memory_hook_cmd(cmd):
                removed += 1
            else:
                new_entries.append(entry)
    return new_entries, removed


def remove_hooks_tool(
    tool: Dict[str, Any],
    config: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """移除客户端的 ai-memory hook 事件（保留非 ai-memory hooks）。

    安全链同 ``fix_hooks_tool``。
    """
    name = tool.get("name", "")
    hc = hooks_client_config(config, name)
    if not hc:
        return _result(name, "missing", "未在 hooks 段声明，跳过")

    config_path = os.path.expanduser(hc.get("config_path", ""))
    if not os.path.isfile(config_path):
        return _result(name, "missing", "配置文件不存在")

    data = _load_json_file(config_path)
    if data is None or not isinstance(data, dict):
        return _result(name, "missing", "配置无法解析")

    hook_keys = hc.get("hook_key_path") or ["hooks"]
    hook_section = _find_in_dict(data, hook_keys)
    # 兼容顶层即事件名
    if hook_section is None and isinstance(data, dict) and data:
        known = set(hc.get("events", []))
        if any(k in known for k in data.keys()):
            hook_section = data

    if hook_section is None or not isinstance(hook_section, dict):
        return _result(name, "missing", "hooks 段不存在")

    removed = 0
    for event in list(hook_section.keys()):
        new_entries, n = _filter_ai_memory_from_event(hook_section[event])
        if n:
            removed += n
            if new_entries:
                hook_section[event] = new_entries
            else:
                del hook_section[event]

    if removed == 0:
        return _result(name, "unchanged", "无 ai-memory hook 可移除")

    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    if dry_run:
        return _result(name, "dry-run", f"[dry-run] 将移除 {removed} 个 ai-memory hook")

    mode = os.stat(config_path).st_mode & 0o777
    bak = backup_path(config_path)
    shutil.copy2(config_path, bak)

    try:
        atomic_write(config_path, rendered, mode)
        verify = _load_json_file(config_path)
        if verify is None:
            raise RuntimeError("写入后重新解析 JSON 失败")
    except Exception as e:
        restore_backup(bak, config_path, mode)
        return _result(name, "error", f"移除失败已回滚：{e}", backup=bak)

    return _result(
        name,
        "updated",
        f"已移除 {removed} 个 ai-memory hook（备份 {bak}）",
        backup=bak,
        path=config_path,
    )
