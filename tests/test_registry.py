import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from tool_registry import (  # noqa: E402
    detect_installation,
    is_stub_launcher,
    read_app_versions,
    read_cli_versions,
    which_with_fallback,
)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tool = {
            "install": {
                "app_bundles": ["/Applications/Example.app"],
                "commands": ["example"],
                "config_paths": ["~/.example/config.json"],
            },
            "skills_paths": ["~/.example/skills"],
        }

    def test_any_real_install_evidence_is_sufficient(self):
        # app or cli => installed (三态语义: 仅 app/cli 算真正安装)
        for existing, commands, reason in [
            ({"/Applications/Example.app"}, set(), "app"),
            (set(), {"example"}, "cli"),
        ]:
            with self.subTest(reason=reason):
                result = detect_installation(
                    self.tool,
                    path_exists=lambda path: path in existing,
                    command_exists=lambda command: "/usr/local/bin/example" if command in commands else None,
                    expanduser=lambda path: path,
                )
                self.assertTrue(result["installed"])
                self.assertIn(reason, result["evidence"])

    def test_config_only_is_not_installed_but_surfaced(self):
        """config-only => not installed, but install_state=config_only (显示待确认)."""
        result = detect_installation(
            self.tool,
            path_exists=lambda path: path == "~/.example/config.json",
            command_exists=lambda command: None,
            expanduser=lambda path: path,
        )
        self.assertFalse(result["installed"])
        self.assertEqual(result["install_state"], "config_only")
        self.assertEqual(result["evidence"], ["config"])

    def test_nothing_at_all_is_none(self):
        """no app/cli/config => install_state=none (hidden)."""
        result = detect_installation(
            self.tool,
            path_exists=lambda path: False,
            command_exists=lambda command: None,
            expanduser=lambda path: path,
        )
        self.assertFalse(result["installed"])
        self.assertEqual(result["install_state"], "none")
        self.assertEqual(result["evidence"], [])

    def test_resolved_paths_exposed(self):
        """app/cli/config paths are surfaced for display, home-prefix abbreviated to ~."""
        # expanduser 模拟真实展开：~/.example/config.json -> /home/x/.example/config.json
        def expand(path):
            return path.replace("~", "/home/x")

        result = detect_installation(
            self.tool,
            path_exists=lambda path: path in {"/Applications/Example.app", "/home/x/.example/config.json"},
            command_exists=lambda command: "/home/x/.local/bin/example" if command == "example" else None,
            expanduser=expand,
        )
        self.assertEqual(result["app_paths"], ["/Applications/Example.app"])  # 非 home 路径保持原样
        self.assertEqual(result["cli_paths"], ["~/.local/bin/example"])       # home 下 CLI 缩写回 ~
        self.assertEqual(result["config_paths"], ["~/.example/config.json"])  # config 缩写回 ~

    def test_skills_symlink_alone_is_not_installation_evidence(self):
        result = detect_installation(
            self.tool,
            path_exists=lambda path: path == "~/.example/skills",
            command_exists=lambda command: False,
            expanduser=lambda path: path,
        )
        self.assertFalse(result["installed"])
        self.assertEqual(result["evidence"], [])


