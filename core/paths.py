"""用户级路径解析 —— 单一入口，运行期可切换（评审 P0-4）。

为什么要有这个模块：技能库根路径原先写成模块级常量
（``_SKILLS_DIR = Path.home() / ".skills-manager" / "skills"``），在 ``import``
时就被求值并按模块缓存。后果是**运行期无法改变它** —— 测试只能靠「把路径
一路当参数透传」绕开，「技能市场源只在首次打开时探测、环境变化后刷不掉」与
「用例读死开发机技能库」都是这一族的症状。

设计取向：

- **每次调用重新解析，不做模块级缓存** —— 这正是本项要治的病。解析很便宜
  （一次 ``os.environ.get`` 加一次 ``Path`` 构造），不值得用缓存换正确性。
- 三层优先级：**显式注入 > 环境变量 > ``Path.home()``**。注入给测试与嵌入式
  调用方；环境变量给「同一台机器跑多套配置」。
- **不提供 ``clear()``**：既然不缓存，就没有要清的东西。测试用 ``override()``
  上下文管理器临时切换即可。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

#: 覆盖用户级根目录的环境变量名。
HOME_ENV = "SKILL_MCP_STUDIO_HOME"

_AGENTS_SUBPATH = ".agents"
_SKILLS_SUBPATH = (".skills-manager", "skills")
_LOCK_NAME = ".skill-lock.json"

#: 显式注入的根目录（None = 未注入，走环境变量/真实 home）。
_injected: Optional[Path] = None


def home_root() -> Path:
    """用户级根目录：显式注入 > 环境变量 > 真实 home。"""
    if _injected is not None:
        return _injected
    env = os.environ.get(HOME_ENV)
    if env:
        return Path(env).expanduser()
    return Path.home()


def agents_dir() -> Path:
    """``~/.agents`` —— ``npx skills`` 的全局安装落点。"""
    return home_root() / _AGENTS_SUBPATH


def skills_dir() -> Path:
    """统一技能库实体目录（``~/.skills-manager/skills``）。"""
    return home_root().joinpath(*_SKILLS_SUBPATH)


def default_lock_path() -> Path:
    """技能来源登记表的默认位置（``~/.agents/.skill-lock.json``）。"""
    return agents_dir() / _LOCK_NAME


def set_home_root(path: Optional[Path]) -> None:
    """显式注入根目录（测试/嵌入式）；传 ``None`` 撤销注入。"""
    global _injected
    _injected = Path(path).expanduser() if path is not None else None


def reset() -> None:
    """撤销注入，回到「环境变量 > 真实 home」的解析。"""
    set_home_root(None)


@contextmanager
def override(path: Path) -> Iterator[Path]:
    """临时切换根目录，退出时恢复原状 —— 测试的推荐入口。"""
    global _injected
    previous = _injected
    set_home_root(path)
    try:
        yield home_root()
    finally:
        _injected = previous
