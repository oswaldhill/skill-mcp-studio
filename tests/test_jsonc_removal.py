"""JSONC 注释感知的文本级操作测试（注释屏蔽 + 按字节范围删除成员）。

TDD：本文件对应的实现是 ``core/jsonc_text.py``。核心不变式——
**删除只动目标成员自身与一个分隔逗号，其余字节（注释、空白、缩进、键序、
其他成员）逐字不变**；未命中任何 key 时返回字节相同的原文。
"""

import itertools
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from config_backups import restore_config_backup  # noqa: E402
from jsonc_text import (  # noqa: E402
    mask_jsonc_comments,
    member_ranges,
    remove_object_members,
)
from mcp_fixer import _render_without_entries, validate_config_text  # noqa: E402


def strip_trailing_commas(text):
    """仅用于断言：把尾随逗号去掉，便于用严格 json.loads 复核内容。"""
    return re.sub(r",(\s*[}\]])", r"\1", text)


class MaskCommentsTest(unittest.TestCase):
    def test_masks_line_and_block_comments_length_preserved(self):
        text = '{\n  "a": 1, // 行注释\n  /* 块\n注释 */\n  "b": 2\n}\n'
        masked = mask_jsonc_comments(text)

        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.count("\n"), text.count("\n"))
        self.assertNotIn("行注释", masked)
        self.assertNotIn("块", masked)
        self.assertEqual(json.loads(masked), {"a": 1, "b": 2})

    def test_no_comments_returns_identical_text(self):
        text = '{\n  "a": 1,\n  "b": [1, 2]\n}\n'
        self.assertEqual(mask_jsonc_comments(text), text)

    def test_url_inside_string_is_not_a_comment(self):
        text = '{"url": "https://example.com/mcp"}\n'
        masked = mask_jsonc_comments(text)

        self.assertEqual(masked, text)
        self.assertEqual(json.loads(masked)["url"], "https://example.com/mcp")

    def test_slashes_and_escaped_quote_inside_string(self):
        # 值里同时含 \"、//、/* —— 都必须留在字符串内，只有真正的行注释被屏蔽。
        text = '{"a": "x \\" // /* y", "b": 1} // 真注释\n'
        masked = mask_jsonc_comments(text)

        self.assertIn('"x \\" // /* y"', masked)
        self.assertNotIn("真注释", masked)
        parsed = json.loads(masked)
        self.assertEqual(parsed["a"], 'x " // /* y')
        self.assertEqual(parsed["b"], 1)

    def test_quote_inside_line_comment_does_not_open_a_string(self):
        text = "// it's a \"quote\n{\"a\": 1}\n"
        masked = mask_jsonc_comments(text)

        self.assertNotIn("quote", masked)
        self.assertEqual(json.loads(masked), {"a": 1})

    def test_unterminated_block_comment_is_masked_to_end(self):
        text = '{"a": 1}\n/* never closed'
        masked = mask_jsonc_comments(text)

        self.assertEqual(len(masked), len(text))
        self.assertTrue(masked.endswith(" " * len("/* never closed")))


