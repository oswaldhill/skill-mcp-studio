#!/usr/bin/env python3
"""
Skill MCP Studio - 主入口脚本
用法:
  python3 scan.py                        # 扫描 + 控制台报告（含前置检查）
  python3 scan.py --sync                 # 扫描前同步 git 仓库
  python3 scan.py --analyze              # 扫描 + skills 分布分析
  python3 scan.py --clean                # 扫描 + 工作区清理（提交未提交代码 + 清理临时文件）
  python3 scan.py --clean --no-interactive  # 非交互式清理（自动提交，跳过不确定项）
  python3 scan.py --clean --push         # 清理后自动推送
  python3 scan.py --report               # 生成 Markdown 报告文件
  python3 scan.py --fix                  # 自动修复（备份 + 创建 symlink）
  python3 scan.py --fix --dry-run        # 预览模式
  python3 scan.py --full                 # 完整只读检查 + MCP 探测 + 报告
"""

import sys
import os
import json
import argparse
from typing import Dict, List

# 添加 core/ 到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))

from scanner import run_scan, load_config
from reporter import print_console_report, write_markdown_report
from fixer import fix_all, print_fix_report
from ops_log import ops_log
from git_sync import (
    validate_unified_dir,
    fix_unified_dir,
    git_pull_if_needed,
    git_status,
    is_git_repo,
)
from change_tracker import (
    compute_changes,
    save_current_state,
    format_change_report,
)
from skills_analyser import (
    get_skills_summary,
    format_analysis_report,
)
from workspace_cleaner import (
    check_workspace_cleanliness,
    clean_temp_files,
    format_cleanliness_report,
    ensure_workspace_clean,
    format_clean_result,
)
from version_checker import (
    check_all_versions,
    format_version_report,
    format_version_report_markdown,
)
from cli_modes import resolve_modes
from combined_checker import check_agents, format_combined_report, result_ok
from frontmatter_audit import (
    audit_skill_frontmatter,
    format_frontmatter_report,
    format_frontmatter_markdown,
)
from mcp_fixer import fix_mcp_clients, remove_legacy_mcp_clients
from profile_loader import list_profiles, load_profile
from multi_profile_reporter import report_all_profiles
# 阶段四：按需加载与启停（L5）
from skill_state import repo_skill_names, skill_link_form
from skill_toggle import disable_skill, enable_skill
from skill_link_migrator import migrate_client_links
from skill_state_auditor import (
    verify_disable_effective,
    verify_rollback_idempotent,
)
from tool_registry import find_tool, normalized_name, detect_installation, effective_tools
from management_snapshot import build_management_snapshot
from config_store import add_discovered_client, set_unified_dir as store_set_unified_dir
# 阶段五（通用管理台）：端点库 CRUD / 挂载 / MCP 清单
from endpoint_library import endpoint_entries, validate_attachment
from endpoint_store import (
    add_endpoint as store_add_endpoint,
    remove_endpoint as store_remove_endpoint,
    update_endpoint as store_update_endpoint,
    set_client_attach as store_set_client_attach,
)
from mcp_inventory import inventory_client
# 阶段五增量：MCP 条目删除 / 清理与配置备份还原
from config_backups import list_config_backups, restore_config_backup
from mcp_entry_removal import remove_class, remove_entries


def _run_all_profiles(args, config, config_path) -> int:
    """Iterate every profile, run check_agents once each, emit a summary matrix."""
    if getattr(args, "profile", None):
        print("  ❌ --all-profiles 与 --profile 互斥")
        return 2
    try:
        scan_result = run_scan(config_path=args.config, auto_discover=args.discover)
    except Exception as e:
        print(f"  ❌ 扫描失败: {e}")
        return 2

    results = []
    all_ok = True
    config_error = False
    for name in list_profiles(config):
        try:
            bundle = load_profile(config, name, config_path=config_path)
        except Exception as e:
            # 阶段二 §7.2：profile/模板加载失败属「配置错误」→ 退出码 2，
            # 与「端点探测失败 → 1」分层；单 profile 失败不阻断其余（§6.3）。
            print(f"  ❌ profile {name!r} 加载失败: {e}")
            results.append({"profile": name, "ok": False, "error": str(e)})
            all_ok = False
            config_error = True
            continue
        try:
            result = check_agents(
                config, scan_result, live_probe=True, profile=bundle["profile"],
                endpoint_key=name,
            )
            ok = result_ok(
                result, strict_skill_state=getattr(args, "strict_skill_state", False)
            )
            all_ok = all_ok and ok
            results.append({"profile": name, "ok": ok, **result})
        except Exception as e:
            # 审计执行期异常 = 工具自身运行错误（阶段二 §7.2「内部异常」→ 2）。
            results.append({"profile": name, "ok": False, "error": str(e)})
            all_ok = False
            config_error = True

    fmt = getattr(args, "format", None) or "table"
    print("")
    print(report_all_profiles(results, fmt=fmt, active_profile=config.get("active_profile", "")))
    if config_error:
        return 2
    return 0 if all_ok else 1


def _run_list_endpoints(args, config, config_path) -> int:
    """Read-only: print the endpoint library table."""
    print("\n  端点库（endpoint library）:")
    print("  " + "-" * 62)
    for entry in endpoint_entries(config):
        print(
            f"    - {entry.get('key','?')}: name={entry.get('name','')!r} "
            f"url={entry.get('url','')!r} transport={entry.get('transport','streamable-http')!r}"
        )
    print("")
    return 0


def _run_add_endpoint(args, config, config_path) -> int:
    key = args.add_endpoint
    url = getattr(args, "endpoint_url", None) or ""
    name = getattr(args, "endpoint_name", None) or ""
    transport = getattr(args, "endpoint_transport", None) or "streamable-http"
    command = getattr(args, "endpoint_command", None)
    required_raw = getattr(args, "endpoint_required_yaml", None)
    required = {}
    if required_raw:
        try:
            required = json.loads(required_raw)
        except (ValueError, TypeError) as exc:
            print(f"  ❌ --endpoint-required-yaml 解析失败（需 JSON 对象）: {exc}")
            return 2
        if not isinstance(required, dict):
            print("  ❌ --endpoint-required-yaml 必须是 {group: [tool...]} JSON 对象")
            return 2
    if not name:
        name = key
    if transport == "stdio":
        if not command:
            print("  ❌ stdio 端点需要 --endpoint-command（本地命令）")
            return 2
        profile = {
            "name": name,
            "transport": "stdio",
            "command": command,
            "url_policy": "strict",
            "required_capabilities": required,
        }
    else:
        if not url:
            print("  ❌ streamable-http 端点需要 --endpoint-url")
            return 2
        profile = {
            "name": name,
            "url": url,
            "transport": "streamable-http",
            "url_policy": "strict",
            "required_capabilities": required,
        }
    result = store_add_endpoint(
        config, key, profile, dry_run=args.dry_run,
        auth_token=getattr(args, "endpoint_auth_token", None),
    )
    _print_store_result(result)
    return 0 if result["status"] in ("ok", "dry-run") else 2


def _run_remove_endpoint(args, config, config_path) -> int:
    result = store_remove_endpoint(config, args.remove_endpoint, dry_run=args.dry_run)
    _print_store_result(result)
    return 0 if result["status"] in ("ok", "dry-run", "unchanged") else 2


def _run_update_endpoint(args, config, config_path) -> int:
    result = store_update_endpoint(
        config,
        args.update_endpoint,
        url=getattr(args, "set_url", None),
        name=getattr(args, "set_name", None),
        auth_token=getattr(args, "endpoint_auth_token", None),
        command=getattr(args, "set_command", None),
        transport=getattr(args, "endpoint_transport", None),
        dry_run=args.dry_run,
    )
    _print_store_result(result)
    return 0 if result["status"] in ("ok", "dry-run") else 2


def _run_test_endpoint(args, config, config_path) -> int:
    """探测指定端点：MCP initialize + tools/list，返回 JSON。

    支持两种 transport：
    - streamable-http：用 endpoint url（可选 auth token）
    - stdio：用 endpoint command（本地进程）
    探测结果统一为 ProbeResult 结构。
    """
    from mcp_probe import probe_mcp

    key = args.test_endpoint
    entries = endpoint_entries(config)
    entry = next((e for e in entries if e.get("key") == key), None)

    # 允许探测「尚未入库」的端点：GUI 在「添加端点」表单里点测试时，端点还没写入
    # 端点库，唯一标识 key 自然查不到。此时用命令行内联的 url / command / transport
    # 组装成临时条目探测；查得到就用库里的存量条目。
    transport = getattr(args, "endpoint_transport", None) or (entry or {}).get("transport", "streamable-http")
    url = getattr(args, "endpoint_url", None) or (entry or {}).get("url", "")
    command = getattr(args, "endpoint_command", None) or (entry or {}).get("command", "")
    token = getattr(args, "endpoint_auth_token", None) or (entry or {}).get("auth_token", "")
    name = getattr(args, "endpoint_name", None) or (entry or {}).get("name", "") or key

    # 既没有存量条目、又没有内联的 url/command 可探测，才判定为「不存在」。
    if not entry and not (url or command):
        print(json.dumps({"ok": False, "error": f"端点 {key!r} 不存在"}, ensure_ascii=False))
        return 2

    if transport == "stdio":
        if not command:
            result = {"initialize_ok": False, "tools_list_ok": False, "tool_names": [],
                      "error": "stdio 端点缺少 command"}
        else:
            result = probe_mcp("", transport="stdio", command=command, token=token or None)
    else:
        if not url:
            result = {"initialize_ok": False, "tools_list_ok": False, "tool_names": [],
                      "error": "streamable-http 端点缺少 URL"}
        else:
            result = probe_mcp(url, token=token if token else None)
    result["endpoint_key"] = key
    result["endpoint_name"] = name
    result["transport"] = transport
    result["ok"] = result.get("initialize_ok", False) and result.get("tools_list_ok", False)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


