---
name: skill-mcp-studio
description: >
  Audit and safely align installed IDEs and agents against a shared Skills
  repository and a declared MCP endpoint profile. Verify installation evidence,
  Skills links, MCP configuration, and live endpoint capabilities as four
  separate states, and repair or roll them back safely. Use when checking or
  fixing IDE/Agent Skills links, MCP configuration, endpoint liveness,
  capability coverage, legacy MCP channel migration, or connection scale.
---

# Skill MCP Studio

Use one registry and one report to answer four different questions without conflating them:

1. Is the IDE or Agent actually installed?
2. Does its Skills path point to the shared repository?
3. Is it configured for the active MCP endpoint profile?
4. Does that endpoint initialize and expose the required capabilities?

MCP configuration does not prove connectivity. MCP connectivity does not prove lifecycle hooks. Report each state separately.

## Endpoint Profiles

The expected external endpoint is declared, never hardcoded. `config.yaml` holds one or more endpoint profiles plus an `active_profile`:

```yaml
schema_version: 1
active_profile: generic-http
profile_sources: []
profiles:
  generic-http:
    name: my-mcp
    url: https://example.internal/mcp
    transport: streamable-http
    url_policy: strict
    required_capabilities: {}
```

A profile may also declare `auth_token_env` (an environment variable name for the probe Bearer token), `probe_timeout`, `legacy_names` (legacy entries to detect/remove), and `legacy_detection` (heuristic rules for the legacy-channel check). Field semantics live in the product spec; here a profile is the single source of truth for the endpoint.

- `--list-profiles` prints the available profiles and exits.
- `--profile <name>` overrides `active_profile` for one run.
- `required_capabilities: {}` means the endpoint only must complete `initialize` and `tools/list`. Otherwise each group maps a display name to the tool names that must appear in `tools/list`.

A client is fully compliant only when `initialize` and `tools/list` succeed and the returned tool names cover every required capability group.

Do not treat legacy entries as the desired state. Detect and report them for migration, and remove them only after the unified endpoint passes all capability checks.

## Safe Workflow

### Read-only audit

```bash
python3 scan.py --skills --mcp --hooks
python3 scan.py --skills --mcp --hooks --probe-mcp --report
```

No-argument execution is read-only. `--full` means all read-only checks plus report generation; it must not imply Git pull, cleanup, commit, push, or configuration repair.

### Configure every installed IDE/Agent

```bash
python3 scan.py --setup-all --dry-run
python3 scan.py --setup-all --report
```

`--setup-all` is the standard write entry point. It detects installed registry clients, creates or repairs their Skills link, creates or updates the single canonical MCP entry from the active profile, then rescans and runs `initialize` plus `tools/list`. Missing clients and unsupported configuration formats are reported and skipped. Installed Skills clients without a verified MCP registry entry are listed as `UNMANAGED`; they are never silently counted as covered. Existing unrelated and legacy MCP entries are preserved.

Before any write:

1. Inspect `git status` and preserve unrelated changes.
2. Back up the exact Skills, MCP, DNS, or proxy file being changed.
3. Apply one class of change at a time.
4. Re-parse the changed configuration and run a live probe.
5. Keep legacy MCP entries until the unified endpoint passes all capability groups.

Never run broad workspace cleanup or automatic commit/push as part of an audit. Git operations and repairs require separate explicit flags.

## IDE/Agent Registry

`config.yaml` is the source of truth for supported tools. Each entry may define canonical name and aliases, App/CLI/config installation evidence, Skills paths, MCP format, Hooks path, and repair support.

An App, CLI, or initialized configuration is installation evidence. A Skills symlink by itself is not.

Supported MCP formats include JSON `mcpServers`, Codex TOML `[mcp_servers.*]`, Reasonix string arrays, direct remote URLs, controlled stdio launchers, and DSH `cordis_yaml`. Reports must never print credential values.

Per-tool `unified_name` override: a tool may set `unified_name` in its `mcp_tools` entry to write the unified endpoint under a distinct server key instead of the profile name, protecting an existing local bridge from being clobbered on `--setup-all`.