class CliFallbackTest(unittest.TestCase):
    """GUI 壳（Finder 启动）PATH 受限时，裸名 CLI 仍应被常见 bin 目录兜底命中。

    回归背景：控制台以 /Applications/skill-mcp-studio.app 运行时继承 launchd 的
    最小 PATH，``shutil.which("dsh")`` 查不到 /opt/homebrew/bin/dsh，在用客户端被
    误判成 config_only（「仅配置」）并给出会删配置的清理入口。
    """

    @staticmethod
    def _make_cli(directory: str, name: str) -> str:
        path = os.path.join(directory, name)
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)
        return path

    def test_bare_name_found_in_extra_bin_dir_when_path_misses(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = self._make_cli(tmp, "smp-studio-probe")
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp,)), \
                    mock.patch("tool_registry.shutil.which", return_value=None):
                self.assertEqual(which_with_fallback("smp-studio-probe"), expected)

    def test_path_form_command_is_not_dir_scanned(self):
        """路径形态的命令只认 which 的结果，不参与兜底目录扫描。"""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp,)), \
                    mock.patch("tool_registry.shutil.which", return_value=None):
                self.assertIsNone(which_with_fallback(os.path.join(tmp, "smp-studio-probe")))

    def test_detect_installation_default_uses_fallback(self):
        tool = {"install": {"app_bundles": [], "commands": ["smp-studio-probe"], "config_paths": []}}
        with tempfile.TemporaryDirectory() as tmp:
            self._make_cli(tmp, "smp-studio-probe")
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp,)), \
                    mock.patch("tool_registry.shutil.which", return_value=None):
                result = detect_installation(tool)
        self.assertTrue(result["installed"])
        self.assertEqual(result["install_state"], "installed")
        self.assertEqual(result["evidence"], ["cli"])

    def test_injected_command_exists_still_takes_over(self):
        """注入 command_exists 时不触碰文件系统兜底（测试契约不变）。"""
        tool = {"install": {"app_bundles": [], "commands": ["smp-studio-probe"], "config_paths": []}}
        with tempfile.TemporaryDirectory() as tmp:
            self._make_cli(tmp, "smp-studio-probe")
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp,)):
                result = detect_installation(tool, command_exists=lambda command: None)
        self.assertFalse(result["installed"])
        self.assertEqual(result["install_state"], "none")


class VersionProbeTest(unittest.TestCase):
    def test_read_app_versions_reads_cfbundleshortversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = os.path.join(tmp, "Demo.app")
            contents = os.path.join(app, "Contents")
            os.makedirs(contents)
            with open(os.path.join(contents, "Info.plist"), "wb") as fh:
                plistlib.dump({"CFBundleShortVersionString": "9.8.7"}, fh)
            self.assertEqual(read_app_versions([app]), ["9.8.7"])

    def test_read_app_versions_missing_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "NoSuch.app")
            self.assertEqual(read_app_versions([missing]), [""])

    def test_read_app_versions_expands_tilde(self):
        home = tempfile.mkdtemp()
        app = os.path.join(home, "Demo.app")
        contents = os.path.join(app, "Contents")
        os.makedirs(contents)
        with open(os.path.join(contents, "Info.plist"), "wb") as fh:
            plistlib.dump({"CFBundleShortVersionString": "1.2.3"}, fh)
        tilde_path = "~" + "/Demo.app"
        versions = read_app_versions([tilde_path], expanduser=lambda p: p.replace("~", home))
        self.assertEqual(versions, ["1.2.3"])

    def test_read_cli_versions_uses_python_version(self):
        # Python 自身的 --version 输出稳定（"Python 3.x.y"），用作真实子进程路径。
        versions = read_cli_versions([sys.executable])
        self.assertEqual(len(versions), 1)
        self.assertTrue(versions[0].startswith("Python "))

    def test_read_cli_versions_failure_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            bogus = os.path.join(tmp, "definitely-not-a-binary")
            versions = read_cli_versions([bogus], timeout=0.5)
            self.assertEqual(versions, [""])


