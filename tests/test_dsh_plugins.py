"""DSH 插件清单（core/dsh_plugins.py）与「DSH 插件」页的门禁断言。

两个重点：

1. **判定正确**：DSH 的插件真相分散在 `dependencies`（装了什么）、
   `dsh.profile.bundles`（启用清单）、`cordis.patch.yml`（补丁层）三处。只看一处
   会得出「装了=在用」或漏掉「装了没启用」。这里用**真实临时目录**构造这三种
   情形，不 mock 文件系统——mock 掉就等于把要验的判定删了。

2. **绝不回显密钥**：真实 `cordis.patch.yml` 里有明文 `apiKey`（本机实测）。
   构造一个含 `sk-xxx` 的样本，断言整个输出（JSON 与文本两种出口）里都查不到它。
   这条比功能正确性更重要：一个会吐密钥的页面比没有这个页面危险得多。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import dsh_plugins as dsh  # noqa: E402

GUI = ROOT / "gui" / "dashboard.html"

FAKE_KEY = "sk-CANARY-abcdef0123456789"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class _Tree:
    """搭一个含三种插件状态的假 DSH 目录树。"""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="dsh-"))
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()

    def profile(self, name, *, deps, bundles, patch=None, installed=None):
        p = self.profiles / name
        p.mkdir(parents=True, exist_ok=True)
        _write(p / "package.json", json.dumps(
            {"name": f"profile-{name}", "dependencies": deps,
             "dsh": {"profile": {"bundles": bundles}}},
            ensure_ascii=False, indent=2))
        if patch is not None:
            _write(p / "cordis.patch.yml", patch)
        for pkg, version in (installed or {}).items():
            _write(p / "node_modules" / pkg / "package.json",
                   json.dumps({"name": pkg, "version": version}))
        return p

    def cleanup(self):
        subprocess.run(["rm", "-rf", str(self.root)], timeout=30)


class StateClassificationTest(unittest.TestCase):
    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)

    def test_three_states_are_distinguished(self):
        local_src = self.tree.root / "my-plugin"
        local_src.mkdir()
        self.tree.profile(
            "desktop",
            deps={
                "@deepseek-ai/dsh-base": "^1.0.0",
                "plug-enabled": "^1.0.0",
                "plug-installed-only": "^1.0.0",
                "plug-broken": f"link:{self.tree.root / 'gone'}",
                "plug-local": f"link:{local_src}",
            },
            bundles=["@deepseek-ai/dsh-base", "plug-enabled", "plug-broken", "plug-local"],
            installed={"plug-enabled": "1.2.3", "plug-installed-only": "0.1.0",
                       "plug-local": "9.9.9"},
        )
        out = dsh.scan(str(self.tree.profiles))
        by = {p["name"]: p for p in out["profiles"][0]["plugins"]}

        self.assertEqual("enabled", by["plug-enabled"]["state"])
        self.assertEqual("1.2.3", by["plug-enabled"]["version"])
        self.assertEqual("installed", by["plug-installed-only"]["state"],
                         "装了但不在 bundles 里，必须单列而不是算启用")
        self.assertEqual("broken", by["plug-broken"]["state"],
                         "link 目标不存在必须是 broken，不能因为『在 bundles 里』就算启用")
        self.assertEqual("local", by["plug-local"]["kind"])

    def test_builtin_scope_detected(self):
        self.tree.profile("web", deps={"@deepseek-ai/dsh-web-app": "^2.0.0"},
                          bundles=["@deepseek-ai/dsh-web-app"])
        out = dsh.scan(str(self.tree.profiles))
        plug = out["profiles"][0]["plugins"][0]
        self.assertEqual("builtin", plug["kind"])

    def test_link_target_gone_is_broken_even_if_installed(self):
        """link 目标已删除、但 node_modules 里仍有残壳 —— 仍必须判 broken。

        这是最容易被漏的一种：pnpm 的 link 依赖在源码目录被删/挪走之后，
        `node_modules/<name>` 往往还留着（指过去的符号链接或旧副本），于是
        「有 version」这条判据会放行，插件看着是「已启用」而 DSH 载入必失败。
        所以 broken 必须独立判 link 目标存在性，不能只靠 version 缺失兜底。
        """
        p = self.tree.profile(
            "desktop",
            deps={"plug-local": f"link:{self.tree.root / 'gone-dir'}"},
            bundles=["plug-local"],
            installed={"plug-local": "1.0.0"},   # 有版本，故意不给它兜底机会
        )
        self.assertTrue((p / "node_modules" / "plug-local" / "package.json").exists())
        out = dsh.scan(str(self.tree.profiles))
        plug = out["profiles"][0]["plugins"][0]
        self.assertEqual("1.0.0", plug["version"], "前提：版本是读得到的")
        self.assertEqual("broken", plug["state"],
                         "link 目标不存在时，即使有 version 也必须判 broken")

    def test_summary_counts_are_separate_not_merged(self):
        self.tree.profile("p1", deps={"a": "^1", "b": "^2"}, bundles=["a"],
                          installed={"a": "1.0.0", "b": "1.0.0"})
        out = dsh.scan(str(self.tree.profiles))
        s = out["summary"]
        self.assertEqual(2, s["plugins"])
        self.assertEqual(1, s["enabled"])
        self.assertEqual(1, s["installed_only"])
        self.assertEqual(0, s["broken"])

    def test_node_modules_is_not_a_profile(self):
        # profiles/node_modules 是 pnpm 依赖树，不是 profile
        (self.tree.profiles / "node_modules" / "x").mkdir(parents=True)
        self.tree.profile("desktop", deps={}, bundles=[])
        out = dsh.scan(str(self.tree.profiles))
        self.assertEqual(["desktop"], [p["name"] for p in out["profiles"]])
        self.assertEqual(1, out["summary"]["profiles"])

    def test_missing_profiles_dir_reports_reason(self):
        out = dsh.scan(str(self.tree.root / "nope"))
        self.assertEqual([], out["profiles"])
        self.assertIn("未找到 DSH profile 目录", out["reason"])


class PatchStatsTest(unittest.TestCase):
    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)

    def test_patch_structure_counted(self):
        patch = """- id: vision
  config:
    provider: custom
