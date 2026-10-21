"""Hook 配置修复：写入 / 移除生命周期 hook 命令模板。

参照 ``mcp_fixer.fix_mcp_tool`` 的 backup → atomic-write → validate → rollback
安全链（``file_atomic`` 三件套）。命令模板来自 ``config.yaml`` 的
``hooks.clients[].template`` 段（事件 → 用户自定义命令）。

v0.29.0 起：写入命令完全由用户自定义，不再内置任何特定工具的兜底命令。
``_default_hook_command`` 返回空字符串（空 = 不写入兜底，该事件跳过）。
移除语义改为「清除该事件下全部 hook 条目（含第三方）」。

写入结构（Claude Code / WorkBuddy / Codex 风格）::

    {"hooks": {"SessionStart": [
        {"matcher": "*", "hooks": [{"type": "command", "command": "<your-command>"}]}
    ]}}
"""

import json
import os
import shutil
from typing import Any, Dict, List

from file_atomic import atomic_write, backup_path, restore_backup
from legacy_checker import _load_json_file, _norm_tool_name
from config_codec import _find_in_dict
from hooks_inventory import hooks_client_config, list_client_hook_entries
from hooks_inventory import event_name_for_client, client_supported_events


def _result(name: str, status: str, message: str, **extra: Any) -> Dict[str, Any]:
    """构造返回 dict（仿 ``mcp_fixer_render._result``）。

    status 枚举与 mcp_fixer 对齐：missing / unsupported / error / unchanged /
    dry-run / updated / created。
    """
    return {"name": name, "status": status, "message": message, **extra}


def _default_hook_command(canonical_event: str) -> str:
    """全局事件列表选中了某客户端 template 未定义的事件时的兜底命令。

    v0.29.0 起 Hook 写入命令完全由用户自定义，不再内置任何特定工具的命令；
    返回空字符串表示「不写入兜底，该事件跳过」。调用方据此把空命令的事件
    排除出写入集合（见 ``fix_hooks_tool`` 的 to_write 计算）。
    """
    return ""


def _canonical_to_snake(canonical_event: str) -> str:
    """PascalCase 规范事件名 → snake_case（``SessionStart`` → ``session_start``）。

    ``{event}`` 变量的取值口径（设计 2026-10-16 §4.1 / 2026-10-21 §3.1）：
    与客户端格式无关的规范名，便于同一条命令模板跨客户端复用。
    """
    out = []
    for ch in canonical_event:
        if ch.isupper() and out:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _client_agent_slug(hc: Dict[str, Any], client_name: str) -> str:
    """``{agent}`` 变量取值：声明值优先，缺省回退客户端名 slug 化。

    回退规则（小写 + 空格转连字符）与 config.yaml 既有 ``agent_slug``
    声明风格一致（``Claude Code`` → ``claude-code``）。
    """
    declared = hc.get("agent_slug")
    if declared and str(declared).strip():
        return str(declared).strip()
    return str(client_name or "").strip().lower().replace(" ", "-")


def _active_server_url(config: Dict[str, Any]) -> str:
    """``{server_url}`` 变量取值：活动 profile 的 url；取不到返回空串。

    返回空串时 ``_interpolate`` 会**保留 ``{server_url}`` 原样**（不吞占位
    符），dry-run 消息里可见，用户补上活动端点后重写即生效。
    """
    profiles = config.get("profiles")
    active = config.get("active_profile")
    if not isinstance(profiles, dict) or not active:
        return ""
    profile = profiles.get(active)
    if not isinstance(profile, dict):
        return ""
    url = profile.get("url")
    return str(url) if isinstance(url, str) else ""


def _interpolate(
    command: str,
    *,
    canonical: str,
    agent_slug: str,
    server_url: str,
) -> str:
    """写入前对命令模板做变量插值（v0.30.0 补齐 v0.29.0 设计 §4.1 承诺）。

    - ``{event}``       → 该事件 canonical snake_case 名（必有）；
    - ``{agent}`        → agent_slug（空则保留占位符原样）；
    - ``{server_url}``  → 活动 profile url（空则保留占位符原样）。

    用字面 ``str.replace`` 而非正则：未识别的 ``{xxx}`` / ``${VAR}`` 天然
    保留原样（不误伤 shell 语法），无占位符的命令是 no-op——已写入的旧
    命令零影响。不做转义语法（设计 §5）。
    """
    if not command:
        return command
    cmd = command.replace("{event}", _canonical_to_snake(canonical))
    if agent_slug:
        cmd = cmd.replace("{agent}", agent_slug)
    if server_url:
        cmd = cmd.replace("{server_url}", server_url)
    return cmd