class EffectiveToolsTest(unittest.TestCase):
    """effective_tools 三源合并去重 + 本机停用过滤。"""

    def _run(self, config, discovered=()):
        from unittest import mock

        import config_store
        from tool_registry import effective_tools

        with mock.patch.object(config_store, "load_discovered", return_value=list(discovered)):
            return effective_tools(config)

    def test_filters_disabled_tools(self):
        config = {
            "mcp_tools": [{"name": "Claude Code"}, {"name": "WorkBuddy"}],
            "tools": [{"name": "Claude Code", "skills_paths": ["~/.claude/skills"]}],
            "disabled_tools": ["claudecode"],
        }
        names = [t["name"] for t in self._run(config)]
        self.assertEqual(names, ["WorkBuddy"])

    def test_disabled_still_filters_rediscovered(self):
        # 停用客户端即使被 auto_discover 重新扫进 discovered，也仍被剔除
        config = {
            "mcp_tools": [],
            "tools": [],
            "disabled_tools": ["geminicli"],
        }
        discovered = [{"name": "Gemini CLI"}, {"name": "WorkBuddy"}]
        names = [t["name"] for t in self._run(config, discovered=discovered)]
        self.assertEqual(names, ["WorkBuddy"])

    def test_no_disabled_merges_and_dedupes(self):
        config = {
            "mcp_tools": [{"name": "Claude Code", "config_path": "~/.claude.json"}],
            "tools": [{"name": "Claude Code", "skills_paths": ["~/.claude/skills"]}],
        }
        names = [t["name"] for t in self._run(config)]
        self.assertEqual(names, ["Claude Code"])

    def test_field_level_union_preserves_skills_paths(self):
        """A-3: mcp_tools 段只有 MCP 字段、tools 段只有 skills_paths，合并后两者并存。"""
        config = {
            "mcp_tools": [{
                "name": "Claude Code",
                "config_path": "~/.claude.json",
                "format": "json",
                "mcp_key_path": ["mcpServers"],
            }],
            "tools": [{
                "name": "Claude Code",
                "skills_paths": ["~/.claude/skills"],
                "type": "AI Coding Assistant",
            }],
        }
        tools = self._run(config)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["config_path"], "~/.claude.json")
        self.assertEqual(tools[0]["format"], "json")
        self.assertEqual(tools[0]["skills_paths"], ["~/.claude/skills"])
        self.assertEqual(tools[0]["type"], "AI Coding Assistant")

    def test_field_level_union_merges_install_block(self):
        config = {
            "mcp_tools": [{
                "name": "Reasonix",
                "install": {"app_bundles": ["/Applications/Reasonix.app"]},
            }],
            "tools": [{
                "name": "Reasonix",
                "install": {"commands": ["reasonix"]},
                "skills_paths": ["~/.reasonix/skills"],
            }],
        }
        tools = self._run(config)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["install"]["app_bundles"], ["/Applications/Reasonix.app"])
        self.assertEqual(tools[0]["install"]["commands"], ["reasonix"])


