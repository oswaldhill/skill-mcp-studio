"""FEAT-6 护栏：非 IDE/Agent 的工具管理器不得进入 IDE/Agent 面板。

CC Switch 是供应商切换器 + 本地代理（`com.ccswitch.desktop`），给 Claude Code /
Codex / Gemini / OpenCode 切换配置。它自身不做推理、不跑 agent 循环，也不消费 MCP
（它是把 MCP 注入别的客户端）；同时它带技能管理功能，所以 `~/.cc-switch/skills` 是
统一技能库的挂载点。

由此得到它的正确可见范围：**技能审计里可见，IDE/Agent 表与统计里不可见**。
快照用 `is_agent: false` 表达这个身份（见 `management_snapshot`），前端所有
IDE/Agent 面板必须经由 `_agentsForPanel()` 取数，否则一个「配置工具」会被当成一个
Agent 计入列表、类型分布与「受管客户端」数量。
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
DASHBOARD = ROOT / "gui" / "dashboard.html"
NODE = shutil.which("node")


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    body = re.search(r"<script>(.*?)</script>", _src(), re.S).group(1)
    i = body.index(f"function {name}(")
    j = body.index("\n}\n", i) + 3
    return body[i:j]


def _agent(name, *, is_agent=True, installed=True, install_state="installed", type_="AI Agent"):
    entry = {
        "name": name,
        "type": type_,
        "installed": installed,
        "install_state": install_state,
        "app_paths": [], "cli_paths": [], "config_paths": [],
        "app_versions": [], "cli_versions": [],
        "skills_dir_found": True,
        "skills_compliant": True,
        "skill_link_form": "unified",
        "mcp_config_path": "", "mcp_attach": [],
    }
    if is_agent is not None:
        entry["is_agent"] = is_agent
    return entry


SNAP_AGENTS = [
    _agent("Codex"),
    _agent("WorkBuddy"),
    _agent("CC Switch", is_agent=False, type_="配置工具"),
]


def _render_list_view(agents):
    """在 node 里执行真实 `renderHomeListView`，返回它写入的表格 HTML。"""
    src = _src()
    esc = re.search(r'const escapeHtml = \(v\) =>.*?&#39;"\);', src, re.S).group(0)
    js = "\n".join(
        [
            "const SNAP = " + json.dumps({"agents": agents, "mcp": {"endpoint_status": {}}}) + ";",
            esc,
            "const dotFor = () => 'ok';",
            "const linkFormText = () => '统一目录';",
            "const homeType = () => 'all';",
            "const showAgentDetail = () => {};",
            "const togglePathPop = () => {};",
            "const ICONS = new Proxy({}, { get: () => '' });",
            # 只捕获 agent-home-body 的 innerHTML 写入
            "const holder = { _v: '', set innerHTML(v) { this._v = v; }, get innerHTML() { return this._v; },",
            "  querySelectorAll: () => [] };",
            "const $ = (id) => (id === 'agent-home-body' ? holder : { textContent: '', innerHTML: '' });",
            _fn("_agentsForPanel"),
            _fn("renderHomeListView"),
            "renderHomeListView('');",
            "process.stdout.write(holder._v);",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "agents.js"
        path.write_text(js, encoding="utf-8")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise AssertionError("node 渲染失败：" + proc.stderr[:400])
    return proc.stdout


class SourceGuardTest(unittest.TestCase):
    """静态护栏：IDE/Agent 面板的数据源必须统一走 `_agentsForPanel()`。"""

    def test_panel_renderers_use_the_filtered_source(self):
        src = _src()
        raw = src.count("const agents = (SNAP && SNAP.agents) || [];")
        self.assertEqual(raw, 0,
                         "仍有面板直接读 SNAP.agents：非 IDE/Agent 会被计入。请改用 _agentsForPanel()")
        self.assertEqual(src.count("const agents = _agentsForPanel();"), 4,
                         "IDE/Agent 面板取数处数变了，请确认新面板也走过滤后的数据源")

    def test_helper_treats_missing_field_as_agent(self):
        """旧快照没有 is_agent 字段，必须按「是 Agent」处理，不能把客户端全隐藏。"""
        body = _fn("_agentsForPanel")
        self.assertIn("a.is_agent !== false", body,
                      "过滤条件须为「显式 false 才排除」，缺字段时默认保留")

    def test_helper_filters_non_agents(self):
        body = _fn("_agentsForPanel")
        self.assertIn("filter", body)


@unittest.skipUnless(NODE, "需要 node 才能执行渲染护栏")
class ListViewRenderTest(unittest.TestCase):
    def test_non_agent_absent_from_ide_agent_list(self):
        html = _render_list_view(SNAP_AGENTS)
        self.assertNotIn("CC Switch", html,
                         "非 IDE/Agent（CC Switch）不得出现在 IDE/Agent 列表里")
        self.assertIn("Codex", html)
        self.assertIn("WorkBuddy", html)

    def test_count_excludes_non_agent(self):
        html = _render_list_view(SNAP_AGENTS)
        self.assertIn("共 2 个", html,
                      "计数须排除非 IDE/Agent；3 条 agent 里只有 2 个是真正的 IDE/Agent")

    def test_all_agents_still_render_when_none_marked(self):
        """回归：没有 non_agent 标记时，全员照常显示。"""
        html = _render_list_view([_agent("Codex"), _agent("WorkBuddy")])
        self.assertIn("共 2 个", html)
        self.assertIn("Codex", html)

    def test_legacy_snapshot_without_field_keeps_rows(self):
        """旧快照（无 is_agent 字段）不得因过滤而丢行。"""
        html = _render_list_view([_agent("Codex", is_agent=None),
                                  _agent("WorkBuddy", is_agent=None)])
        self.assertIn("共 2 个", html)


if __name__ == "__main__":
    unittest.main()