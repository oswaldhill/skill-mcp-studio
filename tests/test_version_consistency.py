"""版本单源真相一致性（B-1/D-1/A-9 回归护栏）。

断言 version.json 的 version/build 与打包元数据（pyproject.toml / Cargo.toml /
tauri.conf.json）以及对外文档（README 徽章 / CHANGELOG 顶部）完全一致。若某处
漂移（历史教训: pyproject 0.1.0 vs version.json 0.20.0、README 徽章 build-103
vs build 104），本测试立即失败，防止 bump_version 漏同步。
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_version() -> dict:
    data = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    return {"version": data["version"], "build": int(data["build"])}


class VersionConsistencyTest(unittest.TestCase):
    def setUp(self):
        self.v = _load_version()

    def test_pyproject_version_matches(self):
        txt = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', txt, re.MULTILINE)
        self.assertIsNotNone(m, "pyproject.toml 缺少 [project].version")
        self.assertEqual(m.group(1), self.v["version"],
                         "pyproject.toml version 与 version.json 漂移")

    def test_cargo_version_matches(self):
        txt = (ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', txt, re.MULTILINE)
        self.assertIsNotNone(m, "Cargo.toml 缺少 version")
        self.assertEqual(m.group(1), self.v["version"])

    def test_tauri_conf_version_matches(self):
        txt = (ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
        m = re.search(r'"version"\s*:\s*"([^"]+)"', txt)
        self.assertIsNotNone(m, "tauri.conf.json 缺少 version")
        self.assertEqual(m.group(1), self.v["version"])

    def test_readme_badges_match(self):
        txt = (ROOT / "README.md").read_text(encoding="utf-8")
        v = re.search(r'version-v([0-9]+\.[0-9]+\.[0-9]+)', txt)
        b = re.search(r'build-([0-9]+)', txt)
        self.assertIsNotNone(v, "README 缺少 version 徽章")
        self.assertIsNotNone(b, "README 缺少 build 徽章")
        self.assertEqual(v.group(1), self.v["version"], "README 徽章 version 漂移")
        self.assertEqual(int(b.group(1)), self.v["build"], "README 徽章 build 漂移")

    def test_changelog_header_matches(self):
        txt = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        v = re.search(r'## \[v([0-9]+\.[0-9]+\.[0-9]+)\]', txt)
        b = re.search(r'当前发布版本（build (\d+)）', txt)
        self.assertIsNotNone(v, "CHANGELOG 缺少版本标题")
        self.assertIsNotNone(b, "CHANGELOG 缺少 build 标注")
        self.assertEqual(v.group(1), self.v["version"], "CHANGELOG 版本漂移")
        self.assertEqual(int(b.group(1)), self.v["build"], "CHANGELOG build 漂移")


if __name__ == "__main__":
    unittest.main()