## Status Model

Every installed client produces the same fields:

```text
installed
skills_compliant
mcp_configured
mcp_initialize_ok
mcp_tools_list_ok
capabilities          # one boolean per required capability group, derived from tools/list
hooks_configured
legacy_channels
```

All summary counts must be derived from these detail records. If summary and details disagree, the check is invalid.

## CLI

```text
--skills          Check unified Skills paths
--mcp             Parse and validate the active profile's MCP configuration
--hooks           Check lifecycle hook coverage separately
--probe-mcp       Run initialize and tools/list against the profile endpoint
--fix-skills      Back up and repair Skills links
--fix-mcp         Back up and write the unified MCP entry
--setup-all       Configure every installed, supported IDE/Agent, then rescan and
                  run the unified MCP capability checks
--remove-legacy-mcp  After a mandatory live full-capability probe, back up and
                     remove the legacy MCP entries declared by the profile
--profile NAME    Override active_profile for one run
--list-profiles   Print available profiles and exit
--report          Write the Markdown report
--full            Run all read-only checks and report generation
--list-skill-states [--client C]   Read-only per-client skill enable/disable matrix (L5)
--audit-skill-states               Read-only cross-client skill-state consistency audit
--enable-skill SKILL [--client C]  Enable a repo skill (write; supports --dry-run)
--disable-skill SKILL [--client C] Disable a repo skill (write; supports --dry-run)
--strict-skill-state               Fold skill-state consistency into result_ok
```

Stage 4 (L5) normalizes each installed-client × repo-skill pair to `enabled` / `disabled` / `not_in_repo`. Per-skill toggling only targets clients whose skills dir uses per-skill symlinks; whole-directory (root) symlink clients are audit-only. Toggle writes reuse the backup → atomic write → validate → rollback safety shape and are atomic (`os.symlink(temp)` + `os.replace`). The audit channel is strictly read-only. Toggle exit codes: `0` all green, `1` post-write validation failure (rolled back), `2` skill not in repo / unsupported client form / rollback failure.

Legacy flags (`--hermes`, `--ai-memory`) remain aliases during migration. They route to the single profile-driven legacy-channel check rather than an obsolete hardcoded channel standard.

## Repair and Rollback

- Skills: move the original path to a timestamped backup before creating a symlink.
- IDE/Agent MCP: make a sibling backup, write atomically, re-parse, then probe.
- `--fix-mcp --dry-run` reports each installed client without writing. Without `--dry-run`, JSON `mcpServers` and Codex TOML receive exactly one canonical entry per the active profile; existing legacy and unrelated entries remain untouched.
- `--remove-legacy-mcp` automatically enables the live MCP probe and refuses to write unless every installed client is fully compliant. It then creates a fresh sibling backup, removes only the entries declared in the profile's `legacy_names`, reparses the result, and rolls back any failed client.

Do not delete legacy MCP entries automatically. Remove them only after the new endpoint passes capability checks in that specific client.

## Dashboard (管理台，可写)

`gui/dashboard.html` renders an `--management` snapshot (see below) as a five-page management console: overview / IDE·Agent / Skills / MCP / Settings. Beyond the read-only client × state matrix (green / yellow / red / gray), it drives **write operations** through the Tauri `run_cli` bridge with the unified backup → atomic write → re-parse validate → rollback safety chain: fix Skills links, write unified MCP config, per-skill enable/disable, and endpoint CRUD. A Tauri shell in `src-tauri/` wraps the same dashboard as a desktop `.app`; the browser-only preview shows a read-only unconfigured sample state (the real write commands require the `window.__TAURI__` shell). Repair is therefore available both from the CLI and the management console; see `src-tauri/BUILD.md`.

## Validation

```bash
python3 -m pytest tests/ -q
python3 scan.py --list-profiles
python3 scan.py --skills --mcp --hooks --probe-mcp --report
```

Deployment-specific endpoint details (network reachability, DNS, and reverse-proxy routing) belong to the individual profile repository referenced through `profile_sources`, not to this skill document.