class StubLauncherTest(unittest.TestCase):
    """卸载残留的转发型启动器（空壳 CLI）不再被当成安装证据。

    回归背景：Cursor 卸载后 ``~/.local/bin/cursor`` 这个 shim 仍留在磁盘上且带
    可执行位——它自身不实现任何功能，只在 PATH 里找另一个同名的自己并 ``exec``
    过去，找不到就报错退出。旧逻辑仅凭「同名文件存在 + 可执行位」判定
    ``installed``：扫描结果误报「已安装」，修复链路还会把 MCP 端点写进一个已经
    不存在的客户端。
    """

    #: 复刻自 ~/.local/bin/cursor 的实际内容。
    CURSOR_SHIM = """#!/bin/sh
find_cursor() {
  for dir in $PATH; do
    cursor_path="$dir/cursor"
    if [ "$cursor_path" != "$HOME/.local/bin/cursor" ] && [ -x "$cursor_path" ]; then
      echo "$cursor_path"
      return 0
    fi
  done
  return 1
}
OTHER_CURSOR=$(find_cursor || true)
if [ -n "${OTHER_CURSOR:-}" ]; then
  exec "$OTHER_CURSOR" "$@"
else
  echo "Error: No Cursor IDE installation found." 1>&2
  exit 1
fi
"""

    #: VS Code 那类引用 .app bundle 的 Electron 启动器。
    VSCODE_SHIM = """#!/usr/bin/env bash
CONTENTS="/Applications/NoSuch-SkillMcpProbe.app/Contents"
ELECTRON="$CONTENTS/MacOS/Electron"
CLI="$CONTENTS/Resources/app/out/cli.js"
exec "$ELECTRON" "$CLI" "$@"
"""

    #: pip 生成的 console script：包装脚本，但不是「转发型启动器」。
    WRAPPER_SCRIPT = """#!/opt/homebrew/bin/python3.11
import sys
from smp_probe.cli import main
sys.exit(main())
"""

    @staticmethod
    def _write(directory: str, name: str, body: str) -> str:
        path = os.path.join(directory, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        return path

    def test_forwarder_shim_without_target_is_stub(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim = self._write(tmp, "smp-stub-probe", self.CURSOR_SHIM.replace("cursor", "smp-stub-probe"))
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp,)):
                self.assertTrue(is_stub_launcher(shim, "smp-stub-probe"))

    def test_forwarder_shim_with_second_copy_is_not_stub(self):
        """别处还有同名真身时 shim 能正常转发，不算空壳。"""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as real:
            shim = self._write(tmp, "smp-dup-probe", self.CURSOR_SHIM.replace("cursor", "smp-dup-probe"))
            self._write(real, "smp-dup-probe", "#!/bin/sh\nexit 0\n")
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp, real)):
                self.assertFalse(is_stub_launcher(shim, "smp-dup-probe"))

    def test_app_bundle_launcher_with_missing_bundle_is_stub(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim = self._write(tmp, "smp-code-probe", self.VSCODE_SHIM)
            self.assertTrue(is_stub_launcher(shim, "smp-code-probe", path_exists=lambda path: False))

    def test_app_bundle_launcher_with_present_bundle_is_not_stub(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim = self._write(tmp, "smp-code-probe", self.VSCODE_SHIM)
            self.assertFalse(is_stub_launcher(shim, "smp-code-probe", path_exists=lambda path: True))

    def test_native_binary_is_not_stub(self):
        """真身是原生二进制（含 NUL 字节），不做脚本解析，直接放行。"""
        self.assertFalse(is_stub_launcher(sys.executable, "python3"))

    def test_plain_wrapper_script_is_not_stub(self):
        """包装脚本（pip console script）不含「重找同名命令」的转发逻辑，不得误判。"""
        with tempfile.TemporaryDirectory() as tmp:
            script = self._write(tmp, "smp-wrap-probe", self.WRAPPER_SCRIPT)
            self.assertFalse(is_stub_launcher(script, "smp-wrap-probe"))

    def test_unreadable_path_is_not_stub(self):
        """判不出来时保守放行：绝不把未知情况当成「未安装」。"""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(is_stub_launcher(os.path.join(tmp, "no-such-file"), "no-such-file"))

    def test_detect_installation_downgrades_stub_cli_to_config_only(self):
        """端到端：只剩空壳 CLI + 残留配置 => config_only（可清理），而不是 installed。"""
        tool = {
            "install": {
                "app_bundles": [],
                "commands": ["smp-stub-probe"],
                "config_paths": ["~/.smp-stub/config.json"],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            shim = self._write(tmp, "smp-stub-probe", self.CURSOR_SHIM.replace("cursor", "smp-stub-probe"))
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp,)), \
                    mock.patch("tool_registry.shutil.which", return_value=None):
                result = detect_installation(
                    tool,
                    path_exists=lambda path: path == "/home/x/.smp-stub/config.json",
                    expanduser=lambda path: path.replace("~", "/home/x"),
                )
        self.assertFalse(result["installed"])
        self.assertEqual(result["install_state"], "config_only")
        self.assertEqual(result["evidence"], ["cli_stub", "config"])
        self.assertEqual(result["cli_paths"], [])
        self.assertEqual(result["cli_stubs"], [shim])
        self.assertEqual(result["config_paths"], ["~/.smp-stub/config.json"])

    def test_detect_installation_healthy_cli_still_installed(self):
        """健全 CLI 不受影响：evidence 只有 cli，cli_stubs 为空。"""
        tool = {"install": {"app_bundles": [], "commands": ["smp-healthy-probe"], "config_paths": []}}
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "smp-healthy-probe", "#!/bin/sh\nexit 0\n")
            with mock.patch("tool_registry._EXTRA_BIN_DIRS_POSIX", (tmp,)), \
                    mock.patch("tool_registry.shutil.which", return_value=None):
                result = detect_installation(tool)
        self.assertTrue(result["installed"])
        self.assertEqual(result["install_state"], "installed")
        self.assertEqual(result["evidence"], ["cli"])
        self.assertEqual(result["cli_stubs"], [])


if __name__ == "__main__":
    unittest.main()
