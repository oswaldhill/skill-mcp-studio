"""`tests/_js_fn.py` 的护栏：函数抽取必须**精确**。

## 为什么需要这道守卫（2026-11-08）

GUI 测试普遍按函数名抽一段源码再断言（「这个函数里不得有 em-dash」
「这个函数必须调用 runCli」）。抽不准时断言**不会报错**，只会静默地检查错东西：

- 抽多了（旧正则以 `\\n\\}` 结尾，匹配不到缩进两格的函数收尾）→ 断言范围
  膨胀到几十倍，别处的问题被记在这个函数头上（**误报**）；
- 抽少了（以 `\\n  }` 结尾，切在第一个内部块）→ 真正要查的代码根本不在范围里
  （**漏报**）。

两种都曾真实发生：`renderMarketProgress` 真实 221 字节，旧正则抽成 43,723 字节，
把二十几个无关函数裹进 em-dash 检查，于是别处的违规被算到它头上。

本文件用**变异测试**锁住正确行为：
1. 抽出的东西必须以函数声明开头、以配对右花括号结尾；
2. 函数**内**注入的违规必须被看到（正向）；
3. 函数**外**注入的违规必须**不被**看到（反向，这才是旧实现栽的地方）；
4. 字符串与注释里的花括号不得干扰配平。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests._js_fn import extract_function  # noqa: E402


SAMPLE = '''function outer() {
  // 无关的顶格函数
}

function target(a, b) {
  const s = "含 } 的字符串";
  const t = `模板 ${a ? "x}" : "y{"} 结束`;
  if (a) {
    return 1;
  }
  return { ok: true };
}

function afterTarget() {
  return 2;
}
'''


class ExtractFunctionTest(unittest.TestCase):
    def test_extracts_exact_bounds(self):
        body = extract_function(SAMPLE, "target")
        self.assertTrue(body.lstrip().startswith("function target("))
        self.assertTrue(body.rstrip().endswith("}"))
        # 不得把前后的函数裹进来
        self.assertNotIn("function outer", body)
        self.assertNotIn("function afterTarget", body)

    def test_braces_in_strings_do_not_break_balance(self):
        """字符串/模板串里的 `}` 若参与计数，会提前截断或越界。"""
        body = extract_function(SAMPLE, "target")
        self.assertIn('return { ok: true };', body)
        self.assertIn("return 1;", body)

    def test_parameter_default_braces(self):
        src = 'function f(opts = {}) {\n  return 1;\n}\nfunction g() {}\n'
        body = extract_function(src, "f")
        self.assertIn("return 1;", body)
        self.assertNotIn("function g", body)

    def test_async_functions(self):
        src = 'async function work() {\n  await x();\n}\n'
        body = extract_function(src, "work")
        self.assertTrue(body.lstrip().startswith("async function work("))

    def test_missing_function_raises(self):
        """找不到必须抛错，不能返回空串让断言静默通过。"""
        with self.assertRaises(KeyError):
            extract_function(SAMPLE, "nope")

    def test_similar_name_not_matched(self):
        """`target` 不得匹配到 `targetHelper`。"""
        src = 'function targetHelper() {\n  return 1;\n}\n'
        with self.assertRaises(KeyError):
            extract_function(src, "target")


class ScopeIsolationTest(unittest.TestCase):
    """变异测试：证明抽取范围既不外溢（误报）也不内缩（漏报）。"""

    def test_violation_inside_is_detected(self):
        mutated = SAMPLE.replace("  return 1;", '  const bad = "a—b";\n    return 1;')
        self.assertIn("—", extract_function(mutated, "target"))

    def test_violation_outside_is_not_detected(self):
        """旧正则会在这里误报：它把 afterTarget 也算了进来。"""
        mutated = SAMPLE.replace("function afterTarget() {",
                                 'function afterTarget() {\n  // 无关文案 a—b')
        body = extract_function(mutated, "target")
        self.assertNotIn("—", body, "抽取范围外溢：函数外的内容被算进了 target")

    def test_reproduce_old_regex_overreach(self):
        """反向断言：旧正则确实会外溢，以此证明本守卫不是空转。

        复现条件必须是**缩进两格**的函数：旧正则以 `\n\}`（零缩进）收尾，
        而管理台里绝大多数函数是 `  function X()`，收尾是 `\n  }` —— 匹配不到，
        正则就一路吃到下一个顶格函数的末尾。这正是线上真实发生的形态。

        若将来有人把 _js_fn 改回这种正则，上面 3 条测试会红；这条则保证
        「我们为什么要改」这件事本身留在案卷里。
        """
        import re

        indented = (
            "  function target() {\n"
            "    if (x) {\n"
            "      return 1;\n"
            "    }\n"
            "  }\n"
            "  function unrelated() {\n"
            "    return 2;\n"
            "  }\n"
            "function topLevel() {\n"
            "  return 3;\n"
            "}\n"
        )
        old = re.search(r"function target\(.*?\n\}", indented, re.S)
        self.assertIsNotNone(old)
        # 旧正则跨过了 target 自己的收尾，一路吃到顶格函数的末尾
        self.assertIn("function unrelated", old.group(0), "旧正则应外溢到后一个函数")
        self.assertIn("function topLevel", old.group(0), "旧正则应一路吃到顶格函数")

        # 新工具必须只拿到 target 自己
        new = extract_function(indented, "target")
        self.assertNotIn("function unrelated", new)


if __name__ == "__main__":
    unittest.main()
