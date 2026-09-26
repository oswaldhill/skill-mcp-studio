"""Stage-5 P3: endpoint store CRUD + attachment overlay + profile_loader merge."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import yaml  # noqa: E402

from endpoint_store import (  # noqa: E402
    add_endpoint,
    remove_endpoint,
    set_client_attach,
    update_endpoint,
)
from profile_loader import apply_profile_sources  # noqa: E402


def _config_with_source(source_path):
    return {
        "schema_version": 2,
        "active_profile": "hermes-home",
        "profile_sources": [source_path],
        "profiles": {"hermes-home": {"name": "hermes", "url": "https://h/mcp"}},
        "mcp_tools": [
            {"name": "Cursor", "config_path": "~/.cursor/mcp.json", "format": "json",
             "mcp_key_path": ["mcpServers"]},
        ],
    }


class EndpointStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "profiles.local.yaml")
        # seed a source file the store can write to
        with open(self.source, "w", encoding="utf-8") as f:
            yaml.safe_dump({"profiles": {}}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def _config(self):
        return _config_with_source(self.source)

    def _read(self):
        with open(self.source, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_add_and_read_back(self):
        cfg = self._config()
        res = add_endpoint(cfg, "ep2", {"name": "ep2", "url": "https://e2/mcp"})
        self.assertEqual(res["status"], "ok")
        data = self._read()
        self.assertEqual(data["profiles"]["ep2"]["url"], "https://e2/mcp")

    def test_add_dry_run_does_not_write(self):
        cfg = self._config()
        res = add_endpoint(cfg, "ep2", {"name": "ep2", "url": "https://e2/mcp"}, dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        data = self._read()
        self.assertNotIn("ep2", data.get("profiles", {}))

    def test_remove_endpoint(self):
        cfg = self._config()
        add_endpoint(cfg, "ep2", {"name": "ep2", "url": "https://e2/mcp"})
        res = remove_endpoint(cfg, "ep2")
        self.assertEqual(res["status"], "ok")
        data = self._read()
        self.assertNotIn("ep2", data.get("profiles", {}))

    def test_update_endpoint_url(self):
        cfg = self._config()
        add_endpoint(cfg, "ep2", {"name": "ep2", "url": "https://e2/mcp"})
        res = update_endpoint(cfg, "ep2", url="https://e2-new/mcp")
        self.assertEqual(res["status"], "ok")
        data = self._read()
        self.assertEqual(data["profiles"]["ep2"]["url"], "https://e2-new/mcp")

    def test_set_attach_persists(self):
        cfg = self._config()
        res = set_client_attach(cfg, "Cursor", ["ep2"])
        self.assertEqual(res["status"], "ok")
        data = self._read()
        self.assertEqual(data["client_mcp_attach"]["Cursor"], ["ep2"])


class AttachOverlayMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "profiles.local.yaml")

    def tearDown(self):
        self.tmp.cleanup()

    def test_client_mcp_attach_applies_to_registry(self):
        with open(self.source, "w", encoding="utf-8") as f:
            yaml.safe_dump({"client_mcp_attach": {"Cursor": ["ep2", "ep3"]}}, f)
        config = _config_with_source(self.source)
        config["profiles"] = {
            "hermes-home": {"name": "hermes", "url": "https://h/mcp"},
            "ep2": {"name": "ep2", "url": "https://e2/mcp"},
            "ep3": {"name": "ep3", "url": "https://e3/mcp"},
        }
        merged = apply_profile_sources(config)
        cursor = merged["mcp_tools"][0]
        self.assertEqual(cursor["mcp_attach"], ["ep2", "ep3"])


if __name__ == "__main__":
    unittest.main()
