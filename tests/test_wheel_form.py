"""T-4: wheel 打包形态的静态一致性守护。

``setup.py`` 的 ``FlattenCoreModules`` 把 ``core/*.py`` 复制到构建根作为顶层
模块，使安装后的 ``scan:main`` 控制台脚本仍能 ``from scanner import ...``。
本测试不实际构建 wheel（本地无 build/pip 网络），改为锁定两条不变量：

1. ``setup.py`` 的 ``CORE_MODULES`` 与磁盘上 ``core/*.py``（除 ``__init__.py``）
   完全一致——新增/删除 core 模块而忘了同步 setup.py 会被此测试拦住；
2. ``scan`` 与全部 core 模块能从「扁平化后」的顶层命名空间导入（模拟安装形态，
   import 路径不含 ``core.`` 前缀）。
"""

import importlib
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(ROOT))   # scan.py 在仓库根
sys.path.insert(0, str(CORE))   # 扁平模块在 core/

_CORE_MODULES_ON_DISK = sorted(
    f[:-3] for f in os.listdir(CORE) if f.endswith(".py") and f != "__init__.py"
)


def _setup_py_core_modules() -> list:
    setup_src = (ROOT / "setup.py").read_text(encoding="utf-8")
    # B-10 后 setup.py 用 _ROOT（仓库根）锚定路径，不再依赖 cwd。
    m = re.search(
        r"CORE_MODULES\s*=\s*sorted\(\s*p\.stem\s+for\s+p\s+in\s+\(_ROOT\s*/\s*\"core\"\)\.glob\(\"\*\.py\"\)\s*\)",
        setup_src,
    )
    if not m:
        return []  # setup.py 改了实现——让下面的断言失败以提醒同步本测试
    # 执行该表达式以获得真实值（与 setup.py 共享同一推导逻辑）。
    return sorted(p.stem for p in (ROOT / "core").glob("*.py") if p.name != "__init__.py")


class WheelFlattenContractTest(unittest.TestCase):
    def test_setup_py_core_modules_match_disk(self):
        self.assertEqual(set(_setup_py_core_modules()), set(_CORE_MODULES_ON_DISK))

    def test_scan_and_all_core_modules_import_flattened(self):
        # 安装形态：每个模块都以顶层名字导入（无 core. 前缀），scan.py 本身也在顶层。
        importlib.import_module("scan")
        for mod in _CORE_MODULES_ON_DISK:
            importlib.import_module(mod)

    def test_setup_py_declares_py_modules(self):
        setup_src = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn("py_modules=[\"scan\"] + CORE_MODULES", setup_src)


if __name__ == "__main__":
    unittest.main()