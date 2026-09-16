import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from combined_checker import _load_tool_servers  # noqa: E402
from combined_checker import _unmanaged_installed_clients  # noqa: E402
from combined_checker import check_agents  # noqa: E402
from combined_checker import result_ok  # noqa: E402
from checker import is_tool_installed  # noqa: E402


class CombinedCheckerTest(unittest.TestCase):
    def test_installed_skills_client_without_mcp_registry_is_reported(self):
        registry = [{"name": "Codex", "aliases": ["codex"]}]
        scan_result = {
            "results": [
                {
                    "tool_name": ".codex",
                    "path": "~/.codex/skills",
                    "status": "correct",
                    "is_installed": True,
                },
                {
                    "tool_name": ".copilot",
                    "path": "~/.copilot/skills",
                    "status": "correct",
                    "is_installed": True,
                },
                {
                    "tool_name": "TRAE",
                    "path": "~/.trae-cn/skills",
                    "status": "correct",
                    "is_installed": False,
                },
            ]
        }

        result = _unmanaged_installed_clients(registry, scan_result)

        self.assertEqual([item["name"] for item in result], [".copilot"])
        self.assertTrue(result[0]["skills_compliant"])

    def test_tools_registry_clients_are_managed_without_mcp_entry(self):
        # Clients registered only in the skills-facing ``tools`` section (no
        # MCP surface to manage, e.g. GitHub Copilot) are managed at L2 and
        # must not be reported as unmanaged.
        registry = [{"name": "Codex", "aliases": ["codex"]}]
        tools_registry = [{"name": ".copilot", "skills_paths": ["~/.copilot/skills"]}]
        scan_result = {
            "results": [
                {
                    "tool_name": ".copilot",
                    "path": "~/.copilot/skills",
                    "status": "correct",
                    "is_installed": True,
                },
                {
                    "tool_name": ".orphan",
                    "path": "~/.orphan/skills",
                    "status": "correct",
                    "is_installed": True,
                },
            ]
        }

        result = _unmanaged_installed_clients(registry, scan_result, tools_registry=tools_registry)

        self.assertEqual([item["name"] for item in result], [".orphan"])

    def test_exempt_clients_are_not_unmanaged(self):
        # Config-declared exemptions (known non-skill consumers whose links
        # exist, e.g. cc-switch) stay silent instead of failing the audit.
        scan_result = {
            "results": [
                {
                    "tool_name": ".cc-switch",
                    "path": "~/.cc-switch/skills",
                    "status": "correct",
                    "is_installed": True,
                },
                {
                    "tool_name": ".orphan",
                    "path": "~/.orphan/skills",
                    "status": "correct",
                    "is_installed": True,
                },
            ]
        }

        result = _unmanaged_installed_clients([], scan_result, exempt=[".cc-switch"])

        self.assertEqual([item["name"] for item in result], [".orphan"])

    def test_dsh_skills_compliance_cross_referenced_from_tools_section(self):
        # DSH is registered in both mcp_tools and tools; its skills path must be
        # cross-referenced from the skills scan so skills_compliant is True even
        # though DSH has no standalone skills symlink discovery of its own.
        config = {
            "unified_mcp": {
                "name": "hermes",
                "url": "https://mcp.example.com/mcp",
                "legacy_names": [],
                "required_capabilities": {},
            },
            "mcp_tools": [
                {
                    "name": "DSH",
                    "aliases": ["dsh"],
                    "install": {
                        "app_bundles": [],
                        "commands": ["dsh"],
                        "config_paths": ["/nonexistent/dsh/cordis.patch.yml"],
                    },
                    "config_path": "/nonexistent/dsh/cordis.patch.yml",
                    "format": "cordis_yaml",
                    "mcp_key_path": ["hermes"],
                },
            ],
            "tools": [
                {"name": "DSH", "skills_paths": ["~/.dsh/skills"], "type": "AI Agent"},
            ],
        }
        scan_result = {
            "results": [
                {
                    "tool_name": "DSH",
                    "path": "~/.dsh/skills",
                    "status": "correct",
                    "is_installed": True,
                },
            ]
        }
        result = check_agents(config, scan_result)
        dsh = next(r for r in result["records"] if r["name"] == "DSH")
        self.assertTrue(dsh["skills_compliant"])

    def test_dsh_installed_via_config_evidence(self):
        # DSH ships no CLI/App in PATH; the cordis patch config file is the proof
        # of installation, so is_tool_installed must resolve it via config evidence.
        self.assertTrue(is_tool_installed("DSH"))
        self.assertTrue(is_tool_installed("dsh"))

    def test_native_disable_marker_flows_into_record_states(self):
        # A registry-declared native_disable spec (read-only marker owned by the
        # client runtime) must override an otherwise-valid enable link in the
        # record's skill_states and be surfaced for the audit channels.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "ascii-art").mkdir(parents=True)
            (repo / "tdai").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "ascii-art", client / "ascii-art", target_is_directory=True)
            os.symlink(repo / "tdai", client / "tdai", target_is_directory=True)
            marker = Path(tmp) / "marker.json"
            marker.write_text(json.dumps({"disabledSkills": ["ascii-art"]}))

            config = {
                "unified_mcp": {
                    "name": "hermes",
                    "url": "https://mcp.example.com/mcp",
                    "legacy_names": [],
                    "required_capabilities": {},
                },
                "mcp_tools": [
                    {
                        "name": "Codex",
                        "aliases": ["codex"],
                        "install": {"config_paths": [str(marker)]},
                        "config_path": str(marker),
                        "format": "json",
                        "mcp_key_path": ["mcpServers"],
                        "native_disable": {
                            "path": str(marker),
                            "format": "json",
                            "key_path": ["disabledSkills"],
                        },
                    },
                ],
            }
            scan_result = {
                "unified_dir": str(repo),
                "results": [
                    {
                        "tool_name": "Codex",
                        "path": str(client),
                        "expanded_path": str(client),
                        "status": "correct",
                        "is_installed": True,
                    },
                ],
            }
            result = check_agents(config, scan_result)
            codex = next(r for r in result["records"] if r["name"] == "Codex")
            self.assertEqual(codex["skill_states"]["ascii-art"], "disabled")
            self.assertEqual(codex["skill_states"]["tdai"], "enabled")
            self.assertEqual(codex["native_disabled_skills"], ["ascii-art"])
            self.assertEqual(codex["skills_enabled_count"], 1)
            self.assertEqual(codex["skills_total"], 2)

    def test_per_tool_legacy_names_flag_bridge_entries(self):
        # OpenCode shape: canonical entry under per-tool unified_name
        # ("hermes-unified") while a stdio bridge occupies the plain "hermes"
        # name. The profile declares no legacy_names; the tool entry does.
        # The audit must flag the bridge as a legacy channel while keeping
        # mcp_configured True (OpenCode leftover cleanup, 2026-09-04).
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "opencode.jsonc"
            config_file.write_text(json.dumps({
                "mcp": {
                    "hermes": {
                        "type": "local",
                        "command": ["python3", "/home/u/.local/bin/hermes-bridge.py"],
                        "env": {"NAS_GATEWAY_URL": "http://nas.example:8642"},
                    },
                    "hermes-unified": {"url": "https://mcp.example.com/mcp"},
                },
            }))
            config = {
                "unified_mcp": {
                    "name": "hermes",
                    "url": "https://mcp.example.com/mcp",
                    "legacy_names": [],
                    "required_capabilities": {},
                },
                "mcp_tools": [
                    {
                        "name": "OpenCode",
                        "aliases": ["opencode"],
                        "install": {"config_paths": [str(config_file)]},
                        "config_path": str(config_file),
                        "format": "jsonc",
                        "mcp_key_path": ["mcp"],
                        "unified_name": "hermes-unified",
                        "legacy_names": ["hermes"],
                    },
                ],
            }
            result = check_agents(config, {"results": []})
            opencode = next(r for r in result["records"] if r["name"] == "OpenCode")
            self.assertTrue(opencode["mcp_configured"])
            self.assertEqual(opencode["legacy_channels"], ["hermes"])

    def test_load_tool_servers_merges_config_candidates(self):
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            primary = os.path.join(tmp, "primary.cordis.yml")
            candidate = os.path.join(tmp, "mcp.json")
            # Primary cordis patch: present but without the unified endpoint.
            with open(primary, "w", encoding="utf-8") as fh:
                fh.write("- id: system-prompt\n  config:\n    persona: x\n")
            # Candidate json: carries the unified hermes endpoint.
            with open(candidate, "w", encoding="utf-8") as fh:
                json.dump(
                    {"mcpServers": {"hermes": {"url": "https://mcp.example.com/mcp"}}},
                    fh,
                )
            tool = {
                "config_path": primary,
                "format": "cordis_yaml",
                "mcp_key_path": ["hermes"],
                "config_candidates": [
                    {"path": candidate, "format": "json", "key_path": ["mcpServers"]}
                ],
            }
            servers = _load_tool_servers(tool)
            self.assertIn("hermes", servers)
            self.assertEqual(
                servers["hermes"].get("url"), "https://mcp.example.com/mcp"
            )

    def test_load_tool_servers_without_candidates_matches_single_path(self):
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            only = os.path.join(tmp, "mcp.json")
            with open(only, "w", encoding="utf-8") as fh:
                json.dump(
                    {"mcpServers": {"hermes": {"url": "https://mcp.example.com/mcp"}}},
                    fh,
                )
            tool = {"config_path": only, "format": "json", "mcp_key_path": ["mcpServers"]}
            servers = _load_tool_servers(tool)
            self.assertIn("hermes", servers)
            # No candidates declared -> identical to the previous single-path behavior.
            self.assertEqual(len(servers), 1)

    def test_dsh_configured_via_config_candidates(self):
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cordis = os.path.join(tmp, "cordis.patch.yml")
            mcp = os.path.join(tmp, "mcp.json")
            with open(cordis, "w", encoding="utf-8") as fh:
                fh.write("- id: system-prompt\n  config:\n    persona: x\n")
            with open(mcp, "w", encoding="utf-8") as fh:
                json.dump(
                    {"mcpServers": {"hermes": {"url": "https://mcp.example.com/mcp"}}},
                    fh,
                )
            config = {
                "unified_mcp": {
                    "name": "hermes",
                    "url": "https://mcp.example.com/mcp",
                    "legacy_names": [],
                    "required_capabilities": {},
                },
                "mcp_tools": [
                    {
                        "name": "DSH",
                        "aliases": ["dsh"],
                        "install": {
                            "app_bundles": [],
                            "commands": ["dsh"],
                            "config_paths": [cordis],
                        },
                        "config_path": cordis,
                        "format": "cordis_yaml",
                        "mcp_key_path": ["hermes"],
                        "config_candidates": [
                            {"path": mcp, "format": "json", "key_path": ["mcpServers"]}
                        ],
                    },
                ],
            }
            result = check_agents(config, {"results": []})
            dsh = next(r for r in result["records"] if r["name"] == "DSH")
            self.assertTrue(dsh["mcp_configured"])
            self.assertFalse(dsh["legacy_channels"])


