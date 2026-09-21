"""Configuration and aggregate checks for a single unified Hermes MCP."""

import json
import os
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import yaml

from config_codec import (
    parse_cordis_yaml as _parse_cordis_yaml,
    parse_reasonix_json as _parse_reasonix_json,
    parse_reasonix_toml as _parse_reasonix_toml,
    parse_toml_mcp_servers as _parse_toml_mcp_servers,
)


def _load_cordis_yaml_text(text: str) -> Any:
    """Thin alias: cordis ``!!js``-tolerant parse lives in config_codec (A-6)."""
    return _parse_cordis_yaml(text)


def is_valid_mcp_url(url: str) -> bool:
    """Accept a portless production HTTPS MCP URL with a real hostname."""
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.hostname) and parsed.path.rstrip("/").endswith("/mcp")
    except (TypeError, ValueError):
        return False


def _nested(data: Any, keys: Iterable[str]) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _load_simple_toml_servers(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse ``[mcp_servers.<name>]`` table sections (delegates to config_codec)."""
    return _parse_toml_mcp_servers(text)


def _load_reasonix(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse ``{"mcp": ["name=command args"]}`` (delegates to config_codec)."""
    return _parse_reasonix_json(text)


def _load_cordis_yaml(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse a DSH cordis patch/config YAML array into a serverName→config map.

    DSH registers MCP servers as cordis loader-patch entries:
        - id: mcp-hermes
          name: '@deepseek-ai/dsh-mcp-client'
          config:
            serverName: hermes
            transport: streamable-http
            url: https://mcp.example.com/mcp
    The unifier keys servers by `serverName` so the canonical channel `hermes`
    is found the same way as JSON/TOML clients.
    """
    servers: Dict[str, Dict[str, Any]] = {}
    try:
        data = _load_cordis_yaml_text(text)
    except (yaml.YAMLError, OSError):
        return servers
    if not isinstance(data, list):
        return servers
    for entry in data:
        if not isinstance(entry, dict):
            continue
        config = entry.get("config") if isinstance(entry.get("config"), dict) else {}
        server_name = config.get("serverName") or entry.get("serverName")
        url = config.get("url", "") if isinstance(config, dict) else ""
        if isinstance(server_name, str) and server_name:
            servers[server_name] = {"url": url if isinstance(url, str) else ""}
    return servers


def _load_reasonix_toml(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse TOML ``plugins`` array (delegates to config_codec)."""
    return _parse_reasonix_toml(text)


def _load_yaml_servers(text: str, key_path: List[str]) -> Dict[str, Dict[str, Any]]:
    """Parse plain YAML configs (e.g. Hermes Agent ``~/.hermes/config.yaml``).

    Unlike ``cordis_yaml`` (an array of loader-patch entries), these keep MCP
    servers as a plain mapping under ``key_path``:

        mcp_servers:
          hermes:
            url: https://mcp.example.com/mcp
    """
    try:
        data = yaml.safe_load(text)
    except (yaml.YAMLError, OSError):
        return {}
    servers = _nested(data, key_path)
    if not isinstance(servers, dict):
        return {}
    return {
        name: entry
        for name, entry in servers.items()
        if isinstance(entry, dict)
    }


def load_mcp_servers(config_path: str, config_format: str, key_path: List[str]) -> Dict[str, Any]:
    path = os.path.expanduser(config_path)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if config_format == "toml":
            return _load_simple_toml_servers(text)
        if config_format == "reasonix_toml":
            return _load_reasonix_toml(text)
        if config_format == "reasonix":
            return _load_reasonix(text)
        if config_format == "cordis_yaml":
            return _load_cordis_yaml(text)
        if config_format == "yaml":
            return _load_yaml_servers(text, key_path)
        data = json.loads(text)
        servers = _nested(data, key_path)
        return servers if isinstance(servers, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def inspect_mcp_configuration(
    servers: Dict[str, Any],
    *,
    expected_name: str,
    expected_url: str,
    legacy_names: List[str],
) -> Dict[str, Any]:
    expected = servers.get(expected_name, {})
    url = expected.get("url", "") if isinstance(expected, dict) else ""
    legacy = sorted(name for name in servers if name in set(legacy_names))
    return {
        "mcp_configured": bool(expected) and url.rstrip("/") == expected_url.rstrip("/") and is_valid_mcp_url(url),
        "configured_url": url,
        "legacy_channels": legacy,
    }


def summarize_records(records: List[Dict[str, Any]]) -> Dict[str, int]:
    installed = [record for record in records if record.get("installed")]
    connected = [
        record for record in installed
        if record.get("mcp_initialize_ok") and record.get("mcp_tools_list_ok")
    ]
    return {
        "installed": len(installed),
        "skills_compliant": sum(bool(record.get("skills_compliant")) for record in installed),
        "mcp_configured": sum(bool(record.get("mcp_configured")) for record in installed),
        "mcp_connected": len(connected),
        "full_capabilities": sum(
            all(record.get("capabilities", {}).values()) for record in connected
        ),
        "hooks_configured": sum(bool(record.get("hooks_configured")) for record in installed),
        "legacy_channels": sum(len(record.get("legacy_channels", [])) for record in installed),
    }
