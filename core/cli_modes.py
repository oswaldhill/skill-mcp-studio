"""CLI mode normalization with read-only defaults."""


def resolve_modes(args):
    explicit = any((
        args.full, args.skills, args.mcp, args.hooks, args.probe_mcp,
        args.report, args.sync, args.clean, args.push, args.fix,
        args.fix_skills, args.fix_mcp, args.remove_legacy_mcp,
        args.setup_all,
        args.hermes, args.ai_memory, args.all_profiles,
        # Stage-4 (按需加载与启停): toggle / audit / list modes run as their own
        # early-return paths; they are explicit modes so the default skill/mcp/hook
        # checks do not also kick in.
        getattr(args, "enable_skill", None), getattr(args, "disable_skill", None),
        getattr(args, "audit_skill_states", False),
        getattr(args, "list_skill_states", False),
        getattr(args, "migrate_skill_links", False),
        # Stage-5 (通用管理台) endpoint library CRUD / inventory / attach modes.
        getattr(args, "list_endpoints", False),
        getattr(args, "add_endpoint", None),
        getattr(args, "remove_endpoint", None),
        getattr(args, "update_endpoint", None),
        getattr(args, "attach_endpoints", None),
        getattr(args, "list_mcp_inventory", False),
        getattr(args, "management", False),
        getattr(args, "add_client", None),
        getattr(args, "set_unified_dir", None),
    ))
    if not explicit:
        args.skills = True
        args.mcp = True
        args.hooks = True
    if args.full:
        args.skills = True
        args.mcp = True
        args.hooks = True
        args.probe_mcp = True
        args.report = True
    if args.hermes:
        args.mcp = True
    if args.ai_memory:
        args.mcp = True
        args.hooks = True
    if args.all_profiles:
        # 遍历全部 profile：等同于对每个 profile 做一次 unified 检查 + 活体探测。
        args.mcp = True
        args.hooks = True
        args.probe_mcp = True
    if args.fix:
        args.fix_skills = True
    if args.remove_legacy_mcp:
        args.mcp = True
        args.probe_mcp = True
    if args.setup_all:
        args.skills = True
        args.mcp = True
        args.hooks = True
        args.probe_mcp = True
        args.fix_skills = True
        args.fix_mcp = True
    return args