class ResultOkTest(unittest.TestCase):
    def test_compliant_result_is_ok(self):
        result = {
            "probe": {"error": ""},
            "records": [
                {
                    "installed": True,
                    "skills_compliant": True,
                    "mcp_configured": True,
                    "mcp_initialize_ok": True,
                    "mcp_tools_list_ok": True,
                    "hooks_configured": True,
                    "legacy_channels": [],
                    "capabilities": {"hermes_memory": True},
                }
            ],
            "unmanaged": [],
        }
        self.assertTrue(result_ok(result))

    def test_unmet_capability_is_not_ok(self):
        result = {
            "probe": {"error": ""},
            "records": [
                {
                    "installed": True,
                    "skills_compliant": True,
                    "mcp_configured": True,
                    "mcp_initialize_ok": True,
                    "mcp_tools_list_ok": True,
                    "hooks_configured": True,
                    "legacy_channels": [],
                    "capabilities": {"hermes_memory": False},
                }
            ],
            "unmanaged": [],
        }
        self.assertFalse(result_ok(result))

    def test_probe_error_is_not_ok(self):
        result = {
            "probe": {"error": "spawn fail"},
            "records": [],
            "unmanaged": [],
        }
        self.assertFalse(result_ok(result))

    def test_uninstalled_clients_are_ignored(self):
        result = {
            "probe": {"error": "not probed"},
            "records": [
                {
                    "installed": False,
                    "skills_compliant": False,
                    "mcp_configured": False,
                    "mcp_initialize_ok": False,
                    "mcp_tools_list_ok": False,
                    "hooks_configured": False,
                    "legacy_channels": [],
                    "capabilities": {},
                }
            ],
            "unmanaged": [],
        }
        self.assertTrue(result_ok(result))

    def test_tool_endpoint_does_not_require_hooks(self):
        # 纯工具端点（required_capabilities 无 ai_memory）标记 hooks_required=False，
        # 客户端未配 hermes hooks 也不阻断 ok（hooks 是 AI-memory 特有概念）。
        result = {
            "probe": {"error": ""},
            "records": [
                {
                    "installed": True,
                    "skills_compliant": True,
                    "mcp_configured": True,
                    "mcp_initialize_ok": True,
                    "mcp_tools_list_ok": True,
                    "hooks_configured": False,
                    "hooks_required": False,
                    "legacy_channels": [],
                    "capabilities": {},
                }
            ],
            "unmanaged": [],
        }
        self.assertTrue(result_ok(result))


if __name__ == "__main__":
    unittest.main()