def _run_attach_endpoints(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --attach-endpoints 需要配合 --client <客户端名>")
        return 2
    raw = args.attach_endpoints
    endpoints = [part.strip() for part in raw.split(",") if part.strip()] if raw else []
    # 校验引用的端点存在
    available = set(list_profiles(config))
    for key in endpoints:
        if key not in available:
            print(f"  ❌ 端点 {key!r} 不存在；可用: {sorted(available)}")
            return 2
    result = store_set_client_attach(config, client, endpoints, dry_run=args.dry_run)
    _print_store_result(result)
    return 0 if result["status"] in ("ok", "dry-run") else 2


def _run_list_mcp_inventory(args, config, config_path) -> int:
    """Read-only: per-client MCP entry dump + classification (需求 ③a 自动识别)."""
    try:
        validate_attachment(config)
    except Exception as exc:
        print(f"  ❌ 挂载校验失败: {exc}")
        return 2
    endpoints = endpoint_entries(config)
    # profile 级 legacy_names 与各 tool 级 legacy_names 并集（与检查模型同语义）。
    profile_legacy: set = set()
    for entry in endpoints:
        for ln in entry.get("legacy_names", []) or []:
            profile_legacy.add(ln)
    print("\n  MCP 清单（每客户端已配置的全部 MCP 条目）:")
    for tool in config.get("mcp_tools", []) or []:
        name = tool.get("name", "Unknown")
        legacy = sorted(profile_legacy | set(tool.get("legacy_names", []) or []))
        entries = inventory_client(
            tool,
            endpoint_entries=endpoints,
            legacy_names=legacy,
        )
        if not entries:
            print(f"    [{name}]（未读到 MCP 条目）")
            continue
        print(f"    [{name}]")
        for entry in entries:
            mark = {"attached": "✅", "legacy": "⚠️ ", "unmanaged": "❓"}.get(
                entry.classification, "  "
            )
            target = entry.url or (entry.command or "")
            print(f"      {mark} {entry.classification:<9} {entry.key}: {target}")
    print("")
    return 0


def _run_management(args, config, config_path) -> int:
    """输出三栏管理台管理快照 JSON（stage-5 P5，只读）。"""
    try:
        payload = build_management_snapshot(
            config,
            config_path=config_path,
            live_probe=True,
            auto_discover=getattr(args, "discover", None),
        )
    except Exception as exc:
        print(json.dumps({"kind": "management", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_version(args, config, config_path) -> int:
    """只读输出应用版本信息（X.Y.Z + build），供「关于」页。"""
    from app_info import read_app_info

    print(json.dumps(read_app_info(), ensure_ascii=False, indent=2))
    return 0


def _run_add_client(args, config, config_path) -> int:
    """写操作：手动添加客户端到 discovered 持久化（stage-5 P7 / FEAT-1 MCP 字段）。"""
    mcp_attach = getattr(args, "client_mcp_attach", None)
    app_bundle = getattr(args, "client_app_bundle", None)
    command = getattr(args, "client_command", None)
    config_paths = getattr(args, "client_config_paths", None)
    install = {}
    if app_bundle or command or config_paths:
        install = {
            "app_bundles": [app_bundle] if app_bundle else [],
            "commands": [command] if command else [],
            "config_paths": [p.strip() for p in config_paths.split(",")] if config_paths else [],
        }
    result = add_discovered_client(
        args.add_client,
        skills_path=getattr(args, "client_skills_path", None),
        client_type=getattr(args, "client_type", None),
        config_path=getattr(args, "client_config_path", None),
        mcp_format=getattr(args, "client_mcp_format", None),
        mcp_key_path=getattr(args, "client_mcp_key_path", None),
        mcp_attach=[k.strip() for k in mcp_attach.split(",")] if mcp_attach else None,
        install=install or None,
        dry_run=args.dry_run,
    )
    _print_store_result(result)
    return 0 if result["status"] in ("ok", "dry-run", "unchanged") else 2


def _run_update_client(args, config, config_path) -> int:
    """写操作：更新已注册客户端的安装证据/目录设置（「编辑客户端」）。"""
    from config_store import update_discovered_client

    def _split(value):
        return [p.strip() for p in value.split(",")] if value else None

    result = update_discovered_client(
        args.update_client,
        app_bundles=_split(getattr(args, "app_bundles", None)),
        commands=_split(getattr(args, "commands", None)),
        config_paths=_split(getattr(args, "config_paths", None)),
        skills_path=getattr(args, "skills_path", None),
        mcp_config_path=getattr(args, "mcp_config_path", None),
        scan_dir=getattr(args, "scan_dir", None),
        dry_run=args.dry_run,
    )
    _print_store_result(result)
    return 0 if result["status"] in ("ok", "dry-run", "unchanged") else 2


def _run_add_defaults(args, config, config_path) -> int:
    """写操作：一键「默认添加」主流 IDE/Agent（整改）。"""
    from config_store import add_default_clients

    result = add_default_clients(dry_run=args.dry_run)
    if args.dry_run:
        print(f"[dry-run] 将默认添加 {result['total']} 个主流 IDE/Agent，新增 {result['added']}")
        for r in result["results"]:
            print(f"  - {r['name']}: {r['status']}")
    else:
        print(f"已默认添加 {result['added']} 个（跳过已存在 {result['unchanged']} 个，共 {result['total']} 个）")
    return 0


def _run_set_unified_dir(args, config, config_path) -> int:
    """写操作：写入 config.yaml 的 unified_skills_dir（stage-5 P7）。"""
    result = store_set_unified_dir(args.set_unified_dir, config_path=config_path, dry_run=args.dry_run)
    _print_store_result(result)
    return 0 if result["status"] in ("ok", "dry-run", "unchanged") else 2


def _unified_dir_from(args, config) -> str:
    """Resolve the operative unified skills dir for skill-level file ops."""
    return args.unified_dir or config.get("unified_skills_dir") or "~/.skills-manager/skills"


def _print_skill_op(result) -> None:
    status = result.get("status", "error")
    icon = {"ok": "  ✅", "dry-run": "  🔍", "unchanged": "  ⏭️ "}.get(status, "  ❌ ")
    print(f"{icon} {status}: {result.get('message', '')}")
    for step in result.get("steps") or []:
        print(f"      [{step.get('status', '?')}] {step.get('step')}: {step.get('message', '')}")
    if result.get("backup"):
        print(f"      备份: {result['backup']}")
    if result.get("path") and status in ("ok", "dry-run"):
        print(f"      位置: {result['path']}")


def _run_skill_backup(args, config, config_path) -> int:
    from skill_ops import backup_skill

    result = backup_skill(_unified_dir_from(args, config), args.backup_skill, dry_run=args.dry_run)
    _print_skill_op(result)
    return 0 if result["status"] in ("ok", "dry-run") else 2


def _run_skill_export(args, config, config_path) -> int:
    from skill_ops import export_skill

    result = export_skill(_unified_dir_from(args, config), args.export_skill, dry_run=args.dry_run)
    _print_skill_op(result)
    return 0 if result["status"] in ("ok", "dry-run") else 2


def _run_skill_rename(args, config, config_path) -> int:
    from skill_ops import rename_skill_meta

    if not (args.new_name or args.new_description):
        print("  ❌ --rename-skill 需要配合 --new-name 或 --new-description")
        return 2
    result = rename_skill_meta(
        _unified_dir_from(args, config),
        args.rename_skill,
        new_name=args.new_name,
        new_description=args.new_description,
        dry_run=args.dry_run,
    )
    _print_skill_op(result)
    return 0 if result["status"] in ("ok", "dry-run", "unchanged") else 2


def _run_skill_delete(args, config, config_path) -> int:
    from skill_ops import soft_delete_skill

    result = soft_delete_skill(_unified_dir_from(args, config), args.delete_skill, dry_run=args.dry_run)
    _print_skill_op(result)
    return 0 if result["status"] in ("ok", "dry-run") else 2


def _run_remove_client(args, config, config_path) -> int:
    """写操作：移除客户端（本机停用 + 残留配置 + skills 链接）。

    已安装（有 app/cli）拒绝；config_only / 未安装的客户端移除 discovered 条目、
    在本机 overlay 记录停用（不删 trunk 共享注册表）、删除残留配置文件与 skills 软链接。
    """
    from config_store import remove_managed_client

    result = remove_managed_client(config, args.remove_client, dry_run=args.dry_run)
    status = result.get("status", "error")
    icon = {"ok": "  ✅", "dry-run": "  🔍", "unchanged": "  ⏭️ ", "skip": "  ⏭️ ", "error": "  ❌"}.get(status, "  ⚠️ ")
    print(f"{icon} {status}: {result.get('message', '')}")
    for step in result.get("steps") or []:
        mark = {"ok": "✓", "dry-run": "?", "error": "x"}.get(step.get("status"), "?")
        print(f"      [{mark}] {step.get('step')}: {step.get('message', '')}")
    backup = result.get("backup")
    if backup:
        print(f"      备份: {backup}")
    return 0 if status in ("ok", "dry-run", "unchanged", "skip") else 2


def _run_cleanup_config(args, config, config_path) -> int:
    """写操作：移除 config_only / 未安装客户端（本机停用 + 删残留配置）。

    用户语义「清理 = 删除」：从 discovered_tools.yaml 移除条目、在本机 overlay 记录
    停用（不删 trunk 共享注册表），再删除残留配置文件（带备份）。已安装（有 app/cli）
    的客户端拒绝删除。
    """
    from config_store import remove_managed_client

    if not getattr(args, "client", None):
        print("  ❌ --cleanup-config 需要配合 --client <名称> 指定目标客户端")
        return 2
    result = remove_managed_client(config, args.client, dry_run=args.dry_run)
    status = result.get("status", "error")
    icon = {"ok": "  ✅", "dry-run": "  🔍", "unchanged": "  ⏭️ ", "skip": "  ⏭️ ", "error": "  ❌"}.get(status, "  ⚠️ ")
    print(f"{icon} {status}: {result.get('message', '')}")
    for step in result.get("steps") or []:
        line = f"      [{'?' if step.get('status') == 'dry-run' else ('x' if step.get('status') == 'error' else '✓')}] {step.get('step')}: {step.get('message', '')}"
        print(line)
        for f in step.get("files") or []:
            print(f"          - {f}")
    backup = result.get("backup")
    if backup:
        print(f"      备份: {backup}")
    return 0 if status in ("ok", "dry-run", "unchanged", "skip") else 2


def _print_store_result(result) -> None:
    status = result.get("status", "error")
    icon = {"ok": "  ✅", "dry-run": "  🔍", "unchanged": "  ⏭️ ", "error": "  ❌"}.get(status, "  ⚠️ ")
    print(f"{icon} {status}: {result.get('message', '')} (path={result.get('path') or '—'})")


def _print_mcp_result(result, as_json: bool) -> None:
    """MCP 条目删除 / 清理 / 还原的统一输出。

    ``--format json`` 时输出结构化对象，前端据此判定结果，不再对 stdout 做
    字符串匹配（旧 ``--remove-legacy-mcp`` 保持原有字符串输出不变）。
    """
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    mark = "✅" if result.get("status") in ("updated", "unchanged") else "❌"
    print(f"  {mark} {result.get('message', '')}")
    if result.get("path"):
        print(f"    配置: {result['path']}")
    if result.get("backup"):
        print(f"    备份: {result['backup']}")
    if result.get("attach_updated"):
        print(f"    已同步摘除挂载声明: {', '.join(result['attach_updated'])}")
    for item in result.get("skipped_high_risk") or []:
        print(f"    ⏭️ 跳过高风险: {item['key']}（{item['reason']}）")


def _find_client_tool(config, client_name):
    """按归一化名在有效客户端里查注册表条目。

    与 ``mcp_fixer`` 对 ``--client`` 的既有口径一致：只比客户端名（归一化），
    不匹配 aliases。
    """
    wanted = normalized_name(client_name)
    for tool in effective_tools(config):
        if isinstance(tool, dict) and normalized_name(tool.get("name", "")) == wanted:
            return tool
    return None


def _run_remove_mcp_entry(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --remove-mcp-entry 需要配合 --client <客户端名>")
        return 2
    keys = [part.strip() for part in (args.remove_mcp_entry or "").split(",") if part.strip()]
    if not keys:
        print("  ❌ --remove-mcp-entry 需要至少一个条目 key")
        return 2
    result = remove_entries(
        config, client, keys,
        force_high_risk=bool(args.force_high_risk), dry_run=bool(args.dry_run),
    )
    _print_mcp_result(result, getattr(args, "format", None) == "json")
    return 0 if result.get("status") in ("updated", "unchanged", "dry-run") else 2


def _run_remove_mcp_class(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --remove-mcp-class 需要配合 --client <客户端名>")
        return 2
    result = remove_class(
        config, client, args.remove_mcp_class,
        include_high_risk=bool(args.include_high_risk), dry_run=bool(args.dry_run),
    )
    _print_mcp_result(result, getattr(args, "format", None) == "json")
    return 0 if result.get("status") in ("updated", "unchanged", "dry-run") else 2


def _run_list_config_backups(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --list-config-backups 需要配合 --client <客户端名>")
        return 2
    tool = _find_client_tool(config, client)
    if tool is None:
        print(f"  ❌ 未找到客户端 {client}")
        return 2
    backups = list_config_backups(tool.get("config_path", ""))
    if getattr(args, "format", None) == "json":
        print(json.dumps(
            {"status": "ok", "client": client, "config_path": tool.get("config_path", ""),
             "backups": backups}, ensure_ascii=False, indent=2))
        return 0
    print(f"  {client} 的配置备份（{len(backups)} 个）:")
    for item in backups:
        print(f"    {item['mtime_text']}  {item['size']:>8} B  {item['path']}")
    return 0


def _run_restore_config_backup(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --restore-config-backup 需要配合 --client <客户端名>")
        return 2
    tool = _find_client_tool(config, client)
    if tool is None:
        print(f"  ❌ 未找到客户端 {client}")
        return 2
    result = restore_config_backup(tool, args.restore_config_backup, dry_run=bool(args.dry_run))
    _print_mcp_result(result, getattr(args, "format", None) == "json")
    return 0 if result.get("status") in ("updated", "dry-run") else 2


def _run_single_profile_snapshot(args, config, config_path) -> int:
    """Machine-readable single-profile snapshot (phase 3 §14.A / P2).

    Same JSON/CSV shape as ``--all-profiles`` (a one-element ``results`` list) so
    the single-profile GUI view and CI assertions consume one contract. Only
    ``json``/``csv``/``md`` reach this path; ``table`` keeps the legacy 11-phase
    human report.
    """
    fmt = getattr(args, "format", None) or "json"
    try:
        bundle = load_profile(config, getattr(args, "profile", None), config_path=config_path)
    except Exception as e:
        print(f"  ❌ profile 加载失败: {e}")
        return 2
    name = bundle["name"]
    profile = bundle["profile"]

    try:
        scan_result = run_scan(config_path=config_path, auto_discover=args.discover)
        result = check_agents(
            config, scan_result, live_probe=True, profile=profile, endpoint_key=name
        )
    except Exception as e:
        print(f"  ❌ 审计失败: {e}")
        return 2

    ok = result_ok(
        result, strict_skill_state=getattr(args, "strict_skill_state", False)
    )
    results = [{"profile": name, "ok": ok, **result}]
    print(report_all_profiles(results, fmt=fmt, active_profile=name))
    return 0 if ok else 1


def _non_agent_names(config_path) -> set:
    """FEAT-7 口径：声明 non_agent 的客户端（如 CC Switch）不进技能面板。

    它同时管着合并预览（GUI「修复链接」弹窗）的统计与实写：`~/.cc-switch/skills`
    是 CC Switch 自管的挂载点，本工具不代它修链接，也不该计入"总路径"。
    曾因这里漏了过滤，卡片显示 7 条路径而用户实际只有 6 个 IDE/Agent。
    """
    return {normalized_name(t.get("name", ""))
            for t in effective_tools(load_config(config_path))
            if t.get("name") and t.get("non_agent")}


def _drop_non_agent_rows(scan_result, config_path):
    """按 _non_agent_names 口径过滤扫描行。预览与实写共用，杜绝两处不同源。"""
    names = _non_agent_names(config_path)
    if not names:
        return scan_result
    return {**scan_result, "results": [
        r for r in scan_result.get("results", [])
        if normalized_name(r.get("tool_name", "")) not in names
    ]}


def _run_fix_skills_preview(args, config, config_path) -> int:
    """「一键合并预览」机读出口（--fix-skills --format json）。

    聚合三份结构化数据供 GUI 表格渲染：
    - ``scan``     : 全量扫描清单 + 汇总（run_scan）
    - ``changes``  : 变更报告（compute_changes，含上次扫描时间）
    - ``fix``      : 修复计划（fix_all + dry_run，含路径/备份/symlink 操作）

    严格只读：修复计划始终以 dry_run=True 生成（真正写入走 --fix-skills 的
    11 阶段主流程，由 GUI 的「确认实写」按钮触发）。
    """
    tools = effective_tools(load_config(config_path))
    # 与 IDE/Agent 页保持统一（FEAT-7）：只纳入「已安装 / 仅配置」的客户端，
    # 过滤掉 install_state == "none" 的幽灵条目与 non_agent 客户端。
    # 过滤必须发生在 fix_all 之前：修复计划要和表格同源，否则预览显示 N 项、
    # 实写却按另一套口径执行。
    install_by_name = {
        normalized_name(t.get("name", "")): detect_installation(t)["install_state"]
        for t in tools
        if t.get("name")
    }

    try:
        scan_result = run_scan(config_path=config_path, auto_discover=args.discover)
    except Exception as exc:  # 预览失败不得拖垮 GUI
        print(json.dumps({"kind": "fix-skills-preview", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    scan_result = _drop_non_agent_rows(scan_result, config_path)
    scan_results = [
        r for r in scan_result.get("results", [])
        if install_by_name.get(normalized_name(r.get("tool_name", ""))) != "none"
    ]
    scan_result = {**scan_result, "results": scan_results}
    try:
        fix_result = fix_all(scan_result, dry_run=True, client=args.client)
        changes = compute_changes(scan_result)
    except Exception as exc:
        print(json.dumps({"kind": "fix-skills-preview", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    payload = {
        "kind": "fix-skills-preview",
        # 列表项只透传表格必需字段，避免把内部 expanded_path 等冗余字段喂给 GUI
        "scan": {
            "unified_dir": scan_result.get("unified_dir", ""),
            "summary": scan_result.get("summary", {}),
            "results": [
                {
                    "tool_name": r.get("tool_name", ""),
                    "type": r.get("type", ""),
                    "is_installed": bool(r.get("is_installed", False)),
                    "install_state": install_by_name.get(normalized_name(r.get("tool_name", "")), "none"),
                    "path": r.get("path", ""),
                    "expanded_path": r.get("expanded_path", ""),
                    "status": r.get("status", ""),
                }
                for r in scan_results
            ],
        },
        "changes": {
            "first_run": changes.get("first_run", False),
            "last_scan_time": changes.get("last_scan_time", ""),
            "tools_added": changes.get("tools_added", []),
            "tools_removed": changes.get("tools_removed", []),
            "tools_status_changed": changes.get("tools_status_changed", []),
            "summary_changes": changes.get("summary_changes", {}),
        },
        "fix": {
            "total": fix_result.get("total", 0),
            "fixed": fix_result.get("fixed", 0),
            "errors": fix_result.get("errors", 0),
            "dry_run": fix_result.get("dry_run", True),
            "details": fix_result.get("details", []),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


# ====================================================================
# 阶段四（按需加载与启停，L5）入口：只读列表 / 只读审计 / 启停写操作。
# 审计通道严格只读（ADR-19）；写操作仅在 --enable-skill / --disable-skill
# 显式触发，并复用 mcp_fixer 备份-原子-校验-回滚范式（ADR-18）。
# ====================================================================


def _stage4_client_skills_dirs(scan_result) -> Dict[str, List[str]]:
    """Map normalized client name -> its scanned skills dirs (installed rows only)."""
    dirs: Dict[str, List[str]] = {}
    for row in scan_result.get("results", []):
        if not row.get("is_installed"):
            continue
        key = normalized_name(row.get("tool_name", ""))
        path = row.get("expanded_path")
        if key and path:
            dirs.setdefault(key, []).append(path)
    return dirs


def _run_list_skill_states(args, config, config_path) -> int:
    """Read-only: print the per-client skill enable/disable matrix (design §7)."""
    unified = args.unified_dir or config.get("unified_skills_dir", "~/.skills")
    try:
        scan_result = run_scan(config_path=config_path, auto_discover=args.discover)
        bundle = load_profile(config, getattr(args, "profile", None), config_path=config_path)
        result = check_agents(config, scan_result, live_probe=False, profile=bundle["profile"])
    except Exception as e:
        print(f"  ❌ 审计失败: {e}")
        return 2

    records = [r for r in result.get("records", []) if r.get("installed")]
    if getattr(args, "client", None):
        wanted = normalized_name(args.client)
        records = [r for r in records if normalized_name(r.get("name", "")) == wanted]
        if not records:
            print(f"  ❌ 客户端 {args.client!r} 未找到或未安装")
            return 2

    skills = sorted({s for r in records for s in (r.get("skill_states") or {})})
    print("")
    print("=" * 78)
    print("  技能启停状态矩阵（L5）")
    print("=" * 78)
    if not records or not skills:
        print("  （无可展示的客户端技能状态：没有已安装客户端或仓库无技能）")
        print("")
        return 0
    name_w = max([len("Skill")] + [len(s) for s in skills]) + 2
    col_widths = [max(len(r["name"]), len("state")) + 2 for r in records]
    header = f"  {'Skill':<{name_w}}" + "".join(
        f"{r['name']:>{w}}" for r, w in zip(records, col_widths)
    )
    print(header)
    print("  " + "-" * (name_w + sum(col_widths)))
    for skill in skills:
        cells = ""
        for record, width in zip(records, col_widths):
            state = (record.get("skill_states") or {}).get(skill, "")
            token = {"enabled": "on", "disabled": "off"}.get(state, "-")
            cells += f"{token:>{width}}"
        print(f"  {skill:<{name_w}}{cells}")
    print("")
    print(f"  （on=enabled off=disabled -=未审计；{len(records)} 个客户端 × {len(skills)} 个仓库技能）")
    print("")
    return 0


def _run_skill_audit(args, config, config_path) -> int:
    """Read-only audit (ADR-19): drift + disable-effective + rollback gate."""
    unified = args.unified_dir or config.get("unified_skills_dir", "~/.skills")
    try:
        scan_result = run_scan(config_path=config_path, auto_discover=args.discover)
        bundle = load_profile(config, getattr(args, "profile", None), config_path=config_path)
        result = check_agents(config, scan_result, live_probe=False, profile=bundle["profile"])
    except Exception as e:
        print(f"  ❌ 审计失败: {e}")
        return 2

    dirs_by_client = _stage4_client_skills_dirs(scan_result)
    drift = result.get("skill_state_drift", [])
    consistent = result.get("summary", {}).get("skill_state_consistent", True)

    ineffective = []
    gates = []
    for record in result.get("records", []):
        if not record.get("installed"):
            continue
        states = record.get("skill_states") or {}
        if not states:
            continue
        client_dirs = dirs_by_client.get(normalized_name(record.get("name", "")), [])
        if not client_dirs:
            continue
        cdir = client_dirs[0]
        native = set(record.get("native_disabled_skills") or [])
        for skill, state in states.items():
            # 原生禁用项由客户端运行时管理：链接仍在属正常，不做残留检查。
            if state == "disabled" and skill not in native and not verify_disable_effective(cdir, unified, skill):
                ineffective.append((record["name"], skill))
        # Rollback-idempotence gate: sandboxed, non-destructive; proves the
        # client's toggle mechanism is reversible (design §6.2 step 4).
        if record.get("skill_link_form") == "per_skill" and states:
            first_skill = sorted(states)[0]
            tool = {"name": record["name"], "skills_paths": [cdir], "fix_supported": True}
            gate = verify_rollback_idempotent(tool, first_skill, unified)
            gates.append((record["name"], gate["ok"], gate["message"]))

    print("")
    print("=" * 78)
    print("  启停一致性审计（L5，只读）")
    print("=" * 78)
    print(f"  启停状态一致性: {'✅ 一致' if consistent else '❌ 存在漂移'}")
    for d in drift:
        print(f"    ⚠️ 技能 {d['skill']}: {d['states']} → 漂移客户端 {', '.join(d['drift_clients'])}")
    if ineffective:
        print(f"  禁用生效验证: ❌ {len(ineffective)} 项未生效")
        for name, skill in ineffective:
            print(f"    ⚠️ {name}/{skill}: symlink 仍存在，禁用未生效")
    else:
        print("  禁用生效验证: ✅ 全部生效")
    gate_fail = [(n, m) for n, ok, m in gates if not ok]
    if gate_fail:
        print(f"  回滚幂等 gate: ❌ {len(gate_fail)} 个客户端失败")
        for name, msg in gate_fail:
            print(f"    ⚠️ {name}: {msg}")
    elif gates:
        print("  回滚幂等 gate: ✅ 全部通过")
    else:
        print("  回滚幂等 gate: ⏭️ 无 per_skill 形态客户端，无需运行（root 形态仅整体审计）")
    print("")

    # 漂移 / 禁用未生效 / 回滚 gate 失败任一即为不合规（§9）。
    # --strict-skill-state 对审计通道是内建的：一致性已包含在 ok 判定里。
    ok = consistent and not ineffective and not gate_fail
    return 0 if ok else 1


def _run_skill_toggle(args, config, config_path) -> int:
    """Enable/disable one skill across per_skill-form clients (design §6.1)."""
    action = "enable" if args.enable_skill else "disable"
    skill = args.enable_skill or args.disable_skill
    unified = args.unified_dir or config.get("unified_skills_dir", "~/.skills")

    # Gate: skill must exist in the unified repo (exit 2, config error, §9).
    if skill not in repo_skill_names(unified):
        print(f"  ❌ 技能 {skill!r} 不在统一仓库 {unified} 中")
        return 2
    try:
        scan_result = run_scan(config_path=config_path, auto_discover=args.discover)
    except Exception as e:
        print(f"  ❌ 扫描失败: {e}")
        return 2

    dirs_by_client = _stage4_client_skills_dirs(scan_result)
    if getattr(args, "client", None):
        wanted = normalized_name(args.client)
        targets = {k: v for k, v in dirs_by_client.items() if k == wanted}
        if not targets:
            print(f"  ❌ 客户端 {args.client!r} 未找到或未安装")
            return 2
    else:
        targets = dirs_by_client
    if not targets:
        print("  ❌ 没有可操作的已安装客户端")
        return 2

    mcp_registry = config.get("mcp_tools", [])
    toggle_results = []
    exit_code = 0
    for key in sorted(targets):
        dirs = targets[key]
        display_name = key
        for row in scan_result.get("results", []):
            if normalized_name(row.get("tool_name", "")) == key:
                display_name = row.get("tool_name", key)
                break
        registry_entry = find_tool(mcp_registry, display_name)
        tool = {
            "name": display_name,
            "skills_paths": dirs,
            "fix_supported": registry_entry.get("fix_supported", True) if registry_entry else True,
        }
        form = skill_link_form(dirs[0], unified)
        if form != "per_skill":
            if getattr(args, "client", None):
                print(f"  ❌ 客户端 {display_name} 为 {form} 形态，不支持单技能启停（见设计 §14.1）")
                return 2
            print(f"  ⏭️ 跳过 {display_name}: {form} 形态不支持单技能启停")
            continue
        fn = enable_skill if action == "enable" else disable_skill
        res = fn(tool, skill, unified, dry_run=args.dry_run)
        toggle_results.append(res)
        if res["status"] == "error":
            if "rollback failed" in res["message"]:
                print(f"  ❌ {res['name']}: {res['message']}")
                return 2
            exit_code = 1

    marks = {"updated": "✅", "unchanged": "✅", "dry-run": "🔍", "skip": "⏭️", "unsupported": "⏭️", "error": "❌"}
    print("")
    for res in toggle_results:
        print(f"  {marks.get(res['status'], '•')} {action} {skill} @ {res['name']}: {res['status']} - {res['message']}")

    # 复检闭环（design §6.1 step 7）：非 dry-run 时重扫并重跑 check_agents 展示
    # 最新启停状态；退出码由启停自身状态决定（§9），不受 MCP 配置态牵连。
    if not args.dry_run and toggle_results:
        try:
            rescan = run_scan(config_path=config_path, auto_discover=args.discover)
            bundle = load_profile(config, getattr(args, "profile", None), config_path=config_path)
            combined = check_agents(config, rescan, live_probe=args.probe_mcp, profile=bundle["profile"])
            print(format_combined_report(combined))
        except Exception as e:
            print(f"\n  ⚠️ 复检失败: {e}")
    print("")
    return exit_code


def _run_market(args) -> int:
    """`--market` 只读出口。

    全量禁止写操作：安装/升级由 core/skill_market_ops.py 另行处理。
    **不调用 `npx skills check`** —— 该命令名为检查、实为升级。
    """
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


def _run_market_write(args) -> int:
    """市场写操作出口（安装 / 升级）。

    必须先 --yes：市场技能来自第三方仓库，静默安装是供应链风险。
    """
    from skill_market_ops import execute_plan, plan_install, plan_upgrade

    if args.market_install and args.market_upgrade:
        print("  ❌ --market-install 与 --market-upgrade 互斥")
        return 2

    if args.market_install:
        plan = plan_install(args.market_install)
        what = f"安装 {args.market_install}"
    else:
        names = [n for n in str(args.market_upgrade).split(",") if n.strip()]
        plan = plan_upgrade(names)
        what = "升级 " + "、".join(plan.get("names") or names)

    if not plan.get("ok"):
        print(f"  ❌ {plan.get('reason')}")
        return 2

    if not getattr(args, "yes", False):
        print(f"  待执行：{what}")
        print(f"  命令：npx skills {' '.join(plan['argv'])}")
        print("  这是写操作，确认后请加 --yes 重跑。")
        return 2  # 非 0：本次未执行任何写操作

    result = execute_plan(plan)
    want_json = getattr(args, "format", None) == "json"
    if want_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        mark = "完成" if result["ok"] else "失败"
        print(f"  {what} {mark}")
        if result.get("verify"):
            v = result["verify"]
            print(f"  已确认在统一库: {len(v.get('present') or [])} 个"
                  f"，缺失 {len(v.get('missing') or [])} 个")
        if not result["ok"] and result.get("stderr"):
            print(f"  {result['stderr'][:300]}")
    return 0 if result["ok"] else 1


def _print_market(payload: dict, kind: str) -> None:
    """人读输出。与 --format json 同源，避免两套口径。"""
    if payload.get("error"):
        print(f"  ❌ {payload['error']}")
        return
    if kind == "sources":
        for _sid, s in (payload.get("sources") or {}).items():
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
                print(f"    {r['name']:32} 远端 {r.get('remote_commit')}")


def _run_skill_usage(args) -> int:
    """`--skill-usage` 只读出口：技能使用统计。

    数据源是各客户端落盘的会话日志（当前仅 Codex 可靠），全程只读、不写盘。
    判据只认工具调用记录（function_call / custom_tool_call）里的技能路径，
    会话注入的技能清单与工具返回内容都不算使用，否则命中数会虚高到全量误报。
    """
    from skill_usage import scan_usage, summarize_text

    want_json = getattr(args, "format", None) == "json"
    try:
        payload = scan_usage(
            since=getattr(args, "usage_since", None),
            progress_path=getattr(args, "progress_file", None),
        )
    except Exception as exc:                      # 日志缺失/损坏不应中断其他流程
        payload = {"error": str(exc)}

    if want_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("error"):
        print(f"  ❌ {payload['error']}")
    else:
        print(summarize_text(payload))
    return 0


def _run_merge_advice(args) -> int:
    """`--merge-advice` 只读出口：技能整理建议（FEAT-11）。

    全程只读：判据在 `skill_merge_advisor` 内，本函数不写盘、不移动、不删除。
    `--usage-since` 复用于窗口过滤，因为 `load`/`sessions` 参与保留者打分。
    """
    from skill_merge_advisor import scan_advice, summarize_text

    want_json = getattr(args, "format", None) == "json"
    try:
        payload = scan_advice(since=getattr(args, "usage_since", None))
    except Exception as exc:                      # 库缺失等异常不中断其他流程
        payload = {"error": str(exc)}

    if want_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("error"):
        print(f"  ❌ {payload['error']}")
    else:
        print(summarize_text(payload))
    return 0


def _run_skill_migrate(args, config, config_path) -> int:
    """Migrate root-form clients to per-skill symlinks (design §14.1 P2).

    Unlocks single-skill enable/disable: root-form clients only support
    whole-repo visibility. Exit codes follow §9: 0 all migrated/unchanged,
    1 a migration failed but rolled back cleanly, 2 config/tool error
    (unknown client, explicit client not migratable, rollback failure).
    """
    unified = args.unified_dir or config.get("unified_skills_dir", "~/.skills")
    try:
        scan_result = run_scan(config_path=config_path, auto_discover=args.discover)
    except Exception as e:
        print(f"  ❌ 扫描失败: {e}")
        return 2

    dirs_by_client = _stage4_client_skills_dirs(scan_result)
    if getattr(args, "client", None):
        wanted = normalized_name(args.client)
        targets = {k: v for k, v in dirs_by_client.items() if k == wanted}
        if not targets:
            print(f"  ❌ 客户端 {args.client!r} 未找到或未安装")
            return 2
    else:
        targets = dirs_by_client
    if not targets:
        print("  ❌ 没有可迁移的已安装客户端")
        return 2

    mcp_registry = config.get("mcp_tools", [])
    migrate_results = []
    exit_code = 0
    for key in sorted(targets):
        dirs = targets[key]
        display_name = key
        for row in scan_result.get("results", []):
            if normalized_name(row.get("tool_name", "")) == key:
                display_name = row.get("tool_name", key)
                break
        registry_entry = find_tool(mcp_registry, display_name)
        tool = {
            "name": display_name,
            "skills_paths": dirs,
            "fix_supported": registry_entry.get("fix_supported", True) if registry_entry else True,
        }
        res = migrate_client_links(tool, unified, dry_run=args.dry_run)
        # 显式 --client 时，不可迁移的结果按配置错误退出（§9）；
        # 缺省全量模式下仅跳过并提示。
        if getattr(args, "client", None) and res["status"] in ("skip", "unsupported", "error"):
            print(f"  ❌ 客户端 {display_name}: {res['status']} - {res['message']}")
            return 2
        migrate_results.append(res)
        if res["status"] == "error":
            if "rollback failed" in res["message"]:
                print(f"  ❌ {res['name']}: {res['message']}")
                return 2
            exit_code = 1

    marks = {"migrated": "✅", "unchanged": "✅", "dry-run": "🔍", "skip": "⏭️", "unsupported": "⏭️", "error": "❌"}
    print("")
    for res in migrate_results:
        print(f"  {marks.get(res['status'], '•')} migrate @ {res['name']}: {res['status']} - {res['message']}")

    # 复检闭环：非 dry-run 时重扫并展示最新形态/启停状态。
    if not args.dry_run and migrate_results:
        try:
            rescan = run_scan(config_path=config_path, auto_discover=args.discover)
            bundle = load_profile(config, getattr(args, "profile", None), config_path=config_path)
            combined = check_agents(config, rescan, live_probe=False, profile=bundle["profile"])
            print(format_combined_report(combined))
        except Exception as e:
            print(f"\n  ⚠️ 复检失败: {e}")
    print("")
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    """Construct the full CLI argument parser (A-7: 从 main() 抽出，拆分 god-function)."""
    parser = argparse.ArgumentParser(
        description="Skill MCP Studio - IDE/Agent Skills 统一化与 Hermes MCP 接入管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scan.py                             # 扫描并输出控制台报告
  python3 scan.py --sync                      # 扫描前同步 git 仓库
  python3 scan.py --analyze                   # 包含 Skills 分布分析
  python3 scan.py --clean                     # 包含临时文件清理
  python3 scan.py --report                    # 生成 Markdown 报告文件
  python3 scan.py --fix                       # 自动修复（备份 + 创建 symlink）
  python3 scan.py --fix --dry-run             # 预览模式（不实际修改）
  python3 scan.py --setup-all                  # 设置并检查所有已安装 IDE/Agent
  python3 scan.py --full                      # 完整只读检查 + MCP 探测 + 报告
  python3 scan.py --hermes                    # 检查各工具 Hermes 网关接入状态
  python3 scan.py --unified-dir /path         # 指定统一目录
  python3 scan.py --list-skill-states         # 只读列出各客户端技能启停状态
  python3 scan.py --audit-skill-states        # 只读审计启停一致性（漂移/生效/幂等）
  python3 scan.py --enable-skill tdai --dry-run   # 预览启用某技能
  python3 scan.py --disable-skill tdai --client "Cursor"  # 禁用指定客户端的某技能
  python3 scan.py --migrate-skill-links --dry-run  # 预览 root→逐技能链接迁移
  python3 scan.py --migrate-skill-links --client "WorkBuddy"  # 迁移单个客户端
        """.strip()
    )

    parser.add_argument(
        "--report", action="store_true",
        help="生成 Markdown 报告文件（scan-report.md）"
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="自动修复（备份原目录 + 创建 symlink）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：显示将要执行的操作，但不实际修改"
    )
    parser.add_argument(
        "--unified-dir", type=str, default=None,
        help="指定统一的 skills 仓库路径（覆盖配置文件）"
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="启用自动发现新工具（覆盖配置文件）"
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="指定配置文件路径"
    )
    # === 新增参数 ===
    parser.add_argument(
        "--sync", action="store_true",
        help="同步：扫描前执行 git pull 同步"
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help="分析：扫描完成后进行 Skills 分布分析并给出整理建议"
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="清理：交互式提交未提交文件 + 清理临时文件，确保工作区干净"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="完整只读模式：Skills + MCP + Hooks + 端点探测 + 报告"
    )
    parser.add_argument(
        "--hermes", action="store_true",
        help="[已废弃] 旧 Hermes 通道检查，已并入 --mcp 统一检查的 legacy_channels 输出",
    )
    parser.add_argument(
        "--ai-memory", action="store_true",
        help="[已废弃] 旧 ai-memory 通道检查，已并入 --mcp 统一检查与 hooks 检查",
    )
    parser.add_argument(
        "--fix-ai-memory", action="store_true",
        help="[已废弃] 请改用 --fix-mcp 统一修复（本 flag 仅作为别名转发）",
    )
    parser.add_argument(
        "--no-interactive", action="store_true",
        help="非交互模式：跳过所有用户确认，自动处理所有变更"
    )
    parser.add_argument(
        "--push", action="store_true",
        help="推送：清理完成后自动 git push 到远程仓库"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="版本检查：检查每个 skill 是否有远程更新，列出当前版本和最新版本"
    )
    parser.add_argument(
        "--scan-only", action="store_true",
        help="仅执行基础扫描 + 路径验证 + 变更追踪（不执行其他操作）"
    )
    parser.add_argument("--skills", action="store_true", help="检查 IDE/Agent Skills 统一状态")
    parser.add_argument("--mcp", action="store_true", help="检查单一 Hermes MCP 配置")
    parser.add_argument("--hooks", action="store_true", help="检查生命周期 hooks")
    parser.add_argument("--probe-mcp", action="store_true", help="执行 MCP initialize 和 tools/list")
    parser.add_argument("--fix-skills", action="store_true", help="修复 Skills 路径（兼容 --fix）")
    parser.add_argument("--fix-mcp", action="store_true", help="写入统一 Hermes MCP 配置（带备份）")
    parser.add_argument(
        "--setup-all", action="store_true",
        help="一键设置并检查所有已安装 IDE/Agent 的 Skills 和统一 MCP",
    )
    parser.add_argument(
        "--remove-legacy-mcp",
        action="store_true",
        help="直接备份并移除旧 Hermes/ai-memory MCP 条目（纯删除，配合 --client 定向清理单个客户端）",
    )
    parser.add_argument(
        "--profile", type=str, default=None,
        help="指定 endpoint profile（覆盖 config.yaml 的 active_profile）",
    )
    parser.add_argument(
        "--list-profiles", action="store_true",
        help="列出 config.yaml 中可用的 endpoint profiles 后退出",
    )
    parser.add_argument(
        "--all-profiles", action="store_true",
        help="遍历全部 profile，输出跨 profile 汇总报告（与 --profile 互斥）",
    )
    parser.add_argument(
        "--format", type=str, default=None,
        choices=["table", "csv", "json", "md"],
        help="机读报告格式：table（默认，人类报告）/ csv / json / md；"
             "配合 --all-profiles 输出跨 profile 汇总，单独使用输出单 profile 快照",
    )
    # === 阶段四：按需加载与启停（L5） ===
    parser.add_argument(
        "--enable-skill", type=str, default=None, metavar="SKILL",
        help="启用指定技能（缺省作用于全部 per_skill 形态客户端；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--disable-skill", type=str, default=None, metavar="SKILL",
        help="禁用指定技能（缺省作用于全部 per_skill 形态客户端；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--client", type=str, default=None, metavar="CLIENT",
        help="限定启停/迁移/列表/修复/清理作用于指定客户端（配合 --enable-skill/--disable-skill/--migrate-skill-links/--list-skill-states/--fix-skills/--fix-mcp/--remove-legacy-mcp）",
    )
    parser.add_argument(
        "--audit-skill-states", action="store_true",
        help="只读审计跨客户端启停一致性（漂移 + 禁用生效 + 回滚幂等）",
    )
    parser.add_argument(
        "--list-skill-states", action="store_true",
        help="只读列出各客户端技能启停状态矩阵",
    )
    parser.add_argument(
        "--strict-skill-state", action="store_true",
        help="把启停一致性纳入 result_ok（与 --audit-skill-states 或 --full 同用）",
    )
    parser.add_argument(
        "--migrate-skill-links", action="store_true",
        help="把 root 形态客户端迁移为逐技能 symlink（解锁单技能启停；写操作，支持 --dry-run/--client）",
    )
    # === 阶段五（通用管理台）：端点库 CRUD 与挂载调整、客户端发现/清单 ===
    parser.add_argument(
        "--list-endpoints", action="store_true",
        help="列出端点库（endpoint key / name / url / transport）后退出",
    )
    parser.add_argument(
        "--add-endpoint", type=str, default=None, metavar="KEY",
        help="新增/覆盖端点库条目（配合 --endpoint-name/--endpoint-url/--endpoint-required-yaml）",
    )
    parser.add_argument(
        "--remove-endpoint", type=str, default=None, metavar="KEY",
        help="从端点库删除条目（写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--update-endpoint", type=str, default=None, metavar="KEY",
        help="更新端点 url/name（配合 --set-url/--set-name）",
    )
    parser.add_argument(
        "--endpoint-name", type=str, default=None,
        help="配合 --add-endpoint：端点的 MCP server name（正典名）",
    )
    parser.add_argument(
        "--endpoint-url", type=str, default=None,
        help="配合 --add-endpoint：端点的 URL（streamable-http 必填；stdio 可留空）",
    )
    parser.add_argument(
        "--endpoint-transport", type=str, default=None, choices=["streamable-http", "stdio"],
        help="配合 --add-endpoint：传输类型（默认 streamable-http）",
    )
    parser.add_argument(
        "--endpoint-command", type=str, default=None,
        help="配合 --add-endpoint / --test-endpoint：stdio 本地命令（如 npx -y @modelcontextprotocol/server-filesystem）",
    )
    parser.add_argument(
        "--set-command", type=str, default=None,
        help="配合 --update-endpoint：替换 stdio 本地命令",
    )
    parser.add_argument(
        "--endpoint-required-yaml", type=str, default=None,
        help="配合 --add-endpoint：JSON 字符串形式的能力组映射 {group: [tool...]}",
    )
    parser.add_argument(
        "--set-url", type=str, default=None,
        help="配合 --update-endpoint：替换 url",
    )
    parser.add_argument(
        "--set-name", type=str, default=None,
        help="配合 --update-endpoint：替换 server name",
    )
    parser.add_argument(
        "--endpoint-auth-token", type=str, default=None,
        help="配合 --add-endpoint / --update-endpoint / --test-endpoint：认证 Token（Bearer）",
    )
    parser.add_argument(
        "--test-endpoint", type=str, default=None, metavar="KEY",
        help="探测指定端点：MCP initialize + tools/list（支持 --endpoint-auth-token）",
    )
    parser.add_argument(
        "--attach-endpoints", type=str, default=None, metavar="KEY[,KEY...]",
        help="设置客户端 mcp_attach（配合 --client；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--remove-mcp-entry", type=str, default=None, metavar="KEY[,KEY...]",
        help="移除指定 MCP 条目（配合 --client；高风险条目需 --force-high-risk；支持 --dry-run）",
    )
    parser.add_argument(
        "--remove-mcp-class", type=str, default=None,
        choices=["attached", "legacy", "unmanaged"],
        help="按分类批量清理 MCP 条目（配合 --client；默认跳过高风险，需 --include-high-risk）",
    )
    parser.add_argument(
        "--force-high-risk", action="store_true",
        help="配合 --remove-mcp-entry：允许删除疑似客户端自带的条目",
    )
    parser.add_argument(
        "--include-high-risk", action="store_true",
        help="配合 --remove-mcp-class：批量清理时纳入疑似客户端自带的条目",
    )
    parser.add_argument(
        "--list-config-backups", action="store_true",
        help="只读列出该客户端配置的历史备份（配合 --client）",
    )
    parser.add_argument(
        "--restore-config-backup", type=str, default=None, metavar="PATH",
        help="从备份还原该客户端配置（配合 --client；整文件覆盖；支持 --dry-run）",
    )
    parser.add_argument(
        "--list-mcp-inventory", action="store_true",
        help="只读列出各客户端当前配置的全部 MCP 条目及分类（attached/legacy/unmanaged）",
    )
    parser.add_argument(
        "--management", action="store_true",
        help="输出三栏管理台管理快照 JSON（IDE/Skills/MCP 三面板；配合 --format json）",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="只读输出应用版本信息 JSON（X.Y.Z + build 数字格式，供「关于」页）",
    )
    parser.add_argument(
        "--add-client", type=str, default=None, metavar="NAME",
        help="手动添加客户端到 discovered 持久化（配合 --client-skills-path/--client-type；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--client-skills-path", type=str, default=None,
        help="配合 --add-client：客户端的 skills 目录路径",
    )
    parser.add_argument(
        "--client-type", type=str, default=None,
        help="配合 --add-client：客户端类型（默认 AI Coding Assistant）",
    )
    parser.add_argument(
        "--client-config-path", type=str, default=None,
        help="配合 --add-client：客户端 MCP 配置文件路径（如 ~/.foo/mcp.json）",
    )
    parser.add_argument(
        "--client-mcp-format", type=str, default=None,
        help="配合 --add-client：MCP 配置格式（json/toml/jsonc，默认 json）",
    )
    parser.add_argument(
        "--client-mcp-key-path", type=str, default=None,
        help="配合 --add-client：MCP servers 键路径（如 mcpServers，默认 mcpServers）",
    )
    parser.add_argument(
        "--client-mcp-attach", type=str, default=None,
        help="配合 --add-client：逗号分隔的挂载端点 key（如 hermes-home,generic-http）",
    )
    parser.add_argument(
        "--client-app-bundle", type=str, default=None,
        help="配合 --add-client：安装检测用的 App Bundle 路径（如 /Applications/Foo.app）",
    )
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
    parser.add_argument(
        "--market-install", type=str, default=None, metavar="PKG",
        help="从技能市场安装（写操作，需 --yes）：包名形如 owner/repo@skill",
    )
    parser.add_argument(
        "--market-upgrade", type=str, default=None, metavar="NAME",
        help="升级已装技能（写操作，需 --yes）：可按逗号分隔多个技能名",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="配合 --market-install/--market-upgrade：确认执行写操作",
    )
    # === 技能使用统计（FEAT-10，只读、零侵入）===
    parser.add_argument(
        "--skill-usage", action="store_true",
        help="统计各技能的真实使用情况（读 Codex 会话日志）：加载/浏览/编辑 + 最近使用时间",
    )
    parser.add_argument(
        "--usage-since", type=str, default=None, metavar="ISO_DATE",
        help="配合 --skill-usage：只统计该日期之后的动作（如 2026-08-24）",
    )
    parser.add_argument(
        "--progress-file", type=str, default=None, metavar="PATH",
        help="配合 --skill-usage/--merge-advice：把扫描进度原子写入该文件（GUI 轮询用，只写进度不写结论）",
    )
    # === 技能整理建议（FEAT-11，只读，不删不改不移）===
    parser.add_argument(
        "--merge-advice", action="store_true",
        help="产出技能整理建议（只读）：可执行合并组 / 上游仅标注 / 已否决变体，不删改任何文件",
    )
    parser.add_argument(
        "--client-command", type=str, default=None,
        help="配合 --add-client：安装检测用的 CLI 命令（如 foo）",
    )
    parser.add_argument(
        "--client-config-paths", type=str, default=None,
        help="配合 --add-client：安装检测用的配置文件路径，逗号分隔（如 ~/.foo/mcp.json,~/.foo/settings.json）",
    )
    parser.add_argument(
        "--update-client", type=str, default=None, metavar="NAME",
        help="更新已注册客户端的安装证据/目录设置（配合 --app-bundles/--commands/--config-paths/--skills-path/--mcp-config-path/--scan-dir；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--app-bundles", type=str, default=None,
        help="配合 --update-client：安装检测用 App Bundle 路径，逗号分隔",
    )
    parser.add_argument(
        "--commands", type=str, default=None,
        help="配合 --update-client：安装检测用 CLI 命令，逗号分隔",
    )
    parser.add_argument(
        "--config-paths", type=str, default=None,
        help="配合 --update-client：安装检测用配置文件路径，逗号分隔",
    )
    parser.add_argument(
        "--skills-path", type=str, default=None,
        help="配合 --update-client：客户端 skills 目录路径",
    )
    parser.add_argument(
        "--mcp-config-path", type=str, default=None,
        help="配合 --update-client：客户端 MCP 配置文件路径",
    )
    parser.add_argument(
        "--scan-dir", type=str, default=None,
        help="配合 --update-client：客户端默认扫描目录",
    )
    parser.add_argument(
        "--add-defaults", action="store_true",
        help="一键「默认添加」所有主流 IDE/Agent 到 discovered 持久化（写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--remove-client", type=str, default=None, metavar="NAME",
        help="移除客户端：本机停用 + discovered 条目 + 残留配置 + skills 链接（不删 trunk 共享注册表；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--cleanup-config", action="store_true",
        help="清理 config_only（仅有配置、无 app/cli）客户端的残留配置文件（配合 --client 定向清理单个客户端；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--set-unified-dir", type=str, default=None, metavar="PATH",
        help="写入 config.yaml 的 unified_skills_dir（写操作，支持 --dry-run）",
    )
    # === 阶段五（通用管理台）：skill 级文件操作（备份 / 导出 / 重命名 / 软删除） ===
    parser.add_argument(
        "--backup-skill", type=str, default=None, metavar="SKILL",
        help="备份指定 skill 目录到统一目录 _backup/（写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--export-skill", type=str, default=None, metavar="SKILL",
        help="导出指定 skill 目录为 zip（写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--rename-skill", type=str, default=None, metavar="SKILL",
        help="编辑指定 skill 的 SKILL.md 显示名/描述（配合 --new-name/--new-description；写操作，支持 --dry-run）",
    )
    parser.add_argument(
        "--new-name", type=str, default=None, metavar="NAME",
        help="配合 --rename-skill：新显示名",
    )
    parser.add_argument(
        "--new-description", type=str, default=None, metavar="DESC",
        help="配合 --rename-skill：新描述",
    )
    parser.add_argument(
        "--delete-skill", type=str, default=None, metavar="SKILL",
        help="软删除指定 skill：先备份再移入统一目录 _trash/（写操作，支持 --dry-run）",
    )

    return parser


def main() -> int:
    args = resolve_modes(build_parser().parse_args())

    # 阶段二 §7.2/ADR-10：工具自身运行错误（各 Phase 内部异常）→ 退出码 2，
    # 与判定性 0/1 分层；这里收集，收尾统一映射，避免"恒为 0 残留"。
    internal_errors: List[str] = []
    # 修复类写操作（--fix-skills / --fix-mcp）失败同样映射退出码 2：修复项自身
    # error 不算"审计结论（0/1）"，而属"工具执行失败"，须让调用方（GUI 按退出
    # 码判成功与否）能识别——否则失败也恒为 0，前端会误报"修复成功"。
    repair_errors: List[str] = []

    # D-2: 旧参数仅作别名/废弃。--hermes/--ai-memory 不再运行旧多通道检查器（其
    # 语义已并入 --mcp 统一检查的 legacy_channels 与 hooks 字段）；--fix-ai-memory
    # 转发到 --fix-mcp。显式废弃告警，避免"失效门面"静默误导调用方。
    if args.hermes or args.ai_memory:
        print("  ⚠️ --hermes/--ai-memory 已废弃，改用 --mcp（统一检查已含旧通道与 hooks）。")
    args.fix = args.fix or args.fix_skills
    args.fix_mcp = args.fix_mcp or args.fix_ai_memory
    args.hermes = False
    args.ai_memory = False
    # --scan-only: 仅保留 always-on 阶段（Phase 1, 3, 4, 状态保存）
    if args.scan_only:
        args.sync = False
        args.analyze = False
        args.fix = False
        args.clean = False
        args.push = False
        args.report = False
        args.hermes = False
        args.ai_memory = False
        args.update = False
        args.skills = True
        args.mcp = False
        args.hooks = False
        args.probe_mcp = False

    # --push 需要配合 --clean 使用
    if args.push and not args.clean:
        print("  ⚠️ --push 需要配合 --clean 使用，单独使用 --push 无效果")

    # 加载配置
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"  ❌ 配置加载失败: {e}")
        return 2
    unified_dir = args.unified_dir or config.get("unified_skills_dir", "~/.skills")
    config_path = args.config or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.yaml"
    )

    # 阶段一 endpoint profile 抽象：解析 --profile / active_profile，选择目标端点。
    if args.list_profiles:
        print("\n  可用 endpoint profiles:")
        for name in list_profiles(config):
            print(f"    - {name}")
        print("")
        return 0

    # 阶段五（通用管理台）：端点库 CRUD / 挂载 / MCP 清单（早返回，先于阶段一二三四）。
    if getattr(args, "list_endpoints", False):
        return _run_list_endpoints(args, config, config_path)
    if getattr(args, "add_endpoint", None):
        return _run_add_endpoint(args, config, config_path)
    if getattr(args, "remove_endpoint", None):
        return _run_remove_endpoint(args, config, config_path)
    if getattr(args, "update_endpoint", None):
        return _run_update_endpoint(args, config, config_path)
    if getattr(args, "test_endpoint", None):
        return _run_test_endpoint(args, config, config_path)
    if getattr(args, "attach_endpoints", None):
        return _run_attach_endpoints(args, config, config_path)
    if getattr(args, "list_mcp_inventory", False):
        return _run_list_mcp_inventory(args, config, config_path)
    # 阶段五增量：MCP 条目删除 / 清理 / 配置备份还原。与上面几条管理台命令同属
    # 「早返回」组，必须排在阶段三的通用 `--format json` 快照路由
    # （_run_single_profile_snapshot）之前：这四个命令也支持 --format json，
    # 且需要只输出自身结果的干净 stdout（GUI 直接 JSON.parse 整个 stdout），
    # 否则通用快照路由会先截走 --format json 的调用。
    if getattr(args, "remove_mcp_entry", None):
        return _run_remove_mcp_entry(args, config, config_path)
    if getattr(args, "remove_mcp_class", None):
        return _run_remove_mcp_class(args, config, config_path)
    if getattr(args, "list_config_backups", False):
        return _run_list_config_backups(args, config, config_path)
    if getattr(args, "restore_config_backup", None):
        return _run_restore_config_backup(args, config, config_path)
    if getattr(args, "management", False):
        return _run_management(args, config, config_path)
    if getattr(args, "version", False):
        return _run_version(args, config, config_path)
    if getattr(args, "add_client", None):
        return _run_add_client(args, config, config_path)
    if getattr(args, "update_client", None):
        return _run_update_client(args, config, config_path)
    if getattr(args, "add_defaults", False):
        return _run_add_defaults(args, config, config_path)
    if getattr(args, "remove_client", None):
        return _run_remove_client(args, config, config_path)
    if getattr(args, "cleanup_config", False):
        return _run_cleanup_config(args, config, config_path)
    if getattr(args, "set_unified_dir", None):
        return _run_set_unified_dir(args, config, config_path)
    if getattr(args, "backup_skill", None):
        return _run_skill_backup(args, config, config_path)
    if getattr(args, "export_skill", None):
        return _run_skill_export(args, config, config_path)
    if getattr(args, "rename_skill", None):
        return _run_skill_rename(args, config, config_path)
    if getattr(args, "delete_skill", None):
        return _run_skill_delete(args, config, config_path)

    # 技能市场（FEAT-9）同属这一组：它带 --format json，且 GUI 直接
    # JSON.parse 整个 stdout，若排在通用快照路由之后会被截走。
    # 只读；安装/升级不在 CLI 出口内。
    if getattr(args, "market", None):
        return _run_market(args)
    if getattr(args, "market_install", None) or getattr(args, "market_upgrade", None):
        return _run_market_write(args)

    # 技能使用统计（FEAT-10）同上：只读，且带 --format json 供 GUI 直接
    # JSON.parse，必须排在通用快照路由之前。
    if getattr(args, "skill_usage", False):
        return _run_skill_usage(args)

    # 技能整理建议（FEAT-11）同上：只读且 GUI 会 JSON.parse 整段 stdout，
    # 必须排在通用快照路由之前，否则输出会被快照截走。
    if getattr(args, "merge_advice", False):
        return _run_merge_advice(args)

    # 阶段二：--all-profiles 一次遍历全部 profile，输出跨 profile 汇总报告。
    if getattr(args, "all_profiles", False):
        return _run_all_profiles(args, config, config_path)

    # 阶段三：单 profile 机读快照（--format json/csv/md 且非 --all-profiles）。
    # 「一键合并预览」需要结构化数据（扫描清单 + 变更报告 + 修复计划），
    # 在通用快照之前优先走固定 JSON 出口，供 GUI 渲染成表格 + 分页。
    if args.fix_skills and getattr(args, "format", None) == "json":
        return _run_fix_skills_preview(args, config, config_path)

    if getattr(args, "format", None) in ("json", "csv", "md"):
        return _run_single_profile_snapshot(args, config, config_path)

    # 阶段四：按需加载与启停（L5）入口，先于 11 阶段主流程早返回。
    if args.migrate_skill_links and (args.enable_skill or args.disable_skill):
        print("  ❌ --migrate-skill-links 与 --enable-skill/--disable-skill 互斥")
        return 2
    if args.migrate_skill_links:
        return _run_skill_migrate(args, config, config_path)
    if args.enable_skill and args.disable_skill:
        print("  ❌ --enable-skill 与 --disable-skill 互斥")
        return 2
    if args.enable_skill or args.disable_skill:
        return _run_skill_toggle(args, config, config_path)
    if args.audit_skill_states:
        return _run_skill_audit(args, config, config_path)
    if args.list_skill_states:
        return _run_list_skill_states(args, config, config_path)

    try:
        profile_bundle = load_profile(config, getattr(args, "profile", None), config_path=config_path)
    except Exception as e:
        print(f"  ❌ profile 加载失败: {e}")
        return 2
    profile = profile_bundle["profile"]

    # ================================================================
    # 阶段 1: 验证主 skills 目录路径
    # ================================================================
    try:
        print("")
        print("=" * 60)
        print("  Phase 1: 目录路径验证")
        print("=" * 60)

        dir_check = validate_unified_dir(config)

        if not dir_check["valid"]:
            print(f"\n  {dir_check['message']}\n")
            if dir_check["needs_fix"] and args.fix_skills and not args.dry_run:
                print("  🔧 正在自动修复到 ~/.skills-manager/skills ...")
                fix_result = fix_unified_dir(config_path)
                print(f"  {fix_result['message']}")
                # 重新加载配置
                config = load_config(args.config)
                unified_dir = args.unified_dir or config.get("unified_skills_dir", "~/.skills")
        else:
            print(f"\n  {dir_check['message']}\n")

        expanded_unified = os.path.expanduser(unified_dir)
    except Exception as e:
        print(f"\n  ❌ Phase 1 异常: {e}")
        internal_errors.append(f"Phase 1: {e}")

    # ================================================================
    # 阶段 2: Git 同步（--sync 或 --full 时执行）
    # ================================================================
    git_sync_result = None
    try:
        if args.sync:
            print("")
            print("=" * 60)
            print("  Phase 2: Git 同步")
            print("=" * 60)
            print("")

            if is_git_repo(expanded_unified):
                print(f"  📂 检测到 git 仓库: {expanded_unified}")
                git_sync_result = git_pull_if_needed(expanded_unified, auto=True)
                print(f"\n  {git_sync_result['message']}")
                if git_sync_result.get("changed_files"):
                    print(f"\n  变更文件:")
                    for line in git_sync_result["changed_files"][:10]:
                        print(f"    {line}")
            else:
                print(f"  ⏭️ 非 git 仓库，跳过同步")
        # 无 --sync 时不访问远端，也不修改 .git 元数据。
    except Exception as e:
        print(f"\n  ❌ Phase 2 异常: {e}")
        internal_errors.append(f"Phase 2: {e}")

    # ================================================================
    # 阶段 3: 扫描
    # ================================================================
    try:
        print("")
        print("=" * 60)
        print("  Phase 3: Skills 扫描")
        print("=" * 60)

        scan_result = run_scan(
            config_path=args.config,
            auto_discover=args.discover,
        )

        # 输出控制台报告
        print_console_report(scan_result)

        # SKILL.md frontmatter 契约审计：每次运行都做只读校验。
        fm_audit = audit_skill_frontmatter(
            scan_result.get("unified_dir", unified_dir)
        )
        print("")
        print(format_frontmatter_report(fm_audit))
    except Exception as e:
        print(f"\n  ❌ Phase 3 异常: {e}")
        internal_errors.append(f"Phase 3: {e}")

    # 阶段 7: Unified Skills/MCP/hooks 统一只读检查。Live probing 默认关，--full 开。
    combined_result = None
    if (args.mcp or args.hooks) and not args.setup_all:
        try:
            print("")
            print("=" * 60)
            print("  Phase 7: Unified Skills/MCP/Hooks 统一检查")
            print("=" * 60)
            combined_result = check_agents(config, scan_result, live_probe=args.probe_mcp, profile=profile)
            print(format_combined_report(combined_result))
        except Exception as e:
            print(f"\n  ❌ Phase 7 异常: {e}")
            internal_errors.append(f"Phase 7: {e}")

    if args.fix_mcp:
        print("")
        print("=" * 60)
        print("  Unified MCP repair")
        print("=" * 60)
        # 语义：把所有「纳管端点」都配置到每个支持 MCP 的已安装客户端。
        # 显式 --profile 才限定单端点；否则遍历整个端点库。
        explicit_profile = getattr(args, "profile", None)
        ops_log("fix_mcp_begin", action="fix_mcp", client=args.client, dry_run=bool(args.dry_run))
        try:
            mcp_fix_results = fix_mcp_clients(
                config,
                dry_run=args.dry_run,
                profile=profile if explicit_profile else None,
                client=args.client,
            )
            marks = {
                "updated": "✅",
                "created": "✅",
                "unchanged": "✅",
                "dry-run": "🔍",
                "not-installed": "⏭️",
                "missing": "⚠️",
                "unsupported": "⏭️",
                "error": "❌",
            }
            for result in mcp_fix_results:
                mark = marks.get(result["status"], "•")
                print(
                    f"  {mark} {result['name']}: {result['status']} - "
                    f"{result['message']} ({result['path']})"
                )
                if result.get("status") == "error":
                    repair_errors.append(
                        f"MCP 修复失败 {result['name']}: {result['message']} ({result['path']})"
                    )
        except Exception as e:
            print(f"\n  ❌ Unified MCP repair failed: {e}")
            repair_errors.append(f"MCP 修复异常: {e}")

    if args.remove_legacy_mcp:
        print("")
        print("=" * 60)
        print("  Legacy Hermes MCP cleanup")
        print("=" * 60)
        try:
            # 纯删除语义：直接移除旧通道（legacy）条目并备份原配置，不再以
            # "统一端点验证通过"作为前置门槛。删除后若客户端失去唯一连接，
            # 可用 --fix-mcp 重新接入统一端点恢复。
            cleanup_results = remove_legacy_mcp_clients(
                config, dry_run=args.dry_run, profile=profile, client=args.client
            )
            marks = {
                "updated": "✅",
                "unchanged": "✅",
                "dry-run": "🔍",
                "not-installed": "⏭️",
                "missing": "⚠️",
                "unsupported": "⏭️",
                "error": "❌",
            }
            for result in cleanup_results:
                mark = marks.get(result["status"], "•")
                print(
                    f"  {mark} {result['name']}: {result['status']} - "
                    f"{result['message']} ({result['path']})"
                )
        except Exception as e:
            print(f"\n  ❌ Legacy MCP cleanup failed: {e}")
            repair_errors.append(f"Legacy MCP cleanup: {e}")

    # ================================================================
    # 阶段 4: 变更追踪
    # ================================================================
    try:
        print("")
        changes = compute_changes(scan_result)
        print(format_change_report(changes))
    except Exception as e:
        print(f"\n  ❌ Phase 4 异常: {e}")
        internal_errors.append(f"Phase 4: {e}")

    # ================================================================
    # 阶段 5: Skills 分布分析（--analyze 或 --full 时执行）
    # ================================================================
    if args.analyze:
        try:
            print("")
            print("  Phase 5: Skills 分布分析")
            print("")

            analysis = get_skills_summary(unified_dir)
            print(format_analysis_report(analysis))

            # 如果有重复项建议，输出到控制台
            if analysis.get("duplicates"):
                print("")
                print("  💡 建议执行整理命令:")
                print("     检查重复技能并手动合并")
                print("")

            # SKILL.md frontmatter 契约审计详情（与 main 报告同源，这里单独成段）。
            print("")
            print(format_frontmatter_report(audit_skill_frontmatter(unified_dir)))
        except Exception as e:
            print(f"\n  ❌ Phase 5 异常: {e}")
            internal_errors.append(f"Phase 5: {e}")

    # ================================================================
    # 阶段 6: 修复（--fix 或 --full 时执行）
    # ================================================================
    if args.fix:
        # FEAT-7 口径：non_agent 客户端（CC Switch 等）不进技能面板，也不代修链接。
        # 与「修复链接」弹窗的预览同源过滤，否则预览显示 6 项、实写按 7 项执行。
        scan_result = _drop_non_agent_rows(scan_result, config_path)
        ops_log("fix_skills_begin", action="fix_skills", client=args.client, dry_run=bool(args.dry_run))
        try:
            print("")
            print("  Phase 6: 自动修复")
            print("")

            fix_result = fix_all(scan_result, dry_run=args.dry_run, client=args.client)
            print_fix_report(fix_result)
            if not args.dry_run and fix_result.get("errors", 0) > 0:
                failed = [
                    d.get("path", "?") for d in fix_result.get("details", [])
                    if d.get("error") and not d.get("error", "").startswith("跳过")
                ]
                repair_errors.append(
                    f"Skills 修复失败 {fix_result.get('errors', 0)} 项: {', '.join(failed) if failed else '见上'}"
                )

            # 修复后重新扫描并保存状态（仅在非 dry-run 时）
            if not args.dry_run:
                print("\n  🔄 重新扫描验证...\n")
                scan_result = run_scan(
                    config_path=args.config,
                    auto_discover=args.discover,
                )
                print_console_report(scan_result)
        except Exception as e:
            print(f"\n  ❌ Phase 6 异常（修复阶段）: {e}")
            internal_errors.append(f"Phase 6: {e}")

    # --setup-all verifies the state after both repair classes have completed.
    if args.setup_all:
        try:
            print("\n  🔄 统一设置后复检 Skills、MCP、Hooks 和端点能力...\n")
            if not args.dry_run:
                scan_result = run_scan(
                    config_path=args.config,
                    auto_discover=args.discover,
                )
            combined_result = check_agents(
                config, scan_result, live_probe=args.probe_mcp, profile=profile
            )
            print(format_combined_report(combined_result))
        except Exception as e:
            print(f"\n  ❌ Unified post-setup validation failed: {e}")
            internal_errors.append(f"Unified post-setup validation: {e}")

    # ================================================================
    # 阶段 8: Skill 版本检查（--update 或 --full 时执行）
    # ================================================================
    if args.update:
        try:
            print("")
            print("  Phase 8: Skill 全网版本检查")
            print("")

            version_result = check_all_versions(unified_dir)
            print(format_version_report(version_result))

            # 如果有可更新且非 dry-run，询问用户是否更新
            git_upd = version_result.get("git_updatable", 0)
            total_upd = version_result.get("updatable", 0)
            manual_upd = total_upd - git_upd

            if (total_upd > 0
                    and not args.dry_run
                    and not args.no_interactive):
                prompt_parts = []
                if git_upd > 0:
                    prompt_parts.append(f"{git_upd} 个可自动更新（git pull）")
                if manual_upd > 0:
                    prompt_parts.append(f"{manual_upd} 个需手动更新")
                prompt = f"  🔄 {'，'.join(prompt_parts)}。是否执行自动更新？(y/N): "
                answer = input(prompt).strip().lower()
                if answer in ("y", "yes") and git_upd > 0:
                    update_result = git_pull_if_needed(expanded_unified, auto=True)
                    print(f"\n  {update_result['message']}")
            elif (git_upd > 0
                    and not args.dry_run
                    and args.no_interactive):
                # 非交互模式下仅自动更新 git 来源的 skill
                update_result = git_pull_if_needed(expanded_unified, auto=True)
                print(f"\n  {update_result['message']}")
        except Exception as e:
            print(f"\n  ❌ Phase 8 异常: {e}")
            internal_errors.append(f"Phase 8: {e}")

    # ================================================================
    # 阶段 9: 保存当前状态（用于下次变更对比）
    # ================================================================
    if (args.fix_skills and not args.dry_run) or args.clean:
        try:
            state_path = save_current_state(scan_result)
            print(f"\n  📝 状态已保存: {state_path}")
        except Exception as e:
            print(f"\n  ❌ Phase 9 异常: {e}")
            internal_errors.append(f"Phase 9: {e}")

    # ================================================================
    # 阶段 10: 生成 Markdown 报告（--report 或 --full 时执行）
    # ================================================================
    try:
        if args.report:
            report_path = write_markdown_report(
                scan_result,
                combined_result=combined_result,
                frontmatter_audit=audit_skill_frontmatter(
                    scan_result.get("unified_dir", unified_dir)
                ),
            )
            print(f"\n  📄 报告已生成: {report_path}")
    except Exception as e:
        print(f"\n  ❌ 报告生成异常: {e}")
        internal_errors.append(f"报告生成: {e}")

    # ================================================================
    # 阶段 11: 工作区清理（--clean 或 --full 时执行）
    # ⚠️ 必须在所有其他阶段之后执行，确保清理能提交所有变更（包括 state.yaml）
    # ================================================================
    if args.clean:
        try:
            print("")
            print("  Phase 11: 工作区清理")
            print("")

            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            # 增强版：一站式清理（提交 + 交互 + 临清）
            clean_result = ensure_workspace_clean(
                workspace_dir,
                interactive=not args.no_interactive,
                commit_msg="chore: workspace cleanup",
                push=args.push,
            )
            print(format_clean_result(clean_result))

            # 如果是一般模式（非交互），也给出提示
            if args.no_interactive and not clean_result.get("final_clean"):
                print(f"\n  ⚠️ 非交互模式，部分不确定文件已跳过。")
                print(f"  使用默认模式 (--clean) 可交互确认。")
        except Exception as e:
            print(f"\n  ❌ Phase 11 异常: {e}")
            internal_errors.append(f"Phase 11: {e}")

    print("")
    print("=" * 60)
    print("  ✅ 完成")
    print("=" * 60)
    print("")

    # 阶段二 §7.2 / ADR-10：工具自身运行错误优先于合规判定 → 退出码 2。
    # 修复类写操作失败（repair_errors）同样映射退出码 2，避免"失败恒为 0"。
    total_oops = len(internal_errors) + len(repair_errors)
    if total_oops:
        print(f"\n  ❌ 工具运行存在 {total_oops} 处内部异常/修复失败，退出码 2:")
        for err in internal_errors:
            print(f"    - {err}")
        for err in repair_errors:
            print(f"    - {err}")
        return 2

    # 阶段二退出码：0=全绿，1=存在不合规项（仅当本次运行执行了 unified 检查）。
    # 阶段四：--strict-skill-state 时，启停一致性也纳入判定（设计 §4.4）。
    if combined_result is not None and not result_ok(
        combined_result, strict_skill_state=args.strict_skill_state
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
