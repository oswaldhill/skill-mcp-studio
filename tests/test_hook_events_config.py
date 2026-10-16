"""Hook 事件配置：全局「要写入哪些事件」的行为契约（2026-10-11）。

## 背景

此前「写哪些 hook 事件」散落在 `config.yaml` 每个客户端的 `template` 里，
既无法统一管理，又会与 `events` 声明不一致 —— 实测 Codex 声明支持
`UserPromptSubmit` 但 template 缺它，审计报「缺 UserPromptSubmit」而写入**永远补不上**
（假警报，因为写入只看 template）。

改为：`settings.hook_events` 给出**标准事件名**列表，`--fix-hooks` 按各客户端
`event_format` 转成它的规范名后写入。本文件守住这条链路的几个关键点。

v0.29.0 起：兜底命令为空（不再内置任何工具命令），无 template 的事件
**跳过不写**；已有第三方 hook 照常保留，我们的命令按命令级去重追加。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from hooks_fixer import fix_hooks_tool  # noqa: E402
from hooks_inventory import event_name_for_client  # noqa: E402


def _config(hook_events=None) -> dict:
    """最小 config：一个 pascal、一个 camel 客户端，覆盖两种命名规范。"""
    settings = {} if hook_events is None else {"hook_events": hook_events}
    return {
        "settings": settings,
        "hooks": {
            "events": [
                {"name": "SessionStart", "description": "会话开始"},
                {"name": "UserPromptSubmit", "description": "用户提交提示"},
                {"name": "SessionEnd", "description": "会话结束"},
                {"name": "Stop", "description": "停止"},
            ],
            "clients": [
                {
                    "name": "PascalCli",
                    "config_path": "",           # 由各用例替换
                    "format": "json",
                    "hook_key_path": ["hooks"],
                    "event_format": "pascal_case",
                    "events": ["SessionStart", "UserPromptSubmit", "SessionEnd", "Stop"],
                    "fix_supported": True,
                    "template": {"SessionStart": "my-tool on session_start"},
                },
                {
                    "name": "CamelCli",
                    "config_path": "",
                    "format": "json",
                    "hook_key_path": ["hooks"],
                    "event_format": "camel_case",
                    "events": ["sessionStart", "stop"],
                    "fix_supported": True,
                    "template": {
                        "sessionStart": "my-tool on session_start",
                        "stop": "my-tool on stop",
                    },
                },
            ],
        },
    }


class EventNameConversionTest(unittest.TestCase):
    """标准事件名 → 各客户端规范名。"""

    def test_pascal_and_camel(self):
        self.assertEqual(event_name_for_client("SessionStart", "pascal_case"), "SessionStart")
        self.assertEqual(event_name_for_client("SessionStart", "camel_case"), "sessionStart")
        self.assertEqual(
            event_name_for_client("UserPromptSubmit", "camel_case"), "userPromptSubmit"
        )

    def test_unknown_format_passes_through(self):
        self.assertEqual(event_name_for_client("SessionStart", None), "SessionStart")
        self.assertEqual(event_name_for_client("SessionStart", ""), "SessionStart")


class GlobalEventsDriveWritingTest(unittest.TestCase):
    """settings.hook_events 决定写入哪些事件（而不是 template）。"""

    def test_template_command_drives_writing_empty_events_skipped(self):
        """v0.29.0：有 template 命令的事件才写入；无 template 的事件兜底为空→跳过。

        这是与旧版的核心差异：旧版无 template 的事件靠兜底命令硬写；
        v0.29.0 兜底为空，无 template 的事件**跳过**（不写空命令条目）。
        """
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart", "UserPromptSubmit", "SessionEnd", "Stop"])
            config["hooks"]["clients"][0]["config_path"] = str(path)

            result = fix_hooks_tool({"name": "PascalCli"}, config)

            self.assertEqual(result["status"], "updated")
            hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
            # 只有 SessionStart 在 template 里有命令；其余三个无 template 且兜底为空 → 跳过
            self.assertEqual(list(hooks.keys()), ["SessionStart"])
            dumped = json.dumps(hooks["SessionStart"], ensure_ascii=False)
            self.assertIn("my-tool on session_start", dumped)

    def test_camel_client_gets_camel_event_names(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "hooks.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart", "Stop"])
            config["hooks"]["clients"][1]["config_path"] = str(path)

            result = fix_hooks_tool({"name": "CamelCli"}, config)

            self.assertEqual(result["status"], "updated")
            hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
            # camel 规范：sessionStart / stop —— 不是 SessionStart / Stop
            self.assertEqual(sorted(hooks.keys()), ["sessionStart", "stop"])

    def test_template_used_when_no_global_config(self):
        """向后兼容：未配置 settings.hook_events 时仍按 template 写入。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(None)          # 无 hook_events
            config["hooks"]["clients"][0]["config_path"] = str(path)

            result = fix_hooks_tool({"name": "PascalCli"}, config)

            self.assertEqual(result["status"], "updated")
            hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
            # 只写 template 里那一个事件
            self.assertEqual(list(hooks.keys()), ["SessionStart"])

    def test_empty_global_list_writes_nothing(self):
        """空列表 = 无事件可写（等同停用），且不得报成功写入。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config([])
            config["hooks"]["clients"][0]["config_path"] = str(path)

            result = fix_hooks_tool({"name": "PascalCli"}, config)

            # 空列表是**用户的停用选择**，归为 unsupported（不是「配置缺失」——
            # 混成 missing 会让人以为配置丢了）；关键是**不能**写进任何事件
            self.assertEqual(result["status"], "unsupported")
            self.assertIn("不写入任何", result["message"])
            hooks = (json.loads(path.read_text(encoding="utf-8")) or {}).get("hooks") or {}
            self.assertEqual(hooks, {})

    def test_existing_third_party_hooks_preserved_and_new_appended(self):
        """只增不减：客户端已有的第三方 hook 必须原样保留，我们的命令照常追加。

        v0.29.0 去重改为命令级：要写的命令字面已在现有 hook 里出现过才跳过；
        第三方 hook 与我们的命令不同 → 追加，不覆盖。
        """
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "hooks.json"
            path.write_text(json.dumps({
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "/usr/local/bin/other-bridge"}]}
                    ]
                }
            }, indent=2) + "\n", encoding="utf-8")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = str(path)

            fix_hooks_tool({"name": "PascalCli"}, config)

            hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
            dumped = json.dumps(hooks["SessionStart"], ensure_ascii=False)
            self.assertIn("other-bridge", dumped, "第三方 hook 被删除了")
            self.assertIn("my-tool on session_start", dumped, "新命令未追加写入")

    def test_command_level_dedup_skips_already_written(self):
        """命令级去重：要写的命令字面已存在则跳过，避免重复条目（v0.29.0）。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            # 已有我们的命令 → 不应再追加一条
            path.write_text(json.dumps({
                "hooks": {
                    "SessionStart": [
                        {"matcher": "*", "hooks": [
                            {"type": "command", "command": "my-tool on session_start"}
                        ]}
                    ]
                }
            }, indent=2) + "\n", encoding="utf-8")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = str(path)

            result = fix_hooks_tool({"name": "PascalCli"}, config)

            self.assertEqual(result["status"], "unchanged")
            arr = json.loads(path.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
            # 仍只有一条（去重生效）
            cmds = [h.get("command")
                    for entry in arr for h in (entry.get("hooks") or [])
                    if isinstance(h, dict)]
            self.assertEqual(cmds.count("my-tool on session_start"), 1)


if __name__ == "__main__":
    unittest.main()


class HookCapabilityValidationTest(unittest.TestCase):
    """能力校验（2026-10-12）：只写该客户端真正认的事件。

    背景：``hooks.clients[].events`` 从「关注的小集合」升级为「该客户端支持的全部
    事件」（Claude Code 33 / Cursor 21 / TRAE 6 …）。写入端据此过滤 —— 此前是
    「勾了就一定写得上」（用兜底命令硬写），会把 Cursor 独有的 BeforeTabFileRead
    写进根本不认识它的客户端。本类守住新语义，防止回退成硬写。
    """

    def test_unsupported_event_is_skipped_not_written(self):
        """客户端不支持的事件必须**跳过**（回报 skipped），不得靠兜底命令硬写。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            config = _config(["SessionStart", "PreToolUse"])
            # 两个夹具客户端都不支持 PreToolUse
            for cl in config["hooks"]["clients"]:
                cl["config_path"] = path
            res = fix_hooks_tool({"name": "PascalCli"}, config)
            self.assertIn(res["status"], ("created", "updated"))
            self.assertEqual(res.get("skipped"), ["PreToolUse"])
            hooks = json.loads(Path(path).read_text(encoding="utf-8"))["hooks"]
            self.assertIn("SessionStart", hooks)
            self.assertNotIn("PreToolUse", hooks)

    def test_all_selected_unsupported_reports_unsupported(self):
        """选中的事件全不支持时，报 unsupported 并点名它们——不能静默当成「无事件」。"""
        with tempfile.TemporaryDirectory() as d:
            config = _config(["SessionEnd"])          # camel 是 sessionEnd
            config["hooks"]["clients"][1]["config_path"] = os.path.join(d, "c.json")
            res = fix_hooks_tool({"name": "CamelCli"}, config)
            self.assertEqual(res["status"], "unsupported")
            self.assertIn("SessionEnd", res["message"])

    def test_camel_client_skips_pascal_only_event(self):
        """CamelCli 只声明 sessionStart/stop；勾 SessionEnd（→sessionEnd）应被跳过。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            config = _config(["SessionEnd", "Stop"])
            config["hooks"]["clients"][1]["config_path"] = path
            res = fix_hooks_tool({"name": "CamelCli"}, config)
            self.assertIn(res["status"], ("created", "updated"))
            self.assertEqual(res.get("skipped"), ["SessionEnd"])
            hooks = json.loads(Path(path).read_text(encoding="utf-8"))["hooks"]
            self.assertIn("stop", hooks)
            self.assertNotIn("sessionEnd", hooks)

    def test_flat_entry_style_writes_flat_structure(self):
        """Cursor 的条目是扁平 ``{type, command, matcher}``，不是嵌套 hooks 数组。

        两套结构**不可混用**：本机 ~/.cursor/hooks.json 实测扁平，而
        TRAE/Codex/WorkBuddy 是 ``{matcher, hooks:[...]}``。写错客户端不认。
        """
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hooks.json")
            config = _config(["SessionStart"])
            cl = config["hooks"]["clients"][0]
            cl["config_path"] = path
            cl["event_format"] = "camel_case"
            cl["events"] = ["sessionStart"]
            cl["entry_style"] = "flat"
            cl["template"] = {"sessionStart": "my-tool on session_start"}
            res = fix_hooks_tool({"name": "PascalCli"}, config)
            self.assertEqual(res["status"], "created")
            entry = json.loads(Path(path).read_text(encoding="utf-8"))["hooks"]["sessionStart"][0]
            self.assertEqual(entry["type"], "command")
            self.assertIn("command", entry)
            self.assertNotIn("hooks", entry)          # 扁平结构没有嵌套 hooks 数组

    def test_nested_entry_style_is_default(self):
        """未声明 entry_style 时保持嵌套结构（Claude Code / TRAE / Codex / WorkBuddy）。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            config = _config(["SessionStart"])
            config["hooks"]["clients"][0]["config_path"] = path
            fix_hooks_tool({"name": "PascalCli"}, config)
            entry = json.loads(Path(path).read_text(encoding="utf-8"))["hooks"]["SessionStart"][0]
            self.assertIn("hooks", entry)
            self.assertEqual(entry["hooks"][0]["type"], "command")
