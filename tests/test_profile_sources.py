"""profile_sources: external (local, untracked) profile overlays.

The trunk config.yaml stays free of personal topology (stage-1 principle):
``profile_sources`` lists extra YAML files whose ``profiles`` / ``templates`` /
``active_profile`` are merged over the inline config. Missing files are skipped
gracefully; malformed ones fail as ProfileError (exit-code 2 channel).
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from profile_loader import (  # noqa: E402
    ProfileError,
    apply_profile_sources,
    list_profiles,
    load_profile,
)


def base_config():
    return {
        "schema_version": 1,
        "active_profile": "generic-http",
        "profile_sources": [],
        "profiles": {
            "generic-http": {
                "name": "my-mcp",
                "url": "https://example.internal/mcp",
                "transport": "streamable-http",
                "url_policy": "strict",
                "required_capabilities": {},
            }
        },
    }


def write_source(tmp, name, text):
    path = Path(tmp) / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class ApplyProfileSourcesTest(unittest.TestCase):
    def test_no_sources_is_identity(self):
        config = base_config()
        apply_profile_sources(config)
        self.assertEqual(list_profiles(config), ["generic-http"])

    def test_source_adds_profile_and_overrides_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = write_source(
                tmp,
                "local.yaml",
                "active_profile: hermes-home\n"
                "profiles:\n"
                "  hermes-home:\n"
                "    name: hermes\n"
                "    url: https://hermes.example.com/mcp\n"
                "    transport: streamable-http\n"
                "    required_capabilities: {}\n",
            )
            config = base_config()
            config["profile_sources"] = [src]
            apply_profile_sources(config)
            self.assertEqual(list_profiles(config), ["generic-http", "hermes-home"])
            bundle = load_profile(config)  # default selection = active_profile
            self.assertEqual(bundle["name"], "hermes-home")
            self.assertEqual(bundle["profile"]["url"], "https://hermes.example.com/mcp")

    def test_source_overrides_inline_profile_on_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = write_source(
                tmp,
                "local.yaml",
                "profiles:\n"
                "  generic-http:\n"
                "    name: overridden\n"
                "    url: https://override.example.com/mcp\n"
                "    required_capabilities: {}\n",
            )
            config = base_config()
            config["profile_sources"] = [src]
            apply_profile_sources(config)
            bundle = load_profile(config, "generic-http")
            self.assertEqual(bundle["profile"]["url"], "https://override.example.com/mcp")

    def test_later_source_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = write_source(
                tmp, "a.yaml",
                "profiles:\n  p:\n    name: first\n    url: https://first.example.com/mcp\n",
            )
            second = write_source(
                tmp, "b.yaml",
                "profiles:\n  p:\n    name: second\n    url: https://second.example.com/mcp\n",
            )
            config = base_config()
            config["profile_sources"] = [first, second]
            apply_profile_sources(config)
            self.assertEqual(load_profile(config, "p")["profile"]["name"], "second")

    def test_missing_source_is_skipped_gracefully(self):
        config = base_config()
        config["profile_sources"] = ["/nonexistent/profiles.local.yaml"]
        apply_profile_sources(config)  # must not raise
        self.assertEqual(list_profiles(config), ["generic-http"])

    def test_malformed_source_raises_profile_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = write_source(tmp, "bad.yaml", "profiles: [not, a, mapping]")
            config = base_config()
            config["profile_sources"] = [src]
            with self.assertRaises(ProfileError):
                apply_profile_sources(config)

    def test_source_templates_usable_by_extends(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = write_source(
                tmp,
                "local.yaml",
                "templates:\n"
                "  memory-basic:\n"
                "    capabilities:\n"
                "      memory: [memory_search]\n"
                "profiles:\n"
                "  hermes-home:\n"
                "    name: hermes\n"
                "    url: https://hermes.example.com/mcp\n"
                "    required_capabilities:\n"
                "      extends: [memory-basic]\n",
            )
            config = base_config()
            config["profile_sources"] = [src]
            apply_profile_sources(config)
            bundle = load_profile(config, "hermes-home")
            self.assertEqual(
                bundle["profile"]["required_capabilities"], {"memory": ["memory_search"]}
            )

    def test_tilde_paths_expand(self):
        config = base_config()
        # A ~ path to a file that does not exist must still skip gracefully,
        # proving expansion happened (no literal '~' in the isfile check).
        config["profile_sources"] = ["~/__skill_mcp_studio_no_such_file__.yaml"]
        apply_profile_sources(config)
        self.assertEqual(list_profiles(config), ["generic-http"])

    def test_disabled_tools_merged_as_normalized_union(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = write_source(tmp, "local.yaml", "disabled_tools:\n- Claude Code\n- Cursor\n")
            config = base_config()
            config["profile_sources"] = [src]
            apply_profile_sources(config)
            # 归一化名称并排序，支持别名/空格归一化
            self.assertEqual(config.get("disabled_tools"), ["claudecode", "cursor"])

    def test_disabled_tools_only_from_overlay_not_inline(self):
        config = base_config()
        apply_profile_sources(config)
        # 无 overlay 声明时，不应凭空注入 disabled_tools
        self.assertNotIn("disabled_tools", config)


class LoadConfigIntegrationTest(unittest.TestCase):
    def test_scanner_load_config_applies_sources(self):
        from scanner import load_config

        with tempfile.TemporaryDirectory() as tmp:
            src = write_source(
                tmp,
                "local.yaml",
                "active_profile: hermes-home\n"
                "profiles:\n"
                "  hermes-home:\n"
                "    name: hermes\n"
                "    url: https://hermes.example.com/mcp\n"
                "    required_capabilities: {}\n",
            )
            main = Path(tmp) / "config.yaml"
            main.write_text(
                "schema_version: 1\n"
                "active_profile: generic-http\n"
                f"profile_sources: [{src}]\n"
                "profiles:\n"
                "  generic-http:\n"
                "    name: my-mcp\n"
                "    url: https://example.internal/mcp\n"
                "    required_capabilities: {}\n",
                encoding="utf-8",
            )
            config = load_config(str(main))
            self.assertEqual(load_profile(config)["name"], "hermes-home")


if __name__ == "__main__":
    unittest.main()