def _build_hook_entry(command: str, entry_style: str = "nested") -> Dict[str, Any]:
    """构造单个 hook 事件的标准写入结构。

    ``entry_style`` 按客户端声明的实际形态分两种 —— 这两套**不可混用**，写错
    客户端不认（本机 ~/.cursor/hooks.json 实测为扁平、TRAE/Codex/WorkBuddy 为嵌套）：

    - ``nested``（默认，Claude Code / TRAE / Codex / WorkBuddy）::

        {"matcher": "*", "hooks": [{"type": "command", "command": "..."}]}

    - ``flat``（Cursor）::

        {"type": "command", "command": "...", "matcher": "*"}
    """
    if entry_style == "flat":
        return {"type": "command", "command": command, "matcher": "*"}
    return {
        "matcher": "*",
        "hooks": [{"type": "command", "command": command}],
    }


def _ensure_hook_section(data: Dict[str, Any], hook_keys: List[str]) -> Dict[str, Any]:
    """沿 hook_keys 深入取 hooks 段（不存在则创建）。

    键不存在才创建，键存在但非 dict 则抛 ``TypeError``（由调用方捕获转 error），
    避免覆盖用户既有的非对象内容。
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
    """为单个客户端写入 Hook 命令模板。

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

    # 要写入哪些事件：**优先用全局 settings.hook_events**（GUI 的「Hook 事件」设置）。
    #
    # 为什么不是直接读 template：template 把「写哪些事件」散落在 6 份客户端配置里，
    # 既无法统一管理，又会与 `events` 声明不一致 —— 实测 Codex 声明支持
    # UserPromptSubmit 但 template 缺它，审计报「缺 UserPromptSubmit」而写入永远
    # 补不上（假警报）。改为：全局列表给出**标准事件名**，这里按各客户端
    # event_format 转成它的规范名。
    #
    # 命令文案取 template 里同名事件的值；没有对应 template 时用兜底命令
    # （v0.29.0 起兜底为空 = 该事件跳过，不再硬写）。
    #
    # 能力校验（2026-10-12 按用户要求变更）：各客户端的 ``events`` 从「声明」升级为
    # **权威能力集**，写入前按它过滤 —— 只写该客户端真正认的事件。此前是「勾了就一定
    # 写得上」，会把 Cursor 独有的 beforeTabFileRead 之类写进根本不认识它的客户端；
    # 现在改为跳过并回报 ``skipped``。注意这**不是**「静默漏写」：GUI 的
    # 「IDE / Agent → Hook 配置」只列出该客户端 ``events`` 里的事件，从入口上就选不出
    # 不支持的项，兜底命令仅用于「支持但没写 template」的同名事件。
    # 客户端未声明 ``events``（如插件型 OpenCode）时不过滤，保持向后兼容。
    # 注意区分「未配置」与「配置为空列表」：
    #   - 键不存在（None）→ 未启用全局管理，回退 template（向后兼容）
    #   - 键存在但为 []     → 用户明确清空了选择，**应停用写入**，不得回退 template
    #     （否则界面显示"0 个事件已选"、实际却照旧写入，是最典型的静默不一致）
    _settings = config.get("settings") or {}
    _events_configured = "hook_events" in _settings
    configured_events = _settings.get("hook_events") or []
    skipped_unsupported: List[str] = []
    if _events_configured:
        template = {}
    if configured_events:
        event_format = hc.get("event_format")
        supported = client_supported_events(hc)
        # 插值上下文（v0.30.0）：循环外算一次，{agent}/{server_url} 对同一
        # 客户端是常量；{event} 在循环内按事件取 canonical snake_case。
        agent_slug = _client_agent_slug(hc, name)
        server_url = _active_server_url(config)
        template = {}
        for canonical in configured_events:
            client_name = event_name_for_client(canonical, event_format)
            if supported and client_name not in supported:
                skipped_unsupported.append(canonical)
                continue
            template[client_name] = _interpolate(
                (hc.get("template") or {}).get(client_name)
                or _default_hook_command(canonical),
                canonical=canonical,
                agent_slug=agent_slug,
                server_url=server_url,
            )
    if not template:
        # 三种「无事件可写」要分开说，否则会让人以为配置丢了：
        #   ① 已配置但清空     → 用户的停用选择；
        #   ② 选了但都不支持   → 能力不匹配（不是漏写，是这项属于别的客户端）；
        #   ③ 从未配置且无模板 → 该客户端没有可写入的模板。
        if _events_configured and not configured_events:
            return _result(name, "unsupported", "已选择不写入任何 hook 事件（settings.hook_events 为空）")
        if skipped_unsupported:
            return _result(
                name,
                "unsupported",
                f"所选事件该客户端均不支持，已跳过：{', '.join(skipped_unsupported)}",
            )
        return _result(name, "missing", "无 template 定义且未配置 hook_events，跳过")

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

    # 去重 + 空命令跳过（v0.29.0）：
    #   - 空命令（template 无值且兜底返回空）= 该事件不写入，跳过；
    #   - 命令级去重：要写的命令字面已在现有 hook 里出现过则跳过，避免重复条目。
    #     不再用「签名级」识别（不区分「是不是我们写的」）—— 第三方 hook 存在时，
    #     只要我们的命令与之不同，照常追加（保住「只增不减」语义）。
    existing_entries = list_client_hook_entries(tool, config)
    existing_cmds = {e.command for e in existing_entries}
    to_write = {
        ev: cmd for ev, cmd in template.items()
        if cmd and cmd.strip() and cmd not in existing_cmds
    }
    skipped_empty = [ev for ev, cmd in template.items() if not (cmd and cmd.strip())]

    if not to_write:
        n_exists = len([ev for ev, cmd in template.items()
                        if cmd and cmd.strip() and cmd in existing_cmds])
        if skipped_empty and not n_exists:
            return _result(
                name, "unsupported",
                f"所选 {len(skipped_empty)} 个事件均无命令模板（template 为空），请先填写命令",
            )
        parts = []
        if n_exists:
            parts.append(f"{n_exists} 个事件命令已存在")
        if skipped_empty:
            parts.append(f"{len(skipped_empty)} 个事件无命令模板已跳过")
        return _result(name, "unchanged", "；".join(parts) + "，无新增写入")

    # 渲染：把 template 事件写入 hook_section（条目形态按客户端声明，不可混用）
    entry_style = hc.get("entry_style", "nested")
    for event, command in to_write.items():
        if event not in hook_section or not isinstance(hook_section[event], list):
            hook_section[event] = []
        hook_section[event].append(_build_hook_entry(command, entry_style))

    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    if dry_run:
        sample = next(iter(to_write.values()))
        return _result(
            name, "dry-run",
            f"[dry-run] 将写入 {len(to_write)} 个 hook 事件：{', '.join(to_write)}"
            f"（插值样例：{sample!r}）",
        )

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

    _skip_note = f"；跳过该客户端不支持的 {len(skipped_unsupported)} 个：{', '.join(skipped_unsupported)}" if skipped_unsupported else ""
    _empty_note = f"；{len(skipped_empty)} 个事件无命令模板已跳过" if skipped_empty else ""
    return _result(
        name,
        "updated" if had_file else "created",
        (f"已写入 {len(to_write)} 个 hook 事件（备份 {bak}）" if bak else f"已创建配置并写入 {len(to_write)} 个 hook 事件") + _skip_note + _empty_note,
        backup=bak,
        path=config_path,
        skipped=skipped_unsupported,
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


def _filter_all_hooks(event_hooks: Any) -> tuple:
    """移除该事件下**全部** hook 条目（含第三方），返回 (新数组, 移除数)。

    v0.29.0 语义变更：移除不再区分来源 ——「移除 Hook」= 清除该事件下所有
    hook 配置（含非本工具写入的第三方 hook）。原配置会先备份。

    命令非空即视为一条 hook 条目（与 ``HookEntry.is_configured`` 口径一致）；
    无 command 字段或命令为空的结构性条目予以保留。
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
                if isinstance(cmd, str) and cmd.strip():
                    removed += 1
                else:
                    kept_hooks.append(h)
            if kept_hooks:
                entry = dict(entry)
                entry["hooks"] = kept_hooks
                new_entries.append(entry)
            # else: 整个 entry 的 hooks 全是命令 hook，丢弃 entry
        else:
            # 扁平结构：检查 command 字段
            cmd = entry.get("command", "")
            if isinstance(cmd, str) and cmd.strip():
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
    """移除客户端该事件下**全部** hook 条目（含第三方）。

    v0.29.0 语义变更：此前只移除本工具写入的条目、保留第三方；现改为清除
    该事件下所有 hook 配置。原配置会先备份。安全链同 ``fix_hooks_tool``。
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
        new_entries, n = _filter_all_hooks(hook_section[event])
        if n:
            removed += n
            if new_entries:
                hook_section[event] = new_entries
            else:
                del hook_section[event]

    if removed == 0:
        return _result(name, "unchanged", "无 hook 条目可移除")

    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    if dry_run:
        return _result(name, "dry-run", f"[dry-run] 将移除 {removed} 个 hook 条目（含第三方）")

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
        f"已移除 {removed} 个 hook 条目（含第三方，备份 {bak}）",
        backup=bak,
        path=config_path,
    )
