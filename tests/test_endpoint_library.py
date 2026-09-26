"""Stage-5 P1: endpoint library + per-client attachment + MCP inventory."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from endpoint_library import (  # noqa: E402
    attach_map,
    endpoint_entries,
    list_endpoints,
    resolve_client_attach,
    validate_attachment,
)
from profile_loader import ProfileError  # noqa: E402
from mcp_inventory import (  # noqa: E402
    classify_entries,
    list_client_mcp_entries,
    McpEntry,
)


def _config():
    return {
        "schema_version": 2,
        "active_profile": "hermes-home",
        "profiles": {
            "hermes-home": {
                "name": "hermes",
                "url": "https://hermes.example.com/mcp",
                "required_capabilities": {},
            },
            "other": {
                "name": "other",
                "url": "https://other.example.com/mcp",
                "required_capabilities": {},
            },
        },
        "mcp_tools": [
            {
                "name": "Cursor",
                "config_path": "~/.cursor/mcp.json",
                "format": "json",
                "mcp_key_path": ["mcpServers"],
            },
            {
                "name": "Claude",
                "config_path": "~/.claude.json",
                "format": "json",
                "mcp_key_path": ["mcpServers"],
                "mcp_attach": ["hermes-home"],
            },
        ],
    }


class EndpointLibraryTest(unittest.TestCase):
    def test_list_endpoints(self):
        self.assertEqual(list_endpoints(_config()), ["hermes-home", "other"])

    def test_default_attach_is_all_endpoints(self):
        config = _config()
        cursor = config["mcp_tools"][0]
        self.assertEqual(resolve_client_attach(cursor, config), ["hermes-home", "other"])

    def test_explicit_attach_wins(self):
        config = _config()
        claude = config["mcp_tools"][1]
        self.assertEqual(resolve_client_attach(claude, config), ["hermes-home"])

    def test_attach_map_declared_only(self):
        self.assertEqual(attach_map(_config()), {"Claude": ["hermes-home"]})

    def test_validate_attachment_ok(self):
        validate_attachment(_config())  # no raise

    def test_validate_attachment_unknown_key(self):
        config = _config()
        config["mcp_tools"][1]["mcp_attach"] = ["nope"]
        with self.assertRaises(ProfileError):
            validate_attachment(config)

    def test_validate_attachment_non_list(self):
        config = _config()
        config["mcp_tools"][0]["mcp_attach"] = "hermes-home"
        with self.assertRaises(ProfileError):
            resolve_client_attach(config["mcp_tools"][0], config)

    def test_endpoint_entries_inject_key(self):
        entries = endpoint_entries(_config())
        keys = [entry["key"] for entry in entries]
        self.assertEqual(keys, ["hermes-home", "other"])
        self.assertEqual(entries[0]["url"], "https://hermes.example.com/mcp")


class McpInventoryTest(unittest.TestCase):
    def test_classify_attached_legacy_unmanaged(self):
        entries = [
            McpEntry(key="hermes", url="https://hermes.example.com/mcp"),
            McpEntry(key="hermes-nas", url="https://old/mcp"),
            McpEntry(key="unknown-srv", url="https://x/mcp"),
        ]
        endpoint_list = [
            {"key": "hermes-home", "name": "hermes", "url": "https://hermes.example.com/mcp"}
        ]
        classified = classify_entries(
            entries,
            endpoint_entries=endpoint_list,
            legacy_names=["hermes-nas"],
        )
        by_key = {c.key: c for c in classified}
        self.assertEqual(by_key["hermes"].classification, "attached")
        self.assertEqual(by_key["hermes"].endpoint_key, "hermes-home")
        self.assertEqual(by_key["hermes-nas"].classification, "legacy")
        self.assertEqual(by_key["unknown-srv"].classification, "unmanaged")

    def test_classify_does_not_mutate_input(self):
        entry = McpEntry(key="hermes")
        classify_entries(
            [entry],
            endpoint_entries=[{"key": "hermes-home", "name": "hermes"}],
            legacy_names=[],
        )
        self.assertEqual(entry.classification, "unmanaged")
        self.assertIsNone(entry.endpoint_key)


if __name__ == "__main__":
    unittest.main()
