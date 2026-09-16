import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from legacy_checker import (  # noqa: E402
    AI_MEMORY_DETECTION,
    DEFAULT_LEGACY_DETECTION,
    _check_legacy_server,
    _legacy_channel_of,
    _resolve_block,
    _resolve_detections,
)

CHANNELS = DEFAULT_LEGACY_DETECTION["channels"]


class LegacyServerClassificationTest(unittest.TestCase):
    def test_matches_server_name_keyword(self):
        result = _check_legacy_server(
            "hermes-nas",
            {"command": "python3", "args": ["bridge.py"]},
        )
        self.assertTrue(result["is_legacy"])
        self.assertIn("hermes", result["match_reason"])

    def test_matches_command_pattern(self):
        result = _check_legacy_server(
            "custom",
            {"command": "python3", "args": ["~/.local/bin/hermes-bridge.py"]},
        )
        self.assertTrue(result["is_legacy"])
        self.assertIn("hermes-bridge", result["match_reason"])

    def test_matches_env_key_and_extracts_gateway_url(self):
        result = _check_legacy_server(
            "custom",
            {"command": "python3", "args": ["bridge.py"],
             "env": {"NAS_GATEWAY_URL": "http://nas-et.example.com:8642",
                     "NAS_API_KEY": "REPLACE_ME"}},
        )
        self.assertTrue(result["is_legacy"])
        self.assertEqual(
            result["gateway_url"], "http://nas-et.example.com:8642"
        )

    def test_url_pattern_fallback_from_server_url(self):
        result = _check_legacy_server(
            "custom",
            {"command": "python3", "args": ["bridge.py"],
             "url": "http://nas-gw.example.com:8642/mcp"},
        )
        self.assertTrue(result["is_legacy"])
        self.assertEqual(result["gateway_url"], "http://nas-gw.example.com:8642/mcp")

    def test_non_legacy_server_is_not_flagged(self):
        result = _check_legacy_server(
            "weather",
            {"command": "npx", "args": ["-y", "weather-mcp"]},
        )
        self.assertFalse(result["is_legacy"])

    def test_custom_detection_is_applied(self):
        custom = {"server_name_keywords": ["acme"], "command_patterns": [],
                  "env_keys": [], "url_pattern": ""}
        result = _check_legacy_server(
            "acme-prod", {"command": "acme-bridge"}, detection=custom
        )
        self.assertTrue(result["is_legacy"])
        self.assertIn("acme", result["match_reason"])


class LegacyChannelMappingTest(unittest.TestCase):
    def test_channel_names_resolve(self):
        self.assertEqual(_legacy_channel_of("hermes-nas", CHANNELS, "hermes"), "nas")
        self.assertEqual(_legacy_channel_of("hermes-memory", CHANNELS, "hermes"), "memory")
        self.assertEqual(_legacy_channel_of("hermes-gateway", CHANNELS, "hermes"), "gateway")

    def test_bare_profile_name_maps_to_first_channel(self):
        self.assertEqual(_legacy_channel_of("hermes", CHANNELS, "hermes"), "nas")

    def test_unknown_name_has_no_channel(self):
        self.assertEqual(_legacy_channel_of("random", CHANNELS, "hermes"), "")


class DetectionResolutionTest(unittest.TestCase):
    def test_default_blocks_are_hermes_and_ai_memory(self):
        blocks = _resolve_detections(None)
        self.assertEqual([b["label"] for b in blocks], ["hermes", "ai-memory"])
        self.assertEqual(blocks[0]["server_name_keywords"], ["hermes"])
        self.assertEqual(blocks[0]["gateway_url_env"], "NAS_GATEWAY_URL")
        self.assertEqual(blocks[0]["api_key_env"], "NAS_API_KEY")

    def test_lone_dict_defaults_label_to_hermes(self):
        blocks = _resolve_detections({"server_name_keywords": ["hermes"]})
        self.assertEqual([b["label"] for b in blocks], ["hermes"])

    def test_list_is_preserved(self):
        blocks = _resolve_detections([DEFAULT_LEGACY_DETECTION, AI_MEMORY_DETECTION])
        self.assertEqual([b["label"] for b in blocks], ["hermes", "ai-memory"])

    def test_env_keys_derive_gateway_and_api_key(self):
        det = _resolve_block({"env_keys": ["FOO_URL", "FOO_KEY"]})
        self.assertEqual(det["gateway_url_env"], "FOO_URL")
        self.assertEqual(det["api_key_env"], "FOO_KEY")

    def test_token_suffix_derives_secret_env(self):
        det = _resolve_block({"env_keys": ["AI_MEMORY_SERVER_URL", "AI_MEMORY_AUTH_TOKEN"]})
        self.assertEqual(det["gateway_url_env"], "AI_MEMORY_SERVER_URL")
        self.assertEqual(det["api_key_env"], "AI_MEMORY_AUTH_TOKEN")


class AiMemoryDetectionTest(unittest.TestCase):
    def test_matches_ai_memory_server_name(self):
        result = _check_legacy_server(
            "ai-memory",
            {"command": "python3", "args": ["bridge.py"]},
            detection=AI_MEMORY_DETECTION,
        )
        self.assertTrue(result["is_legacy"])
        self.assertEqual(result["server_details"]["kind"], "ai-memory")

    def test_token_placeholder_is_flagged(self):
        result = _check_legacy_server(
            "ai-memory",
            {"command": "python3", "args": ["ai-memory-bridge.py"],
             "env": {"AI_MEMORY_SERVER_URL": "http://127.0.0.1:49374/mcp",
                     "AI_MEMORY_AUTH_TOKEN": "REPLACE_ME"}},
            detection=AI_MEMORY_DETECTION,
        )
        self.assertTrue(result["is_legacy"])
        self.assertFalse(result["server_details"]["key_valid"])
        self.assertIn("占位值", result["server_details"]["deep_check_note"])

    def test_valid_token_is_accepted(self):
        result = _check_legacy_server(
            "ai-memory",
            {"command": "python3", "args": ["ai-memory-bridge.py"],
             "env": {"AI_MEMORY_SERVER_URL": "http://127.0.0.1:49374/mcp",
                     "AI_MEMORY_AUTH_TOKEN": "real-token-123"}},
            detection=AI_MEMORY_DETECTION,
        )
        self.assertTrue(result["is_legacy"])
        self.assertTrue(result["server_details"]["key_valid"])


if __name__ == "__main__":
    unittest.main()