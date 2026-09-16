import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_checker import (  # noqa: E402
    inspect_mcp_configuration,
    is_valid_mcp_url,
    load_mcp_servers,
    summarize_records,
)


class McpCheckerTest(unittest.TestCase):
    def test_portless_https_url_is_valid(self):
        self.assertTrue(is_valid_mcp_url("https://mcp.example.com/mcp"))
        self.assertFalse(is_valid_mcp_url("http://mcp.example.com/mcp"))
        self.assertFalse(is_valid_mcp_url("https:///mcp"))

    def test_json_and_toml_direct_urls_are_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "mcp.json"
            json_path.write_text(json.dumps({
                "mcpServers": {"hermes": {"url": "https://mcp.example.com/mcp"}}
            }))
            toml_path = Path(temp_dir) / "config.toml"
            toml_path.write_text(
                '[mcp_servers.hermes]\nurl = "https://mcp.example.com/mcp"\n'
            )

            json_servers = load_mcp_servers(str(json_path), "json", ["mcpServers"])
            toml_servers = load_mcp_servers(str(toml_path), "toml", ["mcp_servers"])

            self.assertEqual(json_servers["hermes"]["url"], "https://mcp.example.com/mcp")
            self.assertEqual(toml_servers["hermes"]["url"], "https://mcp.example.com/mcp")

    def test_legacy_channels_are_reported(self):
        record = inspect_mcp_configuration(
            {"hermes-memory": {"command": "python3"}, "hermes-gateway": {"command": "python3"}},
            expected_name="hermes",
            expected_url="https://mcp.example.com/mcp",
            legacy_names=["hermes-nas", "hermes-memory", "hermes-gateway", "ai-memory"],
        )
        self.assertFalse(record["mcp_configured"])
        self.assertEqual(record["legacy_channels"], ["hermes-gateway", "hermes-memory"])

    def test_summary_is_derived_from_records(self):
        records = [
            {"installed": True, "skills_compliant": True, "mcp_configured": True,
             "mcp_initialize_ok": True, "mcp_tools_list_ok": True,
             "capabilities": {"hermes_memory": True, "ai_memory": True,
                              "tdai": True, "hermes": True},
             "hooks_configured": False, "legacy_channels": ["ai-memory"]},
            {"installed": True, "skills_compliant": False, "mcp_configured": False,
             "mcp_initialize_ok": False, "mcp_tools_list_ok": False,
             "capabilities": {"hermes_memory": False, "ai_memory": False,
                              "tdai": False, "hermes": False},
             "hooks_configured": True, "legacy_channels": []},
            {"installed": False, "skills_compliant": True, "mcp_configured": True,
             "mcp_initialize_ok": True, "mcp_tools_list_ok": True,
             "capabilities": {"hermes_memory": True, "ai_memory": True,
                              "tdai": True, "hermes": True},
             "hooks_configured": True, "legacy_channels": []},
        ]
        summary = summarize_records(records)
        self.assertEqual(summary["installed"], 2)
        self.assertEqual(summary["skills_compliant"], 1)
        self.assertEqual(summary["mcp_configured"], 1)
        self.assertEqual(summary["mcp_connected"], 1)
        self.assertEqual(summary["full_capabilities"], 1)
        self.assertEqual(summary["hooks_configured"], 1)
        self.assertEqual(summary["legacy_channels"], 1)


    def test_cordis_yaml_loads_canonical_server_by_server_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cordis.patch.yml"
            path.write_text(
                "- id: mcp-hermes\n"
                "  name: '@deepseek-ai/dsh-mcp-client'\n"
                "  config:\n"
                "    serverName: hermes\n"
                "    transport: streamable-http\n"
                "    url: https://mcp.example.com/mcp\n",
                encoding="utf-8",
            )
            servers = load_mcp_servers(str(path), "cordis_yaml", ["hermes"])
            self.assertIn("hermes", servers)
            self.assertEqual(servers["hermes"]["url"], "https://mcp.example.com/mcp")

    def test_cordis_yaml_wrong_url_is_not_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cordis.patch.yml"
            path.write_text(
                "- id: mcp-other\n"
                "  config:\n"
                "    serverName: hermes\n"
                "    url: https://elsewhere.example/mcp\n",
                encoding="utf-8",
            )
            servers = load_mcp_servers(str(path), "cordis_yaml", ["hermes"])
            inspected = inspect_mcp_configuration(
                servers, expected_name="hermes",
                expected_url="https://mcp.example.com/mcp", legacy_names=[],
            )
            self.assertFalse(inspected["mcp_configured"])

    def test_plain_yaml_servers_are_loaded_by_key_path(self):
        # Hermes Agent keeps MCP servers in ~/.hermes/config.yaml under a
        # top-level `mcp_servers:` mapping (plain YAML, not cordis patches).
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "hermes-config.yaml"
            path.write_text(
                "hooks:\n"
                "  on_session_end:\n"
                "  - command: /usr/bin/true\n"
                "    timeout: 5\n"
                "mcp_servers:\n"
                "  hermes:\n"
                "    url: https://mcp.example.com/mcp\n"
                "    transport: streamable-http\n",
                encoding="utf-8",
            )
            servers = load_mcp_servers(str(path), "yaml", ["mcp_servers"])
            self.assertEqual(servers["hermes"]["url"], "https://mcp.example.com/mcp")

    def test_plain_yaml_empty_mapping_returns_no_servers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "hermes-config.yaml"
            path.write_text("hooks: {}\nmcp_servers: {}\n", encoding="utf-8")
            servers = load_mcp_servers(str(path), "yaml", ["mcp_servers"])
            self.assertEqual(servers, {})

    def test_plain_yaml_malformed_or_missing_key_is_graceful(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bad = Path(temp_dir) / "bad.yaml"
            bad.write_text("mcp_servers: [unbalanced\n", encoding="utf-8")
            self.assertEqual(load_mcp_servers(str(bad), "yaml", ["mcp_servers"]), {})
            no_key = Path(temp_dir) / "nokey.yaml"
            no_key.write_text("other: 1\n", encoding="utf-8")
            self.assertEqual(load_mcp_servers(str(no_key), "yaml", ["mcp_servers"]), {})


if __name__ == "__main__":
    unittest.main()
