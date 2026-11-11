"""概览页统计卡的口径护栏（2026-11-04 用户反馈「两个数字看起来矛盾」）。

## 问题是什么

概览页显示「受管客户端 17 / 已安装 5 / 仅发现配置 0 / 未安装 12」，而 MCP 页只列出
5 个客户端。两个页面**在数据上是一致的**（17 = 5 装 + 12 未装，MCP 页只渲染
`install_state !== "none"`），但界面读起来像矛盾，因为：

1. 「未安装 12」用了 `err` 红色 —— 在一个**管理工具**里，没装某个客户端是正常
   状态（注册表收录了不代表你该装），不是故障。红色在别处（本文件的 `err` 语义）
   表示「需要处理的问题」，同一个红被两种含义共用，用户自然会问「哪出错了」。
2. 「受管客户端」没说明它包含未安装项，读者会默认 17 个都是本机在用的。

## 判据

- 未安装数不得使用 `err` 语义色（改用中性色）；
- 两张会一起被读的卡（受管客户端 / 未安装）必须带 `tip` 说明口径，
  且文案里要出现「注册表」或「未安装」这类能自解释的词。

判据刻意粗粒度（颜色 + 是否有说明），因为这里守的是**可读性**，不是排版细节。
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from tests._js_fn import extract_function
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "gui" / "dashboard.html"
NODE = shutil.which("node")


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """抽出函数体。用大括号配平（见 tests/_js_fn.py），不用易失准的正则。"""
    return extract_function(_src(), name)


def _agent(name, *, installed=True, install_state="installed"):
    return {
        "name": name,
        "type": "AI Agent",
        "installed": installed,
        "install_state": install_state,
        "is_agent": True,
    }


SNAP = {
    "agents": [
        _agent("Codex"),
        _agent("WorkBuddy"),
        _agent("Gemini CLI", installed=False, install_state="none"),
        _agent("Windsurf", installed=False, install_state="none"),
        _agent("Zed", installed=False, install_state="none"),
    ],
    "skills": {"skill_count": 7},
    "mcp": {"endpoints": []},
    "mainstream_tools": [],
}


@unittest.skipUnless(NODE, "需要 node 才能执行渲染护栏")
def _render_overview():
    """在 node 里执行真实 `renderOverview`，返回它写入的 innerHTML。"""
    src = _src()
    esc = re.search(r'const escapeHtml = \(v\) =>.*?&#39;"\);', src, re.S).group(0)
    js = "\n".join(
        [
            "const SNAP = " + json.dumps(SNAP) + ";",
            esc,
            _fn("_agentsForPanel"),
            _fn("statCard"),
            _fn("renderOverview"),
            "const holder = { _v: '', set innerHTML(v) { this._v = v; }, get innerHTML() { return this._v; } };",
            "const $ = (id) => (id === 'overview-body' ? holder : { textContent: '', innerHTML: '' });",
            "renderOverview();",
            "process.stdout.write(holder._v);",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overview.js"
        path.write_text(js, encoding="utf-8")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise AssertionError("node 渲染失败：" + proc.stderr[:400])
    return proc.stdout


def _card(html: str, label: str) -> str:
    """取出标注为 ``label`` 的那张 stat-card 的完整 HTML（含 title 属性）。"""
    for m in re.finditer(r'<div title="[^"]*" class="stat-card[^"]*">.*?</div></div>', html, re.S):
        block = m.group(0)
        if f">{label}</div>" in block:
            return block
    raise AssertionError(f"找不到统计卡：{label}")


class OverviewCardWordingTest(unittest.TestCase):
    def test_uninstalled_count_is_not_an_error_color(self):
        html = _render_overview()
        card = _card(html, "未安装")
        self.assertNotIn(
            'class="num err"', card,
            "「未安装」用了 err 红色：管理工具里没装某客户端是正常状态，"
            "红色会把「本机没装」读成「出了问题」",
        )

    def test_managed_clients_card_explains_its_scope(self):
        html = _render_overview()
        card = _card(html, "受管客户端")
        title = re.search(r'title="([^"]*)"', card).group(1)
        self.assertTrue(title.strip(), "「受管客户端」缺少 tip：读者会以为 17 个都是本机在用的")
        self.assertIn("注册表", title)

    def test_uninstalled_card_explains_its_scope(self):
        html = _render_overview()
        card = _card(html, "未安装")
        title = re.search(r'title="([^"]*)"', card).group(1)
        self.assertIn("未安装", title)
        self.assertIn("MCP", title,
                      "tip 应点明「未安装的客户端不进 MCP 页」，这正是引起困惑的地方")

    def test_counts_still_add_up(self):
        """口径没变：受管 = 已安装 + 仅配置 + 未安装。改文案不得改口径。"""
        html = _render_overview()
        nums = [int(m.group(1)) for m in
                re.finditer(r'<div class="num[^"]*">(\d+)</div>', html)]
        self.assertEqual(nums[:4], [5, 2, 0, 3], f"统计卡数值口径变了：{nums[:4]}")


if __name__ == "__main__":
    unittest.main()