- id: some-plugin
  disabled: true
- insert:
    - id: extra
"""
        self.tree.profile("desktop", deps={}, bundles=[], patch=patch)
        out = dsh.scan(str(self.tree.profiles))
        p = out["profiles"][0]["patch"]
        self.assertTrue(p["exists"])
        self.assertEqual(3, p["entries"])
        self.assertEqual(1, p["disables"])
        self.assertEqual(1, p["inserts"])

    def test_missing_patch_reported_as_absent(self):
        self.tree.profile("desktop", deps={}, bundles=[])
        out = dsh.scan(str(self.tree.profiles))
        self.assertFalse(out["profiles"][0]["patch"]["exists"])


class SecretsNeverLeakTest(unittest.TestCase):
    """最要紧的一条：patch 层的 config 值绝不回显。"""

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)
        patch = f"""- id: vision
  config:
    provider: custom
    apiKey: {FAKE_KEY}
    baseURL: https://example.invalid/v1
"""
        self.tree.profile("desktop", deps={"dsh-plugin-vision": "^0.1.0"},
                          bundles=["dsh-plugin-vision"], patch=patch,
                          installed={"dsh-plugin-vision": "0.1.0"})

    def test_scan_output_has_no_secret(self):
        out = dsh.scan(str(self.tree.profiles))
        blob = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(FAKE_KEY, blob)
        self.assertNotIn("sk-", blob, "输出里连 sk- 前缀都不该出现")
        self.assertNotIn("example.invalid", blob, "baseURL 这类 config 值同样不该出现")
        self.assertTrue(out["secrets_redacted"])

    def test_text_output_has_no_secret(self):
        out = dsh.scan(str(self.tree.profiles))
        env = dict(os.environ, PYTHONPATH=str(ROOT / "core"))
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), "--dsh-plugins",
             "--dsh-home", str(self.tree.root)],
            capture_output=True, text=True, env=env, timeout=120, cwd=str(ROOT))
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertNotIn(FAKE_KEY, proc.stdout)
        self.assertNotIn("sk-", proc.stdout)
        self.assertIn("脱敏", proc.stdout)
        self.assertIsNotNone(out)


class DshPageGuiTest(unittest.TestCase):
    """GUI 侧：新页必须真的接进来，而不是只有一段死代码。"""

    @classmethod
    def setUpClass(cls):
        cls.body = GUI.read_text(encoding="utf-8")

    def test_nav_item_and_section_exist(self):
        self.assertIn('data-page="dsh"', self.body)
        self.assertIn('id="page-dsh"', self.body)
        self.assertIn('id="nav-dsh"', self.body)

    def test_page_registered_in_pages_map(self):
        self.assertIn('dsh: "page-dsh"', self.body)

    def test_cli_is_called_with_json(self):
        self.assertIn('"--dsh-plugins", "--format", "json"', self.body)

    def test_three_states_rendered_separately(self):
        for state in ("enabled", "installed", "broken"):
            self.assertIn(f"{state}:", self.body, f"缺少 {state} 状态映射")
        self.assertIn("装了未启用", self.body)
        self.assertIn("来源失效", self.body)

    def test_page_does_not_render_config_values(self):
        # 页面只能显示 patch 的结构统计，不得渲染 config 内容
        self.assertIn('patch 值已脱敏', self.body)
        self.assertNotIn(".config", self.body.split("function renderDshPlugins")[1][:4000],
                         "渲染函数里不应触碰 config 字段（可能含密钥）")

    def test_auto_load_on_page_switch(self):
        self.assertIn('if (page === "dsh" && !DSH_DATA) loadDshPlugins();', self.body)

    def test_rust_allowlist_contains_flag(self):
        lib = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertIn('"--dsh-plugins"', lib,
                      "不在 Rust 白名单里，GUI 调用会被安全边界拦下")


if __name__ == "__main__":
    unittest.main()
