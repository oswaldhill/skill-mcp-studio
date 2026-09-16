"""End-to-end proof for phase-2 DoD: a generic capability template drives a full
four-question audit (install evidence -> Skills path -> MCP config+hooks ->
endpoint liveness + capability-group coverage).

The live HTTP handshake itself is covered against a real subprocess server in
``test_stdio_probe.py``; here the live probe is stubbed to a deterministic
tools/list so we can assert the *orchestration* end-to-end without a network.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from combined_checker import check_agents, result_ok  # noqa: E402
from profile_loader import load_profile, list_profiles  # noqa: E402

ENDPOINT_URL = "https://example.internal/mcp"
STUB_TOOL_NAMES = ["memory_search", "memory_add", "extra_tool"]


def _make_config(tmp: str) -> dict:
    mcp_json = os.path.join(tmp, "client-mcp.json")
    with open(mcp_json, "w", encoding="utf-8") as handle:
        json.dump({"mcpServers": {"generic-mcp": {"url": ENDPOINT_URL}}}, handle)

    hooks_json = os.path.join(tmp, "client-hooks.json")
    with open(hooks_json, "w", encoding="utf-8") as handle:
        json.dump({
            "hooks": {
                "on_session_end": {"command": "ai-memory-sync --write"},
            }
        }, handle)

    install_evidence = os.path.join(tmp, "client-installed.flag")
    with open(install_evidence, "w", encoding="utf-8") as handle:
        handle.write("x")
    # 三态语义整改: 仅 config 不再算 installed；给夹具加真实授权的 app bundle。
    app_dir = os.path.join(tmp, "FakeClient.app")
    os.makedirs(app_dir, exist_ok=True)

    return {
        "schema_version": 1,
        "active_profile": "generic-http",
        "templates": {
            "memory-basic": {
                "capabilities": {"memory": ["memory_search", "memory_add"]},
            },
        },
        "profiles": {
            "generic-http": {
                "name": "generic-mcp",
                "url": ENDPOINT_URL,
                "transport": "streamable-http",
                "url_policy": "strict",
                "required_capabilities": {"extends": ["memory-basic"]},
            },
        },
        "mcp_tools": [
            {
                "name": "FakeClient",
                "aliases": ["fakeclient"],
                "install": {
                    "app_bundles": [app_dir],
                    "commands": [],
                    "config_paths": [install_evidence],
                },
                "config_path": mcp_json,
                "format": "json",
                "mcp_key_path": ["mcpServers"],
                "hooks_config_path": hooks_json,
            },
        ],
    }


SCAN_RESULT = {
    "results": [
        {
            "tool_name": "FakeClient",
            "path": "~/.fakeclient/skills",
            "status": "correct",
            "is_installed": True,
        },
    ],
}


class TemplateDrivenFourQuestionAuditTest(unittest.TestCase):
    def test_template_resolves_and_drives_all_four_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(tmp)

            # Template resolves "extends" into a capability group whose tools the
            # (stubbed) endpoint must expose.
            bundle = load_profile(config, "generic-http")
            profile = bundle["profile"]
            self.assertEqual(profile["name"], "generic-mcp")
            self.assertEqual(
                profile["required_capabilities"],
                {"memory": ["memory_search", "memory_add"]},
            )

            with mock.patch(
                "combined_checker.probe_mcp",
                return_value={
                    "initialize_ok": True,
                    "tools_list_ok": True,
                    "tool_names": STUB_TOOL_NAMES,
                    "error": "",
                },
            ):
                result = check_agents(
                    config, SCAN_RESULT, live_probe=True, profile=profile
                )

            record = result["records"][0]
            # Q1 install evidence -> Q2 Skills path -> Q3 MCP config + hooks
            self.assertTrue(record["installed"], record["install_evidence"])
            self.assertTrue(record["skills_compliant"], "Skills path not compliant")
            self.assertTrue(record["mcp_configured"], "MCP config not detected")
            self.assertTrue(record["hooks_configured"], "hooks not detected")
            # Q4 live endpoint: initialize + tools/list + capability coverage
            self.assertTrue(record["mcp_initialize_ok"])
            self.assertTrue(record["mcp_tools_list_ok"])
            self.assertEqual(
                record["capabilities"],
                {"memory": True},
                "capability group from template not satisfied",
            )

            # The whole run is compliant -> exit code 0.
            self.assertTrue(result_ok(result))
            self.assertEqual(result["capability_groups"], ["memory"])

    def test_missing_template_fails_at_load_time_exit_2(self):
        config = {
            "schema_version": 1,
            "active_profile": "generic-http",
            "profiles": {
                "generic-http": {
                    "name": "generic-mcp",
                    "url": ENDPOINT_URL,
                    "required_capabilities": {"extends": ["nope"]},
                }
            },
        }
        from profile_loader import ProfileError

        with self.assertRaises(ProfileError):
            load_profile(config, "generic-http")

    def test_list_profiles_includes_template_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(tmp)
            self.assertEqual(list_profiles(config), ["generic-http"])


class ProjectTemplatesWiringTest(unittest.TestCase):
    """阶段二 §14.1 落地：项目级模板目录经 config_path 穿线到 load_profile。

    目录布局：``<config 所在目录>/.skill-mcp-studio/templates/*.yaml``，
    优先级 用户 > 项目级 > 内置（config['templates']）。
    """

    def test_project_dir_template_resolves_extends(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(tmp)
            # 把内置模板移走，改由项目级目录提供
            del config["templates"]
            config_path = os.path.join(tmp, "config.yaml")
            project_templates = os.path.join(tmp, ".skill-mcp-studio", "templates")
            os.makedirs(project_templates, exist_ok=True)
            with open(os.path.join(project_templates, "memory-basic.yaml"), "w", encoding="utf-8") as handle:
                handle.write("capabilities:\n  memory:\n    - memory_search\n    - memory_add\n")

            bundle = load_profile(config, "generic-http", config_path=config_path)
            self.assertEqual(
                bundle["profile"]["required_capabilities"],
                {"memory": ["memory_search", "memory_add"]},
            )

    def test_no_config_path_falls_back_to_no_project_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(tmp)
            del config["templates"]
            # 项目级目录存在但未传 config_path → 解析不到模板 → 加载期失败
            # （mock 用户目录为空，保证测试不受真实 ~/.config 影响）
            project_templates = os.path.join(tmp, ".skill-mcp-studio", "templates")
            os.makedirs(project_templates, exist_ok=True)
            with open(os.path.join(project_templates, "memory-basic.yaml"), "w", encoding="utf-8") as handle:
                handle.write("capabilities:\n  memory:\n    - memory_search\n")
            from profile_loader import ProfileError

            empty_user_dir = os.path.join(tmp, "empty-user")
            os.makedirs(empty_user_dir, exist_ok=True)
            with mock.patch(
                "capability_templates._default_user_dir", return_value=empty_user_dir
            ):
                with self.assertRaises(ProfileError):
                    load_profile(config, "generic-http")

    def test_malformed_project_template_fails_at_load_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(tmp)
            config_path = os.path.join(tmp, "config.yaml")
            project_templates = os.path.join(tmp, ".skill-mcp-studio", "templates")
            os.makedirs(project_templates, exist_ok=True)
            with open(os.path.join(project_templates, "broken.yaml"), "w", encoding="utf-8") as handle:
                handle.write("capabilities:\n  memory: not-a-list\n")
            from profile_loader import ProfileError

            with self.assertRaises(ProfileError) as ctx:
                load_profile(config, "generic-http", config_path=config_path)
            self.assertIn("broken.yaml", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()