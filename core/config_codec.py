"""Canonical MCP configuration key parsers (A-6).

Single source of truth for the format-specific key extraction shared across the
checker (``mcp_checker``), legacy-channel checker (``legacy_checker``), and fixer
(``mcp_fixer``).  All parsers accept **text** so callers control file I/O and error
wrapping; every format's parsing loop therefore lives here exactly once.

Formats covered:

* ``cordis_yaml``  — DSH cordis loader-patch (tolerates the custom ``!!js`` tag).
* ``toml``         — ``[mcp_servers.<name>]`` table sections (Codex-style).
* ``reasonix``     — JSON ``{"mcp": ["name=command args..."]}`` string array.
* ``reasonix_toml``— TOML ``plugins = [{name = "...", ...}]`` array of tables.

Only stdlib + PyYAML + tomllib are imported, so importing this module can never
re-introduce the ``mcp_checker``/``mcp_fixer`` load-time cycle.
"""

import json
from typing import Any, Dict

try:
    import tomllib as _toml
except ImportError:  # Python < 3.11
    import tomli as _toml

import yaml

# MCP server entries (an intentionally narrow URL-only "unified endpoint" account)
# are built by the *fixer*, not parsed back by this module.  The key-parsing side
# is symmetric with :mod:`mcp_fixer`'s serializers, not a duplicate accelerator.


def parse_cordis_yaml(text: str) -> Any:
    """Parse a cordis patch YAML document tolerating the custom ``!!js`` tag.

    DSH registers MCP servers as cordis loader-patch entries whose headers may use
    the custom ``!!js`` tag for runtime JS expressions.  PyYAML cannot construct
    that tag, so it is registered as an opaque scalar.
    """

    class CordisLoader(yaml.SafeLoader):
        pass

    CordisLoader.add_constructor(
        "tag:yaml.org,2002:js",
        lambda loader, node: loader.construct_scalar(node),
    )
    return yaml.load(text, Loader=CordisLoader)


def _split_toml_server_section(section: str) -> "tuple[str, str]":
    """Split ``<name>[.<sub.table>]`` into ``(server_name, sub_table_path)``.

    TOML semantics: only the **first** dotted key names the server.  A section such
    as ``[mcp_servers.K8s-uat.tools.list_clusters]`` declares the
    ``tools.list_clusters`` *sub-table of server* ``K8s-uat`` — it does not declare a
    server whose name happens to contain dots.  Quoted keys
    (``[mcp_servers."a.b"]``) are TOML's way to give a server a dotted name, so they
    are honoured.
    """
    text = section.strip()
    if not text:
        return "", ""
    if text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        if end == -1:
            return text.strip(quote), ""
        return text[1:end], text[end + 1:].lstrip(".").strip()
    name, _, rest = text.partition(".")
    return name.strip(), rest.strip()


def parse_toml_mcp_servers(text: str) -> Dict[str, Any]:
    """Parse ``[mcp_servers.<name>]`` table sections into a ``name → fields`` map.

    Handles the ``[mcp_servers.<name>.env]`` child table (fields collapse into the
    server's ``env`` sub-mapping) and inline array values (``key = [a, b, c]``).
    This is the superset of the former ``mcp_checker._load_simple_toml_servers``
    (which dropped list values) and ``legacy_checker._load_toml_mcp_servers``
    (which only stripped double quotes).

    **Nested sub-tables never become servers.**  Codex stores per-tool settings as
    ``[mcp_servers.<name>.tools.<tool>]`` (``approval_mode = "approve"``).  Treating
    each of those as a server invented phantom entries; they were classified as
    "unmanaged" and therefore offered for batch cleanup, which silently stripped the
    user's approval settings.  Only the first dotted key is the server name — deeper
    tables are recognised as belonging to it and contribute **no** server fields
    (``env`` is the sole exception, collapsed into ``env``).

    A section header may carry a trailing ``# comment``, and any header outside
    ``mcp_servers`` ends the current context so that later fields can never leak into
    the previously seen server.
    """
    servers: Dict[str, Any] = {}
    cur: str = ""
    cur_env = False
    # True while inside a nested sub-table (or outside mcp_servers at all): field
    # lines are ignored instead of being merged into ``cur``.
    cur_skip = True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        header = line.split("#", 1)[0].strip() if line.startswith("[") else ""
        if header.startswith("[") and header.endswith("]"):
            if header.startswith("[mcp_servers."):
                name, sub = _split_toml_server_section(header[len("[mcp_servers."):-1])
                if not name:
                    cur, cur_env, cur_skip = "", False, True
                elif not sub:
                    cur, cur_env, cur_skip = name, False, False
                    servers.setdefault(name, {})
                elif sub == "env":
                    cur, cur_env, cur_skip = name, True, False
                    servers.setdefault(name, {})
                else:
                    # Sub-table of `name` (e.g. tools.<tool>): belongs to the server
                    # but defines no server field, so it must not add an entry.
                    cur, cur_env, cur_skip = name, False, True
            else:
                cur, cur_env, cur_skip = "", False, True
        elif cur and not cur_skip and "=" in line and not line.startswith("["):
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                value = [i.strip().strip('"').strip("'") for i in inner.split(",")] if inner else []
            else:
                value = value.strip('"').strip("'")
            if cur_env:
                servers[cur].setdefault("env", {})[key] = value
            else:
                servers[cur][key] = value
    return servers


def parse_reasonix_json(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse ``{"mcp": ["name=command args...", ...]}`` into a server map.

    Each array element is a ``name=commandline`` string; the command splits into
    ``{"command": argv0, "args": argv[1:]}``.
    """
    data = json.loads(text)
    servers: Dict[str, Dict[str, Any]] = {}
    if not isinstance(data, dict):
        return servers
    mcp_list = data.get("mcp")
    if not isinstance(mcp_list, list):
        return servers
    for entry in mcp_list:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        name, cmdline = entry.split("=", 1)
        parts = cmdline.split()
        if not parts:
            continue
        servers[name.strip()] = {"command": parts[0], "args": parts[1:]}
    return servers


def parse_reasonix_toml(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse a TOML ``plugins = [{name = "...", ...}]`` array into a server map."""
    data = _toml.loads(text)
    servers: Dict[str, Dict[str, Any]] = {}
    plugins = data.get("plugins", []) if isinstance(data, dict) else []
    if not isinstance(plugins, list):
        return servers
    for plugin in plugins:
        if not isinstance(plugin, dict) or not isinstance(plugin.get("name"), str):
            continue
        servers[plugin["name"]] = {
            key: value for key, value in plugin.items() if key != "name"
        }
    return servers