class RemoveObjectMembersTest(unittest.TestCase):
    COMMENTED = (
        "{\n"
        "  // 顶部：opencode 配置\n"
        '  "$schema": "https://opencode.ai/config.json",\n'
        '  "theme": "dark", /* 主题说明 */\n'
        '  "mcp": {\n'
        "    // 统一端点（保留）\n"
        '    "hermes-unified": {\n'
        '      "type": "remote",\n'
        '      "url": "https://hermes.example/mcp"\n'
        "    },\n"
        "    // 旧桥接（待删；它自己的注释留在原位）\n"
        '    "hermes": {\n'
        '      "type": "local",\n'
        '      "command": ["python3", "/home/u/.local/bin/hermes-bridge.py"]\n'
        "    },\n"
        '    "other": { "url": "https://other.example/mcp" } // 尾部注释\n'
        "  },\n"
        '  "note": "see https://opencode.ai/docs // not a comment"\n'
        "}\n"
    )
    # 目标成员自身 + 紧随其后的分隔逗号；行首 4 空格缩进不在删除范围内。
    HERMES_MEMBER = (
        '"hermes": {\n'
        '      "type": "local",\n'
        '      "command": ["python3", "/home/u/.local/bin/hermes-bridge.py"]\n'
        "    },"
    )

    def test_other_comments_and_formatting_survive_verbatim(self):
        expected = self.COMMENTED.replace(self.HERMES_MEMBER, "", 1)

        result = remove_object_members(self.COMMENTED, ["mcp"], ["hermes"])

        self.assertEqual(result, expected)
        self.assertEqual(len(self.COMMENTED) - len(result), len(self.HERMES_MEMBER))
        for comment in (
            "// 顶部：opencode 配置",
            "/* 主题说明 */",
            "// 统一端点（保留）",
            "// 旧桥接（待删；它自己的注释留在原位）",
            "// 尾部注释",
            '"see https://opencode.ai/docs // not a comment"',
        ):
            self.assertIn(comment, result)

    def test_removed_target_disappears_and_rest_is_intact(self):
        result = remove_object_members(self.COMMENTED, ["mcp"], ["hermes"])
        parsed = json.loads(mask_jsonc_comments(result))

        self.assertNotIn("hermes", parsed["mcp"])
        self.assertEqual(
            parsed["mcp"]["hermes-unified"],
            {"type": "remote", "url": "https://hermes.example/mcp"},
        )
        self.assertEqual(parsed["mcp"]["other"], {"url": "https://other.example/mcp"})
        self.assertEqual(parsed["theme"], "dark")
        self.assertEqual(parsed["$schema"], "https://opencode.ai/config.json")

    def test_removes_first_middle_and_last_member(self):
        text = (
            "{\n"
            '  "mcp": {\n'
            '    "first": {"url": "https://1.example/mcp"},\n'
            '    "middle": {"url": "https://2.example/mcp"},\n'
            '    "last": {"url": "https://3.example/mcp"}\n'
            "  }\n"
            "}\n"
        )

        after_first = remove_object_members(text, ["mcp"], ["first"])
        after_middle = remove_object_members(text, ["mcp"], ["middle"])
        after_last = remove_object_members(text, ["mcp"], ["last"])

        for rendered, gone in (
            (after_first, "first"),
            (after_middle, "middle"),
            (after_last, "last"),
        ):
            parsed = json.loads(mask_jsonc_comments(rendered))
            self.assertNotIn(gone, parsed["mcp"])
            self.assertEqual(len(parsed["mcp"]), 2)

    def test_removes_last_remaining_member_leaving_empty_object(self):
        text = '{"mcp": {"only": {"url": "https://only.example/mcp"}}}\n'

        result = remove_object_members(text, ["mcp"], ["only"])

        self.assertEqual(json.loads(result), {"mcp": {}})
        self.assertNotIn("only", result)

    def test_trailing_comma_after_last_member_is_cleaned_up(self):
        text = '{"mcp": {"a": {}, "b": {},}}\n'

        result = remove_object_members(text, ["mcp"], ["b"])

        self.assertEqual(result, '{"mcp": {"a": {} }}\n')
        self.assertEqual(json.loads(result), {"mcp": {"a": {}}})

    def test_trailing_comma_after_only_member(self):
        text = '{"mcp": {"a": {},}}\n'

        result = remove_object_members(text, ["mcp"], ["a"])

        self.assertEqual(result, '{"mcp": {}}\n')
        self.assertEqual(json.loads(result), {"mcp": {}})

    def test_trailing_comma_is_kept_when_deleting_non_last_member(self):
        # 输入本身带尾随逗号（非严格 JSON）；删非尾成员时只删该成员与它自己的
        # 分隔逗号，容器尾随逗号不属于目标，保持原样。
        text = '{"mcp": {"a": {}, "b": {},}}\n'

        result = remove_object_members(text, ["mcp"], ["a"])

        self.assertEqual(result, '{"mcp": { "b": {},}}\n')
        self.assertEqual(
            json.loads(strip_trailing_commas(result)), {"mcp": {"b": {}}}
        )

    def test_multiple_keys_at_once(self):
        text = (
            "{\n"
            '  "mcp": {\n'
            '    "a": {},\n'
            '    "b": {},\n'
            '    "c": {}\n'
            "  }\n"
            "}\n"
        )

        result = remove_object_members(text, ["mcp"], ["a", "c"])

        self.assertEqual(json.loads(mask_jsonc_comments(result)), {"mcp": {"b": {}}})

    def test_deleting_every_member(self):
        text = '{"mcp": {"a": {}, "b": {}}}\n'

        result = remove_object_members(text, ["mcp"], ["a", "b"])

        self.assertEqual(json.loads(result), {"mcp": {}})

    def test_tail_run_of_multiple_members_leaves_no_dangling_comma(self):
        # 随机化实测发现的缺陷：连续删除到对象末尾的多个成员（此处 x、y），
        # 若只删每个成员「自己的后随逗号」，keep 后面的那个分隔逗号会悬挂成
        # 尾随逗号（json.loads: Illegal trailing comma）。成组删除必须整段处理。
        text = (
            "{\n"
            "  // 顶部注释\n"
            '  "mcp": {\n'
            '    "keep": {"url": "https://keep.example/mcp"},\n'
            '    "x": {"url": "https://x.example/mcp"},\n'
            '    "y": {"url": "https://y.example/mcp"}\n'
            "  }\n"
            "}\n"
        )

        result = remove_object_members(text, ["mcp"], ["x", "y"])

        self.assertEqual(
            json.loads(mask_jsonc_comments(result)),
            {"mcp": {"keep": {"url": "https://keep.example/mcp"}}},
        )
        self.assertIn("// 顶部注释", result)

    def test_every_subset_of_a_container_can_be_removed(self):
        names = ["a", "b", "c", "d"]
        text = (
            "{\n"
            "  // 顶部注释\n"
            '  "mcp": {\n'
            + ",\n".join(
                f'    "{name}": {{"url": "https://{name}.example/mcp"}}'
                for name in names
            )
            + "\n  }\n}\n"
        )

        for size in range(1, len(names) + 1):
            for subset in itertools.combinations(names, size):
                with self.subTest(subset=subset):
                    result = remove_object_members(text, ["mcp"], list(subset))
                    expected = {
                        "mcp": {
                            name: {"url": f"https://{name}.example/mcp"}
                            for name in names
                            if name not in subset
                        }
                    }
                    self.assertEqual(
                        json.loads(mask_jsonc_comments(result)), expected
                    )
                    self.assertIn("// 顶部注释", result)
                    # 幂等：目标已不存在时再删必须字节不变
                    self.assertEqual(
                        remove_object_members(result, ["mcp"], list(subset)), result
                    )

    def test_every_subset_with_trailing_comma(self):
        names = ["a", "b", "c"]
        text = '{"mcp": {' + ", ".join(f'"{name}": {{}}' for name in names) + ",}}\n"

        for size in range(1, len(names) + 1):
            for subset in itertools.combinations(names, size):
                with self.subTest(subset=subset):
                    result = remove_object_members(text, ["mcp"], list(subset))
                    expected = {name for name in names if name not in subset}
                    # 无论删哪些，内容都必须正确（容忍仍留存的容器尾随逗号）。
                    self.assertEqual(
                        set(
                            json.loads(
                                strip_trailing_commas(mask_jsonc_comments(result))
                            )["mcp"]
                        ),
                        expected,
                    )
                    if names[-1] in subset:
                        # 末成员被删 → 尾随逗号随之删掉，结果回到严格 JSON。
                        self.assertEqual(
                            set(json.loads(result)["mcp"]), expected
                        )
                    else:
                        # 末成员保留 → 它自己的尾随逗号属于容器、不属于目标，原样保留
                        # （已知边界：非严格 JSON，严格 json.loads 会拒绝）。
                        with self.assertRaises(json.JSONDecodeError):
                            json.loads(result)

    def test_unknown_key_returns_byte_identical_text(self):
        result = remove_object_members(self.COMMENTED, ["mcp"], ["nope"])

        self.assertEqual(result, self.COMMENTED)

    def test_missing_key_path_returns_byte_identical_text(self):
        result = remove_object_members(self.COMMENTED, ["absent"], ["hermes"])

        self.assertEqual(result, self.COMMENTED)

    def test_nested_objects_and_arrays_are_not_touched(self):
        text = (
            "{\n"
            '  "mcp": {\n'
            '    "keep": {\n'
            '      "nested": {"hermes": {"url": "https://nested.example/mcp"}},\n'
            '      "list": [{"hermes": {}}, ["hermes", "x"]]\n'
            "    },\n"
            '    "hermes": {}\n'
            "  }\n"
            "}\n"
        )

        result = remove_object_members(text, ["mcp"], ["hermes"])

        self.assertEqual(result.count('"hermes"'), 3)
        parsed = json.loads(mask_jsonc_comments(result))
        self.assertNotIn("hermes", parsed["mcp"])
        self.assertIn("hermes", parsed["mcp"]["keep"]["nested"])
        self.assertEqual(parsed["mcp"]["keep"]["list"][1], ["hermes", "x"])

    def test_braces_commas_and_comment_markers_inside_strings(self):
        text = (
            "{\n"
            '  "mcp": {\n'
            '    "a": {"url": "https://a.example/mcp", "note": "}{ , \\" // /* nope"},\n'
            '    "hermes": {"url": "https://h.example/mcp"},\n'
            '    "z": {"url": "https://z.example/mcp"}\n'
            "  }\n"
            "}\n"
        )
        keep_a = '    "a": {"url": "https://a.example/mcp", "note": "}{ , \\" // /* nope"},\n'
        keep_z = '    "z": {"url": "https://z.example/mcp"}\n'

        result = remove_object_members(text, ["mcp"], ["hermes"])

        self.assertIn(keep_a, result)
        self.assertIn(keep_z, result)
        self.assertNotIn("h.example", result)

    def test_result_parses_after_masking_and_target_is_gone(self):
        text = (
            "{\n"
            "  // 注释\n"
            '  "mcp": {\n'
            "    // a 的注释\n"
            '    "a": {"url": "https://a.example/mcp"},\n'
            '    "b": {"url": "https://b.example/mcp"} // b 的注释\n'
            "  }\n"
            "}\n"
        )

        result = remove_object_members(text, ["mcp"], ["b"])
        parsed = json.loads(mask_jsonc_comments(result))

        self.assertNotIn("b", parsed["mcp"])
        self.assertIn("a", parsed["mcp"])
        self.assertIn("// a 的注释", result)
        self.assertIn("// b 的注释", result)

    def test_comment_between_value_and_separator_comma_survives(self):
        # 成员值与它自己的分隔逗号之间夹的注释，不属于目标成员，必须留下。
        text = '{"mcp": {\n  "a": {},\n  "b": {} /* b 的尾注 */,\n  "c": {}\n}}\n'

        result = remove_object_members(text, ["mcp"], ["b"])

        self.assertIn("/* b 的尾注 */", result)
        self.assertEqual(
            sorted(json.loads(mask_jsonc_comments(result))["mcp"]), ["a", "c"]
        )

    def test_member_ranges_locates_members(self):
        ranges = member_ranges(self.COMMENTED, ["mcp"], ["hermes"])

        self.assertEqual(len(ranges), 1)
        start, end = ranges[0]
        self.assertEqual(
            self.COMMENTED[start:end],
            self.HERMES_MEMBER[:-1],  # member_ranges 不含分隔逗号
        )

    def test_member_ranges_empty_when_missing(self):
        self.assertEqual(member_ranges(self.COMMENTED, ["mcp"], ["nope"]), [])
        self.assertEqual(member_ranges(self.COMMENTED, ["absent"], ["hermes"]), [])

    def test_null_key_path_value_returns_original(self):
        # 与 json 分支一致：key 存在但值为 null（JSON null）视同「无该对象」，
        # 原样返回而非抛错。
        text = '{"mcp": null, "x": 1}\n'

        self.assertEqual(remove_object_members(text, ["mcp"], ["a"]), text)

    def test_unparsable_input_raises(self):
        for broken in (
            "{ not json",
            '{"mcp": {"a": {},',
            "[1, 2]",
            '{"mcp": []}',
        ):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    remove_object_members(broken, ["mcp"], ["a"])


