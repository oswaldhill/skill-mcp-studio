"""config.yaml 的 hook 能力表与引擎口径的一致性（2026-10-12）。

背景：GUI 的「写往 N 个客户端」列、写入端的能力校验、以及「缺关键事件」审计
三者必须基于**同一份**能力表。任何一处漂移都会表现为「界面说会写、实际没写」
或「审计报缺、其实不支持」。本文件把这份表钉死。
"""
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from hooks_inventory import (  # noqa: E402
    client_scopes,
    client_supported_events,
    event_name_for_client,
    hooks_client_config,
)

VALID_ENTRY_STYLES = {"nested", "flat"}


class HookCapabilityDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(ROOT / "config.yaml", encoding="utf-8") as fh:
            cls.config = yaml.safe_load(fh)
        cls.hooks = cls.config.get("hooks") or {}
        cls.canonical = [e["name"] for e in cls.hooks.get("events") or []]
        cls.clients = cls.hooks.get("clients") or []

    def test_canonical_vocabulary_is_large_and_unique(self):
        """词表要「尽可能多」（用户诉求）且不得重名。"""
        self.assertGreaterEqual(len(self.canonical), 40)
        self.assertEqual(len(self.canonical), len(set(self.canonical)))

    def test_catalog_entries_carry_group(self):
        """GUI 按 group 分组渲染，缺 group 会掉进「其他」并难以阅读。"""
        missing = [e["name"] for e in self.hooks["events"] if not e.get("group")]
        self.assertEqual(missing, [])

    def test_every_writable_client_declares_capability_and_scopes(self):
        for cl in self.clients:
            with self.subTest(client=cl["name"]):
                self.assertTrue(client_supported_events(cl), "能力集为空")
                self.assertTrue(client_scopes(cl), "未声明分层作用域")
                if cl.get("fix_supported"):
                    self.assertIn(cl.get("entry_style", "nested"), VALID_ENTRY_STYLES)

    def test_supported_events_map_back_to_canonical(self):
        """每个可写客户端的事件都要能由规范词表转名得到。

        否则规范词表勾选项与客户端能力集对不上 —— GUI 的「写往」列会漏算，
        用户勾了却写不进去。
        """
        for cl in self.clients:
            if not cl.get("fix_supported"):
                continue
            fmt = cl.get("event_format")
            supported = set(client_supported_events(cl))
            for canon in self.canonical:
                native = event_name_for_client(canon, fmt)
                if native in supported:
                    continue
                # 反向：能力集里每个事件也必须能被某个规范名解释
            for native in supported:
                canon = native[0].upper() + native[1:]
                with self.subTest(client=cl["name"], event=native):
                    self.assertIn(canon, self.canonical)

    def test_cursor_uses_flat_entry_style(self):
        """Cursor 条目是扁平结构（本机实测），不得写成嵌套。"""
        cursor = hooks_client_config(self.config, "Cursor")
        self.assertEqual(cursor.get("entry_style"), "flat")

    def test_trae_uses_pascal_case(self):
        """TRAE 官方事件是 PascalCase；本机 camelCase 键来自第三方桥接工具。"""
        trae = hooks_client_config(self.config, "TRAE")
        self.assertEqual(trae.get("event_format"), "pascal_case")
        self.assertTrue(all(e[0].isupper() for e in client_supported_events(trae)))


if __name__ == "__main__":
    unittest.main()
