"""整改: app_info 版本单源真相 + bump_version 语义化/数字构建号."""

import json
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))

import app_info  # noqa: E402


class ReadAppInfoTest(unittest.TestCase):
    def test_returns_both_formats(self):
        info = app_info.read_app_info()
        # X.Y.Z 三段
        parts = str(info["version"]).split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))
        self.assertTrue(info["semver_ok"])
        # 数字构建号，monotonic >= 1
        self.assertGreaterEqual(int(info["build"]), 1)
        self.assertEqual(int(info["build_number"]), int(info["build"]))
        self.assertIn("build", info["full"])

    def test_missing_file_falls_back_to_git_count(self):
        from unittest.mock import patch

        with patch.object(app_info, "_VERSION_PATH", "/nonexistent/version.json"):
            info = app_info.read_app_info()
        self.assertGreaterEqual(int(info["build"]), 0)

    def test_invalid_semver_flagged(self):
        import importlib

        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        tmp.write(json.dumps({"version": "1.2", "build": 5}))
        tmp.close()
        try:
            from unittest.mock import patch

            with patch.object(app_info, "_VERSION_PATH", tmp.name):
                info = app_info.read_app_info()
            self.assertFalse(info["semver_ok"])
            self.assertEqual(int(info["build"]), 5)
        finally:
            os.unlink(tmp.name)


class BumpSemverTest(unittest.TestCase):
    def _import(self):
        spec = importlib.util.spec_from_file_location(
            "bump_version", str(ROOT / "scripts" / "bump_version.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_patch_minor_major(self):
        import importlib.util

        mod = self._import()
        self.assertEqual(mod.bump_semver("0.2.0", "patch"), "0.2.1")
        self.assertEqual(mod.bump_semver("0.2.1", "minor"), "0.3.0")
        self.assertEqual(mod.bump_semver("0.3.0", "major"), "1.0.0")

    def test_build_always_increments(self):
        mod = self._import()
        cur = {"version": "1.2.3", "build": 41}
        new_version = mod.bump_semver(cur["version"], "patch")
        new_build = cur["build"] + 1
        self.assertEqual(new_version, "1.2.4")
        self.assertEqual(new_build, 42)


if __name__ == "__main__":
    unittest.main()