class JsoncIntegrationTest(unittest.TestCase):
    COMMENTED = RemoveObjectMembersTest.COMMENTED

    def tool(self, path, **over):
        data = {
            "name": "OpenCode",
            "config_path": str(path),
            "format": "jsonc",
            "mcp_key_path": ["mcp"],
            "fix_supported": True,
        }
        data.update(over)
        return data

    def test_render_without_entries_removes_from_commented_jsonc(self):
        rendered = _render_without_entries(self.tool("/tmp/x.jsonc"), self.COMMENTED, ["hermes"])

        self.assertNotEqual(rendered, self.COMMENTED)
        self.assertEqual(
            rendered, self.COMMENTED.replace(RemoveObjectMembersTest.HERMES_MEMBER, "", 1)
        )
        parsed = json.loads(mask_jsonc_comments(rendered))
        self.assertNotIn("hermes", parsed["mcp"])
        self.assertIn("hermes-unified", parsed["mcp"])
        self.assertIn("// 顶部：opencode 配置", rendered)
        self.assertIn("// 尾部注释", rendered)

    def test_render_without_entries_is_byte_identical_when_key_absent(self):
        rendered = _render_without_entries(self.tool("/tmp/x.jsonc"), self.COMMENTED, ["nope"])

        self.assertEqual(rendered, self.COMMENTED)

    def test_validate_config_text_accepts_comments(self):
        validate_config_text(self.tool("/tmp/x.jsonc"), self.COMMENTED)

        with self.assertRaises(json.JSONDecodeError):
            validate_config_text(self.tool("/tmp/x.jsonc"), "{ broken")

    def test_validate_config_text_rejects_other_malformed_jsonc(self):
        with self.assertRaises(json.JSONDecodeError):
            validate_config_text(
                self.tool("/tmp/x.jsonc"), '{\n  // 注释\n  "mcp": {"a": {}},\n'
            )

    def test_validate_config_text_still_rejects_trailing_comma_jsonc(self):
        """已知边界（不是本次缺陷）：mask 只剥注释，尾随逗号仍会被严格 json.loads 拒绝。

        ``remove_object_members`` 本身支持尾随逗号（见
        ``test_trailing_comma_after_last_member_is_cleaned_up``），但校验口径按设计
        约束保持 ``mask + json.loads``，故**带尾随逗号的 jsonc 备份**仍会被 restore
        判 ``refused``。这是显式已知边界，不是静默降级。
        """
        text = '{\n  // 注释\n  "mcp": {"a": {},},\n}\n'

        with self.assertRaises(json.JSONDecodeError):
            validate_config_text(self.tool("/tmp/x.jsonc"), text)

    def test_restore_commented_jsonc_backup_is_updated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opencode.jsonc"
            current = '{\n  // 当前配置\n  "mcp": {}\n}\n'
            path.write_text(current, encoding="utf-8")
            backup = Path(str(path) + ".bak-20260920-100000-000000")
            backup.write_text(self.COMMENTED, encoding="utf-8")

            result = restore_config_backup(self.tool(path), str(backup))

            self.assertEqual(result["status"], "updated")
            self.assertEqual(path.read_text(encoding="utf-8"), self.COMMENTED)
            self.assertEqual(
                Path(result["backup"]).read_text(encoding="utf-8"), current
            )


if __name__ == "__main__":
    unittest.main()
