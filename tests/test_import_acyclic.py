"""A-5 import 环守护：core/ 模块顶层 import 图必须无环。

历史：config_store ↔ mcp_fixer ↔ tool_registry 的加载期环靠 6+ 处惰性 import 打补丁。
整改后抽出 file_atomic / names / config_codec 三个叶子模块，顶层图可拓扑排序。
本测试锁定该不变量，防止后续改动重新引入环。
"""

import ast
import importlib
import os
import sys
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))

_LOCAL_MODULES = sorted(
    f[:-3] for f in os.listdir(CORE) if f.endswith(".py") and f != "__init__.py"
)


def _top_level_local_deps(mod: str) -> set:
    tree = ast.parse((CORE / f"{mod}.py").read_text(encoding="utf-8"))
    deps = set()
    for node in tree.body:  # module body only; function-body (lazy) imports excluded
        if isinstance(node, ast.Import):
            for alias in node.names:
                deps.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                deps.add(node.module.split(".")[0])
    return {d for d in deps if d in set(_LOCAL_MODULES)}


class ImportGraphTest(unittest.TestCase):
    def test_top_level_import_graph_is_acyclic(self):
        incoming = {m: 0 for m in _LOCAL_MODULES}
        deps = {m: _top_level_local_deps(m) for m in _LOCAL_MODULES}
        for mod, ds in deps.items():
            for d in ds:
                incoming[d] += 1
        queue = deque(sorted(m for m, c in incoming.items() if c == 0))
        ordered = []
        while queue:
            m = queue.popleft()
            ordered.append(m)
            for d in deps[m]:
                incoming[d] -= 1
                if incoming[d] == 0:
                    queue.append(d)
        cyclic = sorted(m for m in _LOCAL_MODULES if incoming[m] > 0)
        self.assertEqual(
            cyclic,
            [],
            f"core/ 顶层 import 存在环成员: {cyclic}（请抽出叶子模块打破，勿用惰性 import 掩藏）",
        )
        self.assertEqual(len(ordered), len(_LOCAL_MODULES))

    def test_every_core_module_imports_standalone(self):
        failures = []
        for mod in _LOCAL_MODULES:
            try:
                importlib.import_module(mod)
            except Exception as exc:  # noqa: BLE001
                failures.append((mod, repr(exc)))
        self.assertEqual(failures, [], f"以下模块无法独立导入: {failures}")


if __name__ == "__main__":
    unittest.main()
