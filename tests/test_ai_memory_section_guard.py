"""R3 回归：MCP 配置段既存内容不是对象时，绝不能被覆盖掉。

历史缺陷（v0.24.0 清单 R3）：``_find_json_mcp_section`` 里写的是
``if key not in current or not isinstance(current[key], dict): current[key] = {}``
—— 第二半会把既有的非 dict 内容（列表/字符串/标量）直接覆盖成 ``{}``，
于是该函数**永不返回 None**，调用方「MCP 配置段结构异常，跳过」成了死代码，
用户原有的 MCP 条目被无提示清空后再整文件回写（数据丢失）。

本测试把这条不变量钉住：**键不存在才创建，键存在但类型不对必须原样返回 None
且不触碰既有值**。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import ai_memory_checker  # noqa: E402


class FindJsonMcpSectionGuardTest(unittest.TestCase):
    def test_returns_none_when_existing_value_is_a_list(self):
        """列表形式的既有 mcpServers 必须原样保留，不得被覆盖成 {}。"""
        original = ["user-entry-1", "user-entry-2"]
        data = {"mcpServers": list(original)}

        section = ai_memory_checker._find_json_mcp_section(data, ["mcpServers"])

        self.assertIsNone(section, "既存值不是 dict 时必须返回 None（让调用方跳过）")
        self.assertEqual(
            data["mcpServers"], original,
            "既存的列表内容被改动了 —— 这正是 R3 的数据丢失",
        )

    def test_returns_none_when_existing_value_is_a_scalar(self):
        data = {"mcpServers": "not-a-dict"}
        self.assertIsNone(ai_memory_checker._find_json_mcp_section(data, ["mcpServers"]))
        self.assertEqual(data["mcpServers"], "not-a-dict")

    def test_returns_none_for_non_dict_intermediate_level(self):
        """中间层类型不对时同样跳过，且不触碰任何已有值。"""
        data = {"a": {"b": [1, 2, 3]}}
        self.assertIsNone(ai_memory_checker._find_json_mcp_section(data, ["a", "b", "c"]))
        self.assertEqual(data["a"]["b"], [1, 2, 3])

    def test_creates_missing_levels_but_does_not_clobber(self):
        """正常的「键不存在」路径仍要创建，且返回的就是容器本身（可写入）。"""
        data = {"a": {}}
        section = ai_memory_checker._find_json_mcp_section(data, ["a", "mcpServers"])
        self.assertEqual(section, {})
        self.assertIs(section, data["a"]["mcpServers"], "应返回同一对象以便调用方写入")

    def test_empty_path_returns_root(self):
        data = {"mcpServers": {}}
        self.assertIs(ai_memory_checker._find_json_mcp_section(data, []), data)


if __name__ == "__main__":
    unittest.main()
