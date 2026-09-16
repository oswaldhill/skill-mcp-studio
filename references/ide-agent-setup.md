# IDE and Agent Setup

The automatic entry point is:

```bash
cd ~/.skills-manager/skills/skills-mcp-unifier
python3 scan.py --setup-all --dry-run
python3 scan.py --setup-all --report
```

It configures only installed clients whose format is declared with
`fix_supported: true` in `config.yaml`. The canonical MCP service name and
URL come from the active endpoint profile in `config.yaml` (see
`--list-profiles` / `--profile`); there is no hardcoded client URL.

| Client | Skills path | MCP configuration | Format |
| --- | --- | --- | --- |
| Claude Code | `~/.claude/skills` | `~/.claude.json` | JSON `mcpServers` |
| Cursor | `~/.cursor/skills` | `~/.cursor/mcp.json` | JSON `mcpServers` |
| WorkBuddy | `~/.workbuddy/skills` | `~/.workbuddy/mcp.json` | JSON `mcpServers` |
| Codex | detected separately | `~/.codex/config.toml` | TOML `mcp_servers` |
| Reasonix | detected separately | `~/.reasonix/config.toml` | TOML `plugins` |

OpenCode, Hermes Agent, and TRAE currently participate in Skills checks. They
do not receive automatic MCP writes until their MCP configuration path and
format are explicitly added to the registry and covered by repair tests.
Auto-discovered installed clients such as configuration switchers or assistants
are reported as `UNMANAGED` under the same rule.

The command creates timestamped backups before replacing existing Skills paths
or MCP files. New configuration files are created with mode `0600`. A failed
MCP parse or validation restores the backup, or removes a newly created invalid
file. Legacy MCP entries are never removed by `--setup-all`.
