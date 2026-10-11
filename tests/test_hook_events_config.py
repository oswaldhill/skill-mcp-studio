"""Hook 事件配置：全局「要写入哪些事件」的行为契约（2026-10-11）。

## 背景

此前「写哪些 hook 事件」散落在 `config.yaml` 每个客户端的 `template` 里，
既无法统一管理，又会与 `events` 声明不一致 —— 实测 Codex 声明支持
`UserPromptSubmit` 但 template 缺它，审计报「缺 UserPromptSubmit」而写入**永远补不上**
（假警报，因为写入只看 template）。

改为：`settings.hook_events` 给出**标准事件名**列表，`--fix-hooks` 按各客户端
`event_format` 转成它的规范名后写入。本文件守住这条链路的四个关键点。
"""

from __future__ import annotations

import json
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
                    "template": {"SessionStart": "ai-memory hook --event session_start"},
                },
                {
                    "name": "CamelCli",
                    "config_path": "",
                    "format": "json",
                    "hook_key_path": ["hooks"],
                    "event_format": "camel_case",
                    "events": ["sessionStart", "stop"],
                    "fix_supported": True,
                    "template": {"stop": "ai-memory hook --event stop"},
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

    def test_configured_events_override_template(self):
        """勾选了 template 没有的事件，也必须写上（这正是 Codex 的假警报场景）。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{}\n", encoding="utf-8")
            config = _config(["SessionStart", "UserPromptSubmit", "SessionEnd", "Stop"])
            config["hooks"]["clients"][0]["config_path"] = str(path)

            result = fix_hooks_tool({"name": "PascalCli"}, config)

            self.assertEqual(result["status"], "updated")
            hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
            self.assertEqual(
                sorted(hooks.keys()),
                ["SessionEnd", "SessionStart", "Stop", "UserPromptSubmit"],
            )
            # 未在 template 里的 UserPromptSubmit 用兜底命令写入，而不是静默漏掉
            dumped = json.dumps(hooks["UserPromptSubmit"], ensure_ascii=False)
            self.assertIn("ai-memory hook --event user_prompt_submit", dumped)

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

    def test_non_ai_memory_hooks_are_preserved(self):
        """只增不减：客户端已有的非 ai-memory hook 必须原样保留。"""
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
            self.assertIn("other-bridge", dumped, "非 ai-memory hook 被删除了")
            self.assertIn("ai-memory hook", dumped, "ai-memory hook 未写入")


if __name__ == "__main__":
    unittest.main()
