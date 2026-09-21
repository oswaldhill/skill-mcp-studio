"""Stage-5 P7: config write store (unified dir + discovered client)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import yaml  # noqa: E402

from config_store import add_discovered_client, set_unified_dir  # noqa: E402


class SetUnifiedDirTest(unittest.TestCase):
    """B3 fix: set_unified_dir writes a gitignored overlay, never trunk config.yaml."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.yaml")
        # trunk config with personal topology deliberately absent (default only)
        self.content = (
            "schema_version: 1\n"
            "active_profile: generic-http\n"
            "# trunk stays free of personal topology\n"
            "unified_skills_dir: ~/.skills-manager/skills\n"
            "profile_sources: []\n"
        )
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(self.content)
        # patch _local_overrides_file + _overlay_target to land under tmp
        import config_store

        self.mod = config_store
        self.local = os.path.join(self.tmp.name, "data", "local_overrides.yaml")
        # 记录原函数：_local_overrides_file / _overlay_target 都是模块级函数，
        # 不还原会污染同进程内的后续用例（OverlayRegistrationTest 会继承到本
        # 用例已 cleanup 的临时目录，导致「单独运行通过、按文件或全量运行失败」）。
        self._orig_local_overrides = config_store._local_overrides_file
        self._orig_overlay_target = config_store._overlay_target
        self.mod._local_overrides_file = lambda: self.local
        self.mod._overlay_target = lambda cfg_path: self.local

    def tearDown(self):
        self.mod._local_overrides_file = self._orig_local_overrides
        self.mod._overlay_target = self._orig_overlay_target
        self.tmp.cleanup()

    def _read_trunk(self):
        with open(self.cfg, encoding="utf-8") as f:
            return f.read()

    def _read_overlay(self):
        with open(self.local, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def test_writes_overlay_not_trunk(self):
        res = set_unified_dir("~/.foo/skills", config_path=self.cfg)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(self._read_overlay().get("unified_skills_dir"), "~/.foo/skills")
        # trunk config.yaml must be untouched (no personal path written in)
        self.assertNotIn("~/.foo/skills", self._read_trunk())
        self.assertIn("# trunk stays free of personal topology", self._read_trunk())

    def test_dry_run_does_not_write(self):
        res = set_unified_dir("~/.foo/skills", config_path=self.cfg, dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertFalse(os.path.isfile(self.local))

    def test_unchanged_status(self):
        set_unified_dir("~/.foo/skills", config_path=self.cfg)
        res = set_unified_dir("~/.foo/skills", config_path=self.cfg)
        self.assertEqual(res["status"], "unchanged")

    def test_overlay_value_overrides_trunk_default(self):
        """apply_profile_sources must merge unified_skills_dir from overlay."""
        set_unified_dir("~/.bar/skills", config_path=self.cfg)
        from profile_loader import apply_profile_sources

        config = yaml.safe_load(self._read_trunk())
        config["profile_sources"] = [self.local]
        merged = apply_profile_sources(config)
        self.assertEqual(merged["unified_skills_dir"], "~/.bar/skills")


class AddDiscoveredClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # patch DISCOVERED_FILE via module-level import path
        self.orig = os.environ.get("DISCOVERED_FILE")
        import config_store

        self.cfg_store_mod = config_store
        self.disc = os.path.join(self.tmp.name, "discovered_tools.yaml")
        config_store._discovered_file = lambda: self.disc

    def tearDown(self):
        self.tmp.cleanup()

    def _read(self):
        with open(self.disc, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_add_new_client(self):
        res = add_discovered_client("FooAgent", skills_path="~/.foo/skills", client_type="AI Agent")
        self.assertEqual(res["status"], "ok")
        data = self._read()
        self.assertEqual(data[0]["name"], "FooAgent")
        self.assertEqual(data[0]["skills_paths"], ["~/.foo/skills"])
        self.assertFalse(data[0]["auto_discovered"])

    def test_dedup_by_normalized_name(self):
        add_discovered_client("FooAgent")
        res = add_discovered_client("fooagent")
        self.assertEqual(res["status"], "unchanged")

    def test_dry_run(self):
        res = add_discovered_client("BarAgent", dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertFalse(os.path.isfile(self.disc))

    def test_feat1_add_client_with_mcp_fields(self):
        """FEAT-1: add a full MCP-capable client (config_path/format/mcp_key_path/attach)."""
        res = add_discovered_client(
            "McpAgent",
            skills_path="~/.mcpa/skills",
            config_path="~/.mcpa/mcp.json",
            mcp_format="json",
            mcp_key_path="mcpServers",
            mcp_attach=["hermes-home"],
        )
        self.assertEqual(res["status"], "ok")
        data = self._read()
        entry = next(d for d in data if d["name"] == "McpAgent")
        self.assertEqual(entry["config_path"], "~/.mcpa/mcp.json")
        self.assertEqual(entry["format"], "json")
        self.assertEqual(entry["mcp_key_path"], ["mcpServers"])
        self.assertEqual(entry["mcp_attach"], ["hermes-home"])

    def test_add_client_with_install_block(self):
        """整改: --add-client 支持 install 检测块 + aliases 持久化."""
        res = add_discovered_client(
            "CustomAgent",
            client_type="AI Agent",
            install={"app_bundles": ["/Applications/Custom.app"], "commands": ["custom"], "config_paths": ["~/.custom/mcp.json"]},
            aliases=["custom-agent", "ca"],
        )
        self.assertEqual(res["status"], "ok")
        data = self._read()
        entry = next(d for d in data if d["name"] == "CustomAgent")
        self.assertEqual(entry["install"]["app_bundles"], ["/Applications/Custom.app"])
        self.assertEqual(entry["install"]["commands"], ["custom"])
        self.assertEqual(entry["aliases"], ["custom-agent", "ca"])


class AddDefaultClientsTest(unittest.TestCase):
    """整改: add_default_clients 一键默认添加主流 IDE/Agent."""

    def setUp(self):
        import config_store

        self.tmp = tempfile.TemporaryDirectory()
        self.disc = os.path.join(self.tmp.name, "discovered_tools.yaml")
        self._orig = config_store._discovered_file
        config_store._discovered_file = lambda: self.disc

    def tearDown(self):
        import config_store

        config_store._discovered_file = self._orig
        self.tmp.cleanup()

    def test_defaults_merge_dedup_and_include_deepseek(self):
        from config_store import add_default_clients
        from mainstream_registry import MAINSTREAM_TOOLS

        r1 = add_default_clients()
        self.assertEqual(r1["added"], len(MAINSTREAM_TOOLS))

        # 二次调用全部 unchanged（去重）
        r2 = add_default_clients()
        self.assertEqual(r2["added"], 0)
        self.assertEqual(r2["unchanged"], len(MAINSTREAM_TOOLS))

        data = yaml.safe_load(Path(self.disc).read_text(encoding="utf-8"))
        names = {d["name"] for d in data}
        # DeepSeek Harness（原 DSH）必须在主流清单中
        self.assertIn("DeepSeek Harness", names)
        dsh = next(d for d in data if d["name"] == "DeepSeek Harness")
        self.assertIn("install", dsh)
        self.assertIn("dsh", dsh.get("aliases", []))

    def test_defaults_dry_run_does_not_write(self):
        from config_store import add_default_clients

        r = add_default_clients(dry_run=True)
        self.assertEqual(r["added"], len(r["results"]))
        self.assertFalse(os.path.isfile(self.disc))


class RemoveDiscoveredClientTest(unittest.TestCase):
    """整改: remove_discovered_client 仅动 discovered 持久化，归一化名去重移除."""

    def setUp(self):
        import config_store

        self.tmp = tempfile.TemporaryDirectory()
        self.disc = os.path.join(self.tmp.name, "discovered_tools.yaml")
        self._orig = config_store._discovered_file
        config_store._discovered_file = lambda: self.disc
        add_discovered_client("Foo Agent", client_type="AI Agent")

    def tearDown(self):
        import config_store

        config_store._discovered_file = self._orig
        self.tmp.cleanup()

    def test_remove_by_normalized_name(self):
        from config_store import remove_discovered_client

        r = remove_discovered_client("foo-agent")
        self.assertEqual(r["status"], "ok")
        data = yaml.safe_load(Path(self.disc).read_text(encoding="utf-8"))
        self.assertEqual(data, [])

    def test_remove_missing_is_unchanged(self):
        from config_store import remove_discovered_client

        r = remove_discovered_client("nope")
        self.assertEqual(r["status"], "unchanged")

    def test_remove_dry_run_does_not_write(self):
        from config_store import remove_discovered_client

        r = remove_discovered_client("Foo Agent", dry_run=True)
        self.assertEqual(r["status"], "dry-run")
        data = yaml.safe_load(Path(self.disc).read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)


class CleanupConfigOnlyClientTest(unittest.TestCase):
    """整改: cleanup_config_only_client 清理 config_only 客户端残留配置文件（带备份）。"""

    def setUp(self):
        import config_store
        import tool_registry

        self.tmp = tempfile.TemporaryDirectory()
        # 真实存在的配置文件（绝对路径，绕过 expanduser 差异）
        self.conf_s = os.path.join(self.tmp.name, "settings.json")
        self.conf_m = os.path.join(self.tmp.name, "mcp.json")
        with open(self.conf_s, "w", encoding="utf-8") as f:
            f.write("{}\n")
        with open(self.conf_m, "w", encoding="utf-8") as f:
            f.write("{}\n")

        # patch discovered 为不存在 → effective_tools 只读 config 的 tools，隔离真实磁盘
        self.disc = os.path.join(self.tmp.name, "discovered.yaml")
        self._orig_disc = config_store._discovered_file
        config_store._discovered_file = lambda: self.disc

        # patch detect_installation：默认 config_only
        self._orig_detect = tool_registry.detect_installation

        def fake_detect(tool, **kwargs):
            return {
                "installed": False,
                "install_state": "config_only",
                "app_paths": [],
                "cli_paths": [],
                "config_paths": [self.conf_s],
            }

        self.fake_detect = fake_detect
        tool_registry.detect_installation = fake_detect

        self.config = {
            "mcp_tools": [],
            "tools": [
                {"name": "Foo Agent", "config_path": self.conf_m,
                 "install": {"config_paths": [self.conf_s]}},
            ],
        }

    def tearDown(self):
        import config_store
        import tool_registry

        tool_registry.detect_installation = self._orig_detect
        config_store._discovered_file = self._orig_disc
        self.tmp.cleanup()

    def test_ok_deletes_and_backs_up(self):
        from config_store import cleanup_config_only_client

        res = cleanup_config_only_client(self.config, "Foo Agent")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(res["files"]), 2)
        self.assertFalse(os.path.exists(self.conf_s))
        self.assertFalse(os.path.exists(self.conf_m))
        # 备份文件以 .bak- 前缀落地
        backup = res["backup"]
        self.assertTrue(backup)
        self.assertEqual(len(backup.split(", ")), 2)

    def test_dry_run_does_not_delete(self):
        from config_store import cleanup_config_only_client

        res = cleanup_config_only_client(self.config, "foo-agent", dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertTrue(os.path.exists(self.conf_s))
        self.assertTrue(os.path.exists(self.conf_m))

    def test_skip_if_installed(self):
        import tool_registry

        def fake_installed(tool, **kwargs):
            return {"installed": True, "install_state": "installed",
                    "app_paths": ["/Applications/Foo.app"], "cli_paths": [],
                    "config_paths": [self.conf_s]}

        tool_registry.detect_installation = fake_installed
        from config_store import cleanup_config_only_client

        res = cleanup_config_only_client(self.config, "Foo Agent")
        self.assertEqual(res["status"], "skip")
        self.assertTrue(os.path.exists(self.conf_s))

    def test_missing_client_error(self):
        from config_store import cleanup_config_only_client

        res = cleanup_config_only_client(self.config, "Nope")
        self.assertEqual(res["status"], "error")


class RemoveManagedClientTest(unittest.TestCase):
    """整改: remove_managed_client 移除（本机停用 + discovered 条目 + 残留配置 + skills 链接），不删 trunk。"""

    def setUp(self):
        import config_store
        import tool_registry

        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.yaml")
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(
                "mcp_tools:\n"
                "- name: Hermes Agent\n"
                "  config_path: ~/.hermes/config.yaml\n"
                "tools:\n"
                "- backup_suffix: .bak\n"
                "  name: Hermes Agent\n"
                "  skills_paths:\n"
                "  - ~/.agents/skills\n"
                "  type: AI Agent\n"
                "unified_skills_dir: ~/.skills-manager/skills\n"
            )
        self.disc = os.path.join(self.tmp.name, "discovered.yaml")
        with open(self.disc, "w", encoding="utf-8") as f:
            f.write("- name: Gemini CLI\n  type: AI Agent\n")
        self.conf = os.path.join(self.tmp.name, "settings.json")
        with open(self.conf, "w", encoding="utf-8") as f:
            f.write("{}\n")
        self.overlay = os.path.join(self.tmp.name, "overlay.yaml")

        self.mod = config_store
        self.tool_registry = tool_registry
        self._orig_disc = config_store._discovered_file
        self._orig_cfg = config_store._default_config_path
        self._orig_overlay = config_store._overlay_target
        self._orig_detect = tool_registry.detect_installation
        config_store._discovered_file = lambda: self.disc
        config_store._default_config_path = lambda: self.cfg
        config_store._overlay_target = lambda cfg: self.overlay
        tool_registry.detect_installation = self._fake_detect

    def _fake_detect(self, tool, **kwargs):
        return {
            "installed": False,
            "install_state": "config_only",
            "app_paths": [],
            "cli_paths": [],
            "config_paths": [self.conf],
        }

    def tearDown(self):
        self.mod._discovered_file = self._orig_disc
        self.mod._default_config_path = self._orig_cfg
        self.mod._overlay_target = self._orig_overlay
        self.tool_registry.detect_installation = self._orig_detect
        self.tmp.cleanup()

    def test_skip_if_installed(self):
        self.tool_registry.detect_installation = lambda tool, **kw: {
            "installed": True, "install_state": "installed",
            "app_paths": ["/Applications/X.app"], "cli_paths": [], "config_paths": [],
        }
        from config_store import remove_managed_client

        config = {"tools": [{"name": "Hermes Agent"}], "mcp_tools": []}
        res = remove_managed_client(config, "Hermes Agent")
        self.assertEqual(res["status"], "skip")
        self.assertIn("Hermes Agent", Path(self.cfg).read_text(encoding="utf-8"))

    def test_disables_in_overlay_keeps_trunk_and_removes_config(self):
        from config_store import remove_managed_client

        config = {
            "tools": [{"name": "Hermes Agent", "config_path": self.conf,
                       "install": {"config_paths": [self.conf]}}],
            "mcp_tools": [],
        }
        res = remove_managed_client(config, "Hermes Agent")
        self.assertEqual(res["status"], "ok")
        self.assertFalse(os.path.exists(self.conf))
        # trunk 注册表保留（不再删 trunk 条目）
        self.assertIn("Hermes Agent", Path(self.cfg).read_text(encoding="utf-8"))
        # 停用标记写进 overlay
        overlay = yaml.safe_load(Path(self.overlay).read_text(encoding="utf-8"))
        self.assertIn("Hermes Agent", overlay.get("disabled_tools", []))
        # steps 里应有 disable 步骤（不再是 trunk 步骤）
        steps = {s["step"]: s for s in res["steps"]}
        self.assertIn("disable", steps)
        self.assertNotIn("trunk", steps)

    def test_removes_skills_symlink_only(self):
        from config_store import remove_managed_client

        target_dir = os.path.join(self.tmp.name, "real_skills")
        os.makedirs(target_dir)
        link = os.path.join(self.tmp.name, "hermes_skills")
        os.symlink(target_dir, link)
        real = os.path.join(self.tmp.name, "real_dir")
        os.makedirs(real)

        config = {
            "tools": [{"name": "Hermes Agent", "skills_paths": [link, real]}],
            "mcp_tools": [],
        }
        res = remove_managed_client(config, "Hermes Agent")
        self.assertEqual(res["status"], "ok")
        self.assertFalse(os.path.islink(link))
        self.assertTrue(os.path.isdir(real))
        self.assertTrue(os.path.isdir(target_dir))

    def test_merges_skills_paths_across_sections(self):
        from config_store import remove_managed_client

        # mcp_tools 段 Hermes（无 skills_paths）+ tools 段 Hermes（有 skills 链接）
        target_dir = os.path.join(self.tmp.name, "real_skills")
        os.makedirs(target_dir)
        link = os.path.join(self.tmp.name, "tools_skills")
        os.symlink(target_dir, link)

        config = {
            "mcp_tools": [{"name": "Hermes Agent", "config_path": self.conf}],
            "tools": [{"name": "Hermes Agent", "skills_paths": [link]}],
        }
        res = remove_managed_client(config, "Hermes Agent")
        self.assertEqual(res["status"], "ok")
        self.assertFalse(os.path.islink(link))

    def test_removes_discovered_client(self):
        from config_store import remove_managed_client

        config = {"tools": [], "mcp_tools": []}
        res = remove_managed_client(config, "Gemini CLI")
        self.assertEqual(res["status"], "ok")
        with open(self.disc, encoding="utf-8") as fh:
            self.assertEqual(yaml.safe_load(fh), [])
        self.assertIn("Hermes Agent", Path(self.cfg).read_text(encoding="utf-8"))


class OverlayRegistrationTest(unittest.TestCase):
    """回归：_overlay_target 复用第一个已存在的 profile_source；块式 profile_sources
    追加时不产生重复键（否则 YAML 后者覆盖前者，导致真实端点 profiles 丢失）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.yaml")
        # 块式写法（真实 config.yaml 顶部就是这种写法）
        self.content = (
            "schema_version: 1\n"
            "active_profile: generic-http\n"
            "profile_sources:\n"
            "- ~/.skills-manager/profiles.local.yaml\n"
            "profiles:\n"
            "  generic-http:\n"
            "    name: my-mcp\n"
            "    url: https://example.internal/mcp\n"
        )
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(self.content)
        import config_store

        self.mod = config_store
        self._orig_local_overrides = config_store._local_overrides_file
        self.local = os.path.join(self.tmp.name, "data", "local_overrides.yaml")
        config_store._local_overrides_file = lambda: self.local

    def tearDown(self):
        self.mod._local_overrides_file = self._orig_local_overrides
        self.tmp.cleanup()

    def _read_trunk(self):
        with open(self.cfg, encoding="utf-8") as f:
            return f.read()

    def test_overlay_target_reuses_first_existing_profiles_local(self):
        """Bug 1：_overlay_target 曾 import 不存在的 profile_loader.load_config，
        吞异常后退化为空 config，永远 fallback 到 local_overrides.yaml。修复后
        应直接解析 profile_sources，复用第一个存在的文件。"""
        # 创建第一个 profile_source 指向的文件
        first = os.path.join(self.tmp.name, "profiles.local.yaml")
        with open(first, "w", encoding="utf-8") as f:
            f.write("profiles: {}\n")
        # 把 config.yaml 里的 profile_sources 改为绝对路径（第一个存在）
        content = (
            "profile_sources:\n"
            f"- {first}\n"
            f"- {self.local}\n"
        )
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(content)
        self.assertEqual(self.mod._overlay_target(self.cfg), first)

    def test_ensure_overlay_registered_block_style_appends_item(self):
        """Bug 2：块式 profile_sources 追加 overlay 时应作为列表项追加，不能用
        重复键覆盖（YAML 重复键会造成 profiles.local.yaml 丢失）。"""
        self.mod._ensure_overlay_registered(self.cfg, self.local)
        text = self._read_trunk()
        # 只应有一个 profile_sources 键，且以块式保留 profiles.local.yaml
        self.assertEqual(text.count("profile_sources:"), 1)
        self.assertIn("- ~/.skills-manager/profiles.local.yaml", text)
        self.assertIn(f"- {os.path.relpath(self.local, self.tmp.name)}", text)
        # 重新解析后 profiles.local.yaml 仍在 profile_sources 列表里
        parsed = yaml.safe_load(text)
        sources = parsed["profile_sources"]
        self.assertIn("~/.skills-manager/profiles.local.yaml", sources)
        self.assertIn(os.path.relpath(self.local, self.tmp.name), sources)

    def test_ensure_overlay_registered_flow_style_still_works(self):
        """流式写法 profile_sources: [a] 仍应原地追加，不退化。"""
        content = (
            "profile_sources: ['~/.skills-manager/profiles.local.yaml']\n"
        )
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(content)
        self.mod._ensure_overlay_registered(self.cfg, self.local)
        text = self._read_trunk()
        self.assertEqual(text.count("profile_sources:"), 1)
        self.assertIn("~/.skills-manager/profiles.local.yaml", text)
        self.assertIn(os.path.relpath(self.local, self.tmp.name), text)


if __name__ == "__main__":
    unittest.main()
