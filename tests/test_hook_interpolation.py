"""Hook 命令变量插值契约（v0.30.0，设计 2026-10-21 §3.1）。

## 背景

v0.29.0 设计 §4.1 与 PRD §6.4 承诺「变量插值 ``{event}`` / ``{agent}`` /
``{server_url}``」，但 ``hooks_fixer`` 此前把 template 命令**原样**写入客户端
配置——用户应用「日志记录」预设（``echo {event} triggered``）后，客户端执行
的是字面 ``{event}``（不是任何客户端的 hook 变量语法），等于坏命令。

v0.30.0 在 ``fix_hooks_tool`` 的 template 构建处补齐写入时插值。本文件守住：

- 三变量取值口径（canonical snake_case / agent_slug 回退 / 活动 profile url）；
- 未识别占位符与无占位符命令 **no-op**（旧命令零影响）；
- ``{server_url}`` 取不到时保留占位符原样（不吞）；
- dry-run 消息附插值样例。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from hooks_fixer import (  # noqa: E402
    _active_server_url,
    _canonical_to_snake,
    _client_agent_slug,
    _interpolate,
    fix_hooks_tool,
)


def _config(hook_events, *, agent_slug=None, profiles=None, active=None) -> dict:
    """最小 config：一个 pascal 客户端 + 可选 agent_slug / profiles。"""
    client: dict = {
        "name": "PascalCli",
        "config_path": "",           # 由各用例替换
        "format": "json",
        "hook_key_path": ["hooks"],
        "event_format": "pascal_case",
        "events": ["SessionStart", "Stop"],
        "fix_supported": True,
        "template": {"SessionStart": "echo {event} triggered >> ~/.hook.log"},
    }
    if agent_slug is not None:
        client["agent_slug"] = agent_slug
    config = {
        "settings": {"hook_events": hook_events},
        "hooks": {"clients": [client]},
    }
    if profiles is not None:
        config["profiles"] = profiles
    if active is not None:
        config["active_profile"] = active
    return config


class InterpolateUnitTest(unittest.TestCase):
    """``_interpolate`` 纯函数契约。"""

    def test_three_variables(self):
        cmd = _interpolate(
            "echo {event} by {agent} to {server_url}",
            canonical="SessionStart",
            agent_slug="claude-code",
            server_url="https://gw.internal/mcp",
        )
        self.assertEqual(cmd, "echo session_start by claude-code to https://gw.internal/mcp")

    def test_unknown_placeholder_and_shell_var_untouched(self):
        """未识别 ``{xxx}`` / ``${VAR}`` 保留原样（不误伤 shell 语法）。"""
        cmd = _interpolate(
            "run ${HOME}/{xxx} {event}",
            canonical="Setup",
            agent_slug="a",
            server_url="u",
        )
        self.assertEqual(cmd, "run ${HOME}/{xxx} setup")

    def test_no_placeholder_is_noop(self):
        self.assertEqual(
            _interpolate("plain command", canonical="Setup", agent_slug="a", server_url="u"),
            "plain command",
        )

    def test_empty_agent_keeps_placeholder(self):
        cmd = _interpolate("{agent} {event}", canonical="Stop", agent_slug="", server_url="")
        self.assertEqual(cmd, "{agent} stop")

    def test_empty_command_passthrough(self):
        self.assertEqual(_interpolate("", canonical="Stop", agent_slug="a", server_url="u"), "")

    def test_snake_conversion(self):
        self.assertEqual(_canonical_to_snake("SessionStart"), "session_start")
        self.assertEqual(_canonical_to_snake("UserPromptSubmit"), "user_prompt_submit")
        self.assertEqual(_canonical_to_snake("Stop"), "stop")


class VariableSourceTest(unittest.TestCase):
    """``{agent}`` / ``{server_url}`` 的取值与回退。"""

    def test_agent_slug_declared_wins(self):
        hc = {"agent_slug": "claude-code"}
        self.assertEqual(_client_agent_slug(hc, "Claude Code"), "claude-code")

    def test_agent_slug_fallback_sluggifies_name(self):
        """未声明 agent_slug → 客户端名 slug 化（WorkBuddy → workbuddy）。"""
        self.assertEqual(_client_agent_slug({}, "WorkBuddy"), "workbuddy")
        self.assertEqual(_client_agent_slug({"agent_slug": "  "}, "Some Tool"), "some-tool")

    def test_active_server_url_resolves(self):
        config = {"profiles": {"k8s": {"url": "https://a/mcp"}}, "active_profile": "k8s"}
        self.assertEqual(_active_server_url(config), "https://a/mcp")

    def test_active_server_url_missing_cases_return_empty(self):
        self.assertEqual(_active_server_url({}), "")
        self.assertEqual(_active_server_url({"profiles": {"k": {}}}), "")
        self.assertEqual(_active_server_url({"profiles": {"k": {"url": "x"}}}), "")  # 无 active
        self.assertEqual(_active_server_url({"active_profile": "k"}), "")           # 无 profiles


class FixHooksInterpolationTest(unittest.TestCase):
    """端到端：``fix_hooks_tool`` 写入的命令是插值后的。"""

    def test_written_command_is_interpolated(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = str(path)
            config["hooks"]["clients"][0]["agent_slug"] = "claude-code"
            config["profiles"] = {"k8s": {"url": "https://gw/mcp"}}
            config["active_profile"] = "k8s"

            result = fix_hooks_tool({"name": "PascalCli"}, config)

            self.assertEqual(result["status"], "updated")
            entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
            command = entry[0]["hooks"][0]["command"]
            self.assertEqual(command, "echo session_start triggered >> ~/.hook.log")

    def test_server_url_placeholder_kept_when_no_active_profile(self):
        """无活动 profile → ``{server_url}`` 保留原样（写入后可见，不吞）。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = str(path)
            config["hooks"]["clients"][0]["template"] = {
                "SessionStart": "curl {server_url}/hook -d {event}"
            }

            fix_hooks_tool({"name": "PascalCli"}, config)

            entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
            command = entry[0]["hooks"][0]["command"]
            self.assertEqual(command, "curl {server_url}/hook -d session_start")

    def test_agent_fallback_used_when_undeclared(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = str(path)
            config["hooks"]["clients"][0]["name"] = "Work Buddy"
            config["hooks"]["clients"][0]["template"] = {
                "SessionStart": "notify {agent} {event}"
            }

            fix_hooks_tool({"name": "Work Buddy"}, config)

            entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
            self.assertEqual(entry[0]["hooks"][0]["command"], "notify work-buddy session_start")

    def test_dry_run_message_contains_interpolated_sample(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = str(path)

            result = fix_hooks_tool({"name": "PascalCli"}, config, dry_run=True)

            self.assertEqual(result["status"], "dry-run")
            self.assertIn("插值样例", result["message"])
            self.assertIn("echo session_start triggered", result["message"])

    def test_plain_legacy_command_unchanged(self):
        """无占位符的旧命令：插值 no-op，写入内容与模板逐字一致。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = str(path)
            config["hooks"]["clients"][0]["template"] = {
                "SessionStart": "my-tool on session_start"
            }

            fix_hooks_tool({"name": "PascalCli"}, config)

            entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
            self.assertEqual(entry[0]["hooks"][0]["command"], "my-tool on session_start")


if __name__ == "__main__":
    unittest.main()
