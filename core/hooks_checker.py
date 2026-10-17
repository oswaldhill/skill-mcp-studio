"""Hook configuration checks kept independent from MCP availability."""

import json
import os
from typing import Any, Dict, Iterable


def _commands(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        if isinstance(node.get("command"), str):
            yield node["command"]
        for value in node.values():
            yield from _commands(value)
    elif isinstance(node, list):
        for value in node:
            yield from _commands(value)


def check_hooks(config_path: str) -> Dict[str, Any]:
    path = os.path.expanduser(config_path)
    if not os.path.isfile(path):
        return {"hooks_configured": False, "events": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {"hooks_configured": False, "events": []}
    hooks = data.get("hooks", data) if isinstance(data, dict) else {}
    events = []
    if isinstance(hooks, dict):
        for event, value in hooks.items():
            # 命令非空即算该事件已配置（不区分来源；v0.29.0 起不再识别特定工具签名）
            if any(command.strip() for command in _commands(value)):
                events.append(event)
    return {"hooks_configured": bool(events), "events": sorted(events)}
