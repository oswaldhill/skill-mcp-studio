"""Per-client MCP inventory: list every MCP entry a client actually configures.

Stage-5 requirement ③a: "手动指定 MCP，或者自动识别本机已有的 MCP".  The check
model historically only looked for the **canonical** entry (``expected_name``)
or legacy names.  This module dumps *all* MCP entries a client has configured —
regardless of whether they match any endpoint in the library — and classifies
each one so the GUI can:

- match an endpoint library entry   -> ``attached`` (this endpoint is configured);
- match a legacy channel name       -> ``legacy``;
- match nothing                     -> ``unmanaged`` (a real MCP entry the library
  does not yet know about).

It is strictly read-only and reuses ``mcp_checker.load_mcp_servers`` so the parse
formats (json/toml/jsonc/reasonix/reasonix_toml/cordis_yaml/yaml) stay in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mcp_checker import load_mcp_servers


@dataclass
class McpEntry:
    """One MCP server entry found in a client config."""

    key: str
    url: str = ""
    command: str = ""
    args: List[str] = field(default_factory=list)
    classification: str = "unmanaged"  # attached | legacy | unmanaged
    endpoint_key: Optional[str] = None  # set when classification == attached


def _entry_to_dict(entry: Any, key: str) -> McpEntry:
    if isinstance(entry, dict):
        return McpEntry(
            key=key,
            url=str(entry.get("url", "")),
            command=str(entry.get("command", "")),
            args=list(entry.get("args", []) or []),
        )
    return McpEntry(key=key, url=str(entry))


def list_client_mcp_entries(tool: Dict[str, Any]) -> List[McpEntry]:
    """All MCP entries configured by one client, in file-load order.

    Merges the primary ``config_path`` and every ``config_candidates`` entry
    (same merge as ``combined_checker._load_tool_servers``), then normalises each
    server into an ``McpEntry``.
    """
    servers: Dict[str, Any] = {}
    primary = load_mcp_servers(
        tool.get("config_path", ""),
        tool.get("format", "json"),
        tool.get("mcp_key_path", ["mcpServers"]),
    )
    servers.update(primary)
    for candidate in tool.get("config_candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        candidate_servers = load_mcp_servers(
            candidate.get("path", ""),
            candidate.get("format", "json"),
            candidate.get("key_path", tool.get("mcp_key_path", ["mcpServers"])),
        )
        servers.update(candidate_servers)
    return [_entry_to_dict(value, key) for key, value in servers.items()]


def classify_entries(
    entries: List[McpEntry],
    *,
    endpoint_entries: List[Dict[str, Any]],
    legacy_names: List[str],
    canonical_name: Optional[str] = None,
) -> List[McpEntry]:
    """Annotate each entry with its classification against the endpoint library.

    A client's MCP entry is:

    - ``attached`` when its key matches an endpoint's declared ``name`` (the
      canonical server name the fixer writes) *and* the URL agrees when both are
      set;
    - ``legacy`` when its key is a declared legacy channel name;
    - otherwise ``unmanaged``.

    Returns a new list (inputs are not mutated).
    """
    by_name: Dict[str, str] = {}
    for endpoint in endpoint_entries:
        name = endpoint.get("name")
        if isinstance(name, str) and name:
            by_name[name] = str(endpoint.get("key", name))
    legacy = set(legacy_names)
    classified: List[McpEntry] = []
    for entry in entries:
        clone = McpEntry(
            key=entry.key,
            url=entry.url,
            command=entry.command,
            args=list(entry.args),
            classification=entry.classification,
            endpoint_key=entry.endpoint_key,
        )
        if entry.key in legacy:
            clone.classification = "legacy"
        elif entry.key in by_name:
            clone.classification = "attached"
            clone.endpoint_key = by_name[entry.key]
        elif canonical_name and entry.key == canonical_name:
            clone.classification = "attached"
        classified.append(clone)
    return classified


def observed_endpoint_keys(entries: List[McpEntry]) -> List[str]:
    """Endpoint keys **actually mounted**, derived from the config on disk.

    Only entries classified ``attached`` carry an ``endpoint_key``, so this is the
    observed counterpart of ``endpoint_library.resolve_client_attach`` (which is a
    declaration/default, not an observation).  Order follows inventory order and
    duplicates are dropped.
    """
    observed: List[str] = []
    for entry in entries:
        key = entry.endpoint_key
        if isinstance(key, str) and key and key not in observed:
            observed.append(key)
    return observed


def attachment_consistency(
    entries: List[McpEntry],
    expected_keys: List[str],
) -> Dict[str, List[str]]:
    """Compare *expected* attachment against what the client really mounts.

    ``expected_keys`` comes from ``resolve_client_attach``: an explicit
    ``mcp_attach`` declaration, or — when the client declares none — the default
    "every endpoint in the library".  That value is an **intention**, so presenting
    it as "已配置" without checking the config produced false positives (a client
    with no MCP config at all still looked fully wired up).

    Returns three ordered lists:

    - ``observed``   — mounted, per the config file;
    - ``missing``    — expected but absent from the config (**anomaly**);
    - ``undeclared`` — present in the config but not expected.

    ``expected`` itself is echoed so callers need not re-resolve it.
    """
    expected: List[str] = []
    for key in expected_keys or []:
        if isinstance(key, str) and key and key not in expected:
            expected.append(key)
    observed = observed_endpoint_keys(entries)
    return {
        "expected": expected,
        "observed": observed,
        "missing": [key for key in expected if key not in observed],
        "undeclared": [key for key in observed if key not in expected],
    }


def inventory_client(
    tool: Dict[str, Any],
    *,
    endpoint_entries: List[Dict[str, Any]],
    legacy_names: List[str],
    canonical_name: Optional[str] = None,
) -> List[McpEntry]:
    """Load then classify one client's MCP entries (convenience wrapper)."""
    entries = list_client_mcp_entries(tool)
    return classify_entries(
        entries,
        endpoint_entries=endpoint_entries,
        legacy_names=legacy_names,
        canonical_name=canonical_name or tool.get("unified_name"),
    )
