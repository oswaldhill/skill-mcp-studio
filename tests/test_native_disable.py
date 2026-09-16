"""Stage-4 follow-up: client-native disabled markers (item 7).

Survey (2026-09-04, this machine): none of the 8 managed clients currently
exposes a native per-skill disable marker — symlink presence IS the mechanism.
This module is the config-driven read hook so a future client (e.g. Hermes
``hermes skills config`` once discoverable) plugs in without core changes.

Read-only by design: markers are owned by the client runtime; the tool never
writes them. Unreadable specs fail open to "no native disables" — the symlink
truth still governs.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from native_disable import read_native_disabled  # noqa: E402


class ReadNativeDisabledTest(unittest.TestCase):
    def test_no_spec_returns_empty_set(self):
        self.assertEqual(read_native_disabled({"name": "T"}), set())
        self.assertEqual(read_native_disabled({}), set())

    def test_json_list_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"disabledSkills": ["ascii-art", "tdai"]}))
            tool = {
                "name": "T",
                "native_disable": {"path": str(path), "format": "json", "key_path": ["disabledSkills"]},
            }
            self.assertEqual(read_native_disabled(tool), {"ascii-art", "tdai"})

    def test_yaml_list_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.yaml"
            path.write_text("skills:\n  disabled:\n  - pixel-art\n", encoding="utf-8")
            tool = {
                "name": "T",
                "native_disable": {"path": str(path), "format": "yaml", "key_path": ["skills", "disabled"]},
            }
            self.assertEqual(read_native_disabled(tool), {"pixel-art"})

    def test_toml_list_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[skills]\ndisabled = ["dogfood"]\n', encoding="utf-8")
            tool = {
                "name": "T",
                "native_disable": {"path": str(path), "format": "toml", "key_path": ["skills", "disabled"]},
            }
            self.assertEqual(read_native_disabled(tool), {"dogfood"})

    def test_missing_file_or_key_is_empty(self):
        tool_missing = {
            "name": "T",
            "native_disable": {"path": "/nonexistent/x.json", "format": "json", "key_path": ["k"]},
        }
        self.assertEqual(read_native_disabled(tool_missing), set())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"other": 1}))
            tool_no_key = {
                "name": "T",
                "native_disable": {"path": str(path), "format": "json", "key_path": ["k"]},
            }
            self.assertEqual(read_native_disabled(tool_no_key), set())

    def test_malformed_marker_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json")
            tool = {
                "name": "T",
                "native_disable": {"path": str(path), "format": "json", "key_path": ["k"]},
            }
            self.assertEqual(read_native_disabled(tool), set())

    def test_tilde_path_is_expanded(self):
        tool = {
            "name": "T",
            "native_disable": {"path": "~/nonexistent-marker.json", "format": "json", "key_path": ["k"]},
        }
        self.assertEqual(read_native_disabled(tool), set())


if __name__ == "__main__":
    unittest.main()
