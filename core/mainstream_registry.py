"""主流工具注册入口（公开 API）。

实现与数据已拆到 mainstream_registry_data / mainstream_registry_extra（评审清单 P2-16），
此处保留原有公开名字与行为，对外导入路径不变。
"""
# 显式再导出：7 处（含 config_store.py）直接 `from mainstream_registry import MAINSTREAM_TOOLS`。
# 写成 `as` 同名字形式，同时避免被 ruff F401 当未使用导入删掉（见清单 P1-11 实测）。
from mainstream_registry_data import MAINSTREAM_TOOLS as MAINSTREAM_TOOLS
from mainstream_registry_extra import EXTRA_MAINSTREAM_TOOLS


MAINSTREAM_NAMES = [t["name"] for t in MAINSTREAM_TOOLS]



def register_mainstream_tools():
    """返回扩展后的主流工具清单（含国内外常用）。"""
    return MAINSTREAM_TOOLS + EXTRA_MAINSTREAM_TOOLS
