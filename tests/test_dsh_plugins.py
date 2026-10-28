"""DSH 插件清单（core/dsh_plugins.py）与「DSH 插件」页的门禁断言。

两个重点：

1. **判定正确**：DSH 的插件真相分散在 `dependencies`（装了什么）、
   `dsh.profile.bundles`（启用清单）、`cordis.patch.yml`（补丁层）三处。只看一处
   会得出「装了=在用」或漏掉「装了没启用」。这里用**真实临时目录**构造这三种
   情形，不 mock 文件系统——mock 掉就等于把要验的判定删了。

2. **绝不回显密钥**：真实 `cordis.patch.yml` 里有明文 `apiKey`（本机实测）。
   构造一个含 `sk-xxx` 的样本，断言整个输出（JSON 与文本两种出口）里都查不到它。
   这条比功能正确性更重要：一个会吐密钥的页面比没有这个页面危险得多。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import dsh_plugins as dsh  # noqa: E402

GUI = ROOT / "gui" / "dashboard.html"

FAKE_KEY = "sk-CANARY-abcdef0123456789"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class _Tree:
    """搭一个含三种插件状态的假 DSH 目录树。"""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="dsh-"))
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()

    def profile(self, name, *, deps, bundles, patch=None, installed=None):
        p = self.profiles / name
        p.mkdir(parents=True, exist_ok=True)
        _write(p / "package.json", json.dumps(
            {"name": f"profile-{name}", "dependencies": deps,
             "dsh": {"profile": {"bundles": bundles}}},
            ensure_ascii=False, indent=2))
        if patch is not None:
            _write(p / "cordis.patch.yml", patch)
        for pkg, version in (installed or {}).items():
            _write(p / "node_modules" / pkg / "package.json",
                   json.dumps({"name": pkg, "version": version}))
        return p

    def cleanup(self):
        subprocess.run(["rm", "-rf", str(self.root)], timeout=30)


class StateClassificationTest(unittest.TestCase):
    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)

    def test_three_states_are_distinguished(self):
        local_src = self.tree.root / "my-plugin"
        local_src.mkdir()
        self.tree.profile(
            "desktop",
            deps={
                "@deepseek-ai/dsh-base": "^1.0.0",
                "plug-enabled": "^1.0.0",
                "plug-installed-only": "^1.0.0",
                "plug-broken": f"link:{self.tree.root / 'gone'}",
                "plug-local": f"link:{local_src}",
            },
            bundles=["@deepseek-ai/dsh-base", "plug-enabled", "plug-broken", "plug-local"],
            installed={"plug-enabled": "1.2.3", "plug-installed-only": "0.1.0",
                       "plug-local": "9.9.9"},
        )
        out = dsh.scan(str(self.tree.profiles))
        by = {p["name"]: p for p in out["profiles"][0]["plugins"]}

        self.assertEqual("enabled", by["plug-enabled"]["state"])
        self.assertEqual("1.2.3", by["plug-enabled"]["version"])
        self.assertEqual("installed", by["plug-installed-only"]["state"],
                         "装了但不在 bundles 里，必须单列而不是算启用")
        self.assertEqual("broken", by["plug-broken"]["state"],
                         "link 目标不存在必须是 broken，不能因为『在 bundles 里』就算启用")
        self.assertEqual("local", by["plug-local"]["kind"])

    def test_builtin_scope_detected(self):
        self.tree.profile("web", deps={"@deepseek-ai/dsh-web-app": "^2.0.0"},
                          bundles=["@deepseek-ai/dsh-web-app"])
        out = dsh.scan(str(self.tree.profiles))
        plug = out["profiles"][0]["plugins"][0]
        self.assertEqual("builtin", plug["kind"])

    def test_link_target_gone_is_broken_even_if_installed(self):
        """link 目标已删除、但 node_modules 里仍有残壳 —— 仍必须判 broken。

        这是最容易被漏的一种：pnpm 的 link 依赖在源码目录被删/挪走之后，
        `node_modules/<name>` 往往还留着（指过去的符号链接或旧副本），于是
        「有 version」这条判据会放行，插件看着是「已启用」而 DSH 载入必失败。
        所以 broken 必须独立判 link 目标存在性，不能只靠 version 缺失兜底。
        """
        p = self.tree.profile(
            "desktop",
            deps={"plug-local": f"link:{self.tree.root / 'gone-dir'}"},
            bundles=["plug-local"],
            installed={"plug-local": "1.0.0"},   # 有版本，故意不给它兜底机会
        )
        self.assertTrue((p / "node_modules" / "plug-local" / "package.json").exists())
        out = dsh.scan(str(self.tree.profiles))
        plug = out["profiles"][0]["plugins"][0]
        self.assertEqual("1.0.0", plug["version"], "前提：版本是读得到的")
        self.assertEqual("broken", plug["state"],
                         "link 目标不存在时，即使有 version 也必须判 broken")

    def test_summary_counts_are_separate_not_merged(self):
        self.tree.profile("p1", deps={"a": "^1", "b": "^2"}, bundles=["a"],
                          installed={"a": "1.0.0", "b": "1.0.0"})
        out = dsh.scan(str(self.tree.profiles))
        s = out["summary"]
        self.assertEqual(2, s["plugins"])
        self.assertEqual(1, s["enabled"])
        self.assertEqual(1, s["installed_only"])
        self.assertEqual(0, s["broken"])

    def test_node_modules_is_not_a_profile(self):
        # profiles/node_modules 是 pnpm 依赖树，不是 profile
        (self.tree.profiles / "node_modules" / "x").mkdir(parents=True)
        self.tree.profile("desktop", deps={}, bundles=[])
        out = dsh.scan(str(self.tree.profiles))
        self.assertEqual(["desktop"], [p["name"] for p in out["profiles"]])
        self.assertEqual(1, out["summary"]["profiles"])

    def test_missing_profiles_dir_reports_reason(self):
        out = dsh.scan(str(self.tree.root / "nope"))
        self.assertEqual([], out["profiles"])
        self.assertIn("未找到 DSH profile 目录", out["reason"])


class PatchStatsTest(unittest.TestCase):
    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)

    def test_patch_structure_counted(self):
        patch = """- id: vision
  config:
    provider: custom
- id: some-plugin
  disabled: true
- insert:
    - id: extra
"""
        self.tree.profile("desktop", deps={}, bundles=[], patch=patch)
        out = dsh.scan(str(self.tree.profiles))
        p = out["profiles"][0]["patch"]
        self.assertTrue(p["exists"])
        self.assertEqual(3, p["entries"])
        self.assertEqual(1, p["disables"])
        self.assertEqual(1, p["inserts"])

    def test_missing_patch_reported_as_absent(self):
        self.tree.profile("desktop", deps={}, bundles=[])
        out = dsh.scan(str(self.tree.profiles))
        self.assertFalse(out["profiles"][0]["patch"]["exists"])


class SecretsNeverLeakTest(unittest.TestCase):
    """最要紧的一条：patch 层的 config 值绝不回显。"""

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)
        patch = f"""- id: vision
  config:
    provider: custom
    apiKey: {FAKE_KEY}
    baseURL: https://example.invalid/v1
"""
        self.tree.profile("desktop", deps={"dsh-plugin-vision": "^0.1.0"},
                          bundles=["dsh-plugin-vision"], patch=patch,
                          installed={"dsh-plugin-vision": "0.1.0"})

    def test_scan_output_has_no_secret(self):
        out = dsh.scan(str(self.tree.profiles))
        blob = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(FAKE_KEY, blob)
        self.assertNotIn("sk-", blob, "输出里连 sk- 前缀都不该出现")
        self.assertNotIn("example.invalid", blob, "baseURL 这类 config 值同样不该出现")
        self.assertTrue(out["secrets_redacted"])

    def test_text_output_has_no_secret(self):
        out = dsh.scan(str(self.tree.profiles))
        env = dict(os.environ, PYTHONPATH=str(ROOT / "core"))
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), "--dsh-plugins",
             "--dsh-home", str(self.tree.root)],
            capture_output=True, text=True, env=env, timeout=120, cwd=str(ROOT))
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertNotIn(FAKE_KEY, proc.stdout)
        self.assertNotIn("sk-", proc.stdout)
        self.assertIn("脱敏", proc.stdout)
        self.assertIsNotNone(out)


class DshPageGuiTest(unittest.TestCase):
    """GUI 侧：新页必须真的接进来，而不是只有一段死代码。"""

    @classmethod
    def setUpClass(cls):
        cls.body = GUI.read_text(encoding="utf-8")

    def test_nav_item_and_section_exist(self):
        self.assertIn('data-page="dsh"', self.body)
        self.assertIn('id="page-dsh"', self.body)
        self.assertIn('id="nav-dsh"', self.body)

    def test_page_registered_in_pages_map(self):
        self.assertIn('dsh: "page-dsh"', self.body)

    def test_cli_is_called_with_json(self):
        self.assertIn('"--dsh-plugins", "--format", "json"', self.body)

    def test_three_states_rendered_separately(self):
        for state in ("enabled", "installed", "broken"):
            self.assertIn(f"{state}:", self.body, f"缺少 {state} 状态映射")
        self.assertIn("装了未启用", self.body)
        self.assertIn("来源失效", self.body)

    def test_page_does_not_render_config_values(self):
        # 页面只能显示 patch 的结构统计，不得渲染 config 内容
        self.assertIn('patch 值已脱敏', self.body)
        self.assertNotIn(".config", self.body.split("function renderDshPlugins")[1][:4000],
                         "渲染函数里不应触碰 config 字段（可能含密钥）")

    def test_auto_load_on_page_switch(self):
        self.assertIn('if (page === "dsh" && !DSH_DATA) loadDshPlugins();', self.body)

    def test_rust_allowlist_contains_flag(self):
        lib = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertIn('"--dsh-plugins"', lib,
                      "不在 Rust 白名单里，GUI 调用会被安全边界拦下")

    def test_nav_item_lives_in_manage_group(self):
        """DSH 插件必须归属「管理」组，而不是「系统」组。

        分组在 DOM 里是**隐式**的：`applyNavGroup()` 从 `.nav-group-label` 的
        下一个兄弟节点起，把所有 `.nav-item` 都当成该组的成员，直到遇到下一个
        `.nav-group-label`。所以「放在哪个分组」完全由 nav 内的**元素顺序**决定，
        没有任何显式归属属性可查——改顺序就会静默改变语义，必须用顺序断言守住。

        判据（见 docs/DESIGN.md §2.3g）：管理组各项都是「本工具去检查和管理的
        对象」（各自有清单与启用状态）；系统组的「变更详情」是审计输出、「设置」
        是本工具通用配置。DSH 插件是「装了哪些、哪些在生效」的资源清单，与
        Skills/MCP 同质，因此必须落在「管理」组内。

        本断言会在三种回归下失败：
          1) 把 nav-dsh 挪回「系统」组（变更详情之后）；
          2) 把「系统」组标签移到 DSH 插件之前；
          3) 删掉分组标签导致分组语义消失。
        """
        nav_start = self.body.find('<nav class="nav">')
        nav_end = self.body.find("</nav>", nav_start)
        self.assertNotIn(-1, (nav_start, nav_end), "找不到侧栏 nav 块，断言失效")
        nav = self.body[nav_start:nav_end]

        manage_at = nav.find('data-group="manage"')
        system_at = nav.find('data-group="system"')
        dsh_at = nav.find('id="nav-dsh"')
        for name, pos in (("管理组标签", manage_at), ("系统组标签", system_at),
                          ("DSH 插件导航项", dsh_at)):
            self.assertNotEqual(-1, pos, f"侧栏里找不到{name}")

        self.assertLess(
            manage_at, dsh_at,
            "DSH 插件排到了「管理」组标签之前 —— 它不在管理组里")
        self.assertLess(
            dsh_at, system_at,
            "DSH 插件落到了「系统」组标签之后 —— 它被归入了系统组。"
            "分组由 DOM 顺序隐式决定（applyNavGroup 按兄弟节点顺序收集 nav-item），"
            "所以位置即语义。若确实要改归属，请同步改 docs/DESIGN.md §2.3g 与本断言。")

    def test_nav_item_precedes_changes_in_dom(self):
        """「变更详情」属于系统组，DSH 插件不应再排在它之后。

        这条与上一条互补：上一条守「组边界」，这条守「组内相对位置」。二者分开的
        原因是失败信息不同——一个说「跨组了」，一个说「组内顺序变了」，便于定位。
        """
        nav_start = self.body.find('<nav class="nav">')
        nav = self.body[nav_start:self.body.find("</nav>", nav_start)]
        self.assertLess(
            nav.find('id="nav-dsh"'), nav.find('id="nav-changes"'),
            "DSH 插件排在了「变更详情」之后 —— 两页都将在系统组内或顺序错乱")

    def test_nav_count_badge_present_like_siblings(self):
        """DSH 插件必须带 `.count` 徽标，与同组四项保持同一视觉语言。

        回归背景：该项曾被移入管理组却没有徽标，于是同组五项里四项有数字、
        一项空白 —— 用户会误以为「这一项没数据/没加载出来」，而不是「它本来
        就没有计数」。徽标的有无是**分组归属完整性的信号**。
        """
        self.assertIn('id="count-dsh"', self.body, "DSH 插件导航项缺少 count 徽标")
        # 与同组各项同构：nav-item 内紧跟文字的 span.count + 唯一 id
        for sibling in ("count-agents", "count-skills", "count-mcp", "count-hooks"):
            self.assertIn(f'id="{sibling}"', self.body,
                          f"同组基准项 {sibling} 缺失，本断言的前提已不成立")

    def test_nav_count_uses_plugin_total_not_enabled(self):
        """徽标取 `summary.plugins`（总数），不得取 `summary.enabled`（启用数）。

        口径依据 docs/DESIGN.md §2.3g：「管理组五个导航项的计数徽标显示该页
        要管理的对象**总数**」。若改成 enabled，DSH 会显示 12 而页面顶部写
        「共 16 个插件」，同组其余四项也都是总数 —— 口径立刻不一致。
        """
        fn = self._fn("setDshNavCount")
        self.assertIn("(d.summary || {}).plugins", fn,
                      "徽标未取 summary.plugins —— 与同组四项的「总数」口径不符")
        self.assertNotIn("(d.summary || {}).enabled", fn,
                         "徽标取成了 summary.enabled —— 该值应在页面内展示，不是导航计数")

    def test_nav_count_failure_shows_dash_not_zero(self):
        """读取失败时必须显示「-」而不是 0。

        `0` 的语义是「确实一个插件都没有」；失败是「不知道有几个」。二者混淆会
        把「DSH 未安装」误读成「装了但没有插件」——这正是本页要防的那类误判。

        占位符必须是**普通连字符**（U+002D）而非 em-dash（U+2014）：DESIGN.md §3
        禁用 em-dash 作可见文案，徽标数字位也属可见文案。这里同时断言「用了
        "-"」与「没有用 em-dash」，防止有人为了视觉宽度又换回去。
        """
        fn = self._fn("setDshNavCount")
        self.assertIn('"-"', fn, "失败态未回退到「-」，会与「0 个插件」混淆")
        self.assertNotIn("\u2014", fn, "失败态用了 em-dash，违反 DESIGN.md §3")
        # 成功分支必须走 plugins，失败分支必须走 -：两条路径都要有
        self.assertIn("d.error", fn, "未把 error 计入失败判定")
        self.assertIn("profiles", fn, "未把「没有 profile」计入失败判定")

        load_fn = self._fn("loadDshPlugins")
        # 两条失败路径（CLI 非零 / 返回无法解析）都必须重置徽标
        self.assertEqual(
            2, load_fn.count("setDshNavCount(null)"),
            "loadDshPlugins 的两条失败路径未都重置徽标 —— 残留旧数字会谎报结果")

    def test_plugins_deduped_across_profiles(self):
        """同一插件跨 profile 只显示一行，不得按 profile 重复列出。

        实测 `@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-web-app` 在 desktop 与
        web 两个 profile 里都被声明。逐 profile 分卡片会让它们各出现两次
        （16 条 vs 14 个唯一插件），看起来像装了两份，也无法横向比较。

        断言强度说明：只检查「存在 byName / new Map()」这类字符串是无效的——
        把聚合结果替换成空数组时那些字面量仍在，测试照样通过（反向验证实测
        确认过这个漏洞）。因此这里进一步绑定**数据结构关系**：聚合表以插件名
        为键、逐条 push 进 states、且行数据取自聚合结果（而非某单 profile）。
        """
        fn = self._fn("renderDshPlugins")
        # 1) 聚合表以插件名为键
        self.assertIn("byName.get(plug.name)", fn,
                      "未按插件名查聚合表 —— 无法把同名插件合并到同一行")
        self.assertIn("byName.set(plug.name, row)", fn, "未按插件名写入聚合表")
        # 2) 各 profile 的状态收进同一行的 states 数组
        self.assertIn("row.states.push", fn,
                      "未把各 profile 的状态收进同一行 —— 去重后会丢 profile 归属")
        # 3) 行数据必须由聚合结果生成（若改成遍历 p.plugins 就会重复出行）
        self.assertIn("Array.from(byName.values())", fn,
                      "行数据未取自聚合结果 —— 同一插件会按 profile 重复出现")
        self.assertIn("plugins.map(", fn, "表格行未由去重后的聚合结果生成")

    def test_profile_attribution_kept_after_dedup(self):
        """去重后必须仍能看出某个插件属于哪些 profile。

        去重的代价是丢失「哪个 profile 装了什么」，必须用 profile 列补回来，
        否则用户无法判断「这个插件到底在哪个 profile 里生效」。
        """
        fn = self._fn("renderDshPlugins")
        self.assertIn("<th>profile</th>", fn, "表头缺少 profile 列 —— 去重后丢失归属信息")
        self.assertIn("profCell", fn, "未渲染 profile 单元格")

    def test_inconsistent_state_picks_worst_and_labels_it(self):
        """跨 profile 状态不一致时，取最严重状态并显式标注「不一致」。

        若静默取其一（例如取第一个 profile 的 enabled），则「web 下已失效、
        desktop 下正常」会被误读成全平台正常 —— 这正是本页要防的误判。
        broken > installed > enabled 是安全优先的排序。
        """
        fn = self._fn("renderDshPlugins")
        self.assertIn("SEVERITY", fn, "缺少状态严重性表，无法取最严重状态")
        for state in ("enabled", "installed", "broken"):
            self.assertIn(f"{state}:", fn, f"严重性表缺少 {state}")
        self.assertIn("各 profile 不一致", fn,
                      "状态分歧时未显式标注 —— 用户会以为各 profile 一致")

    def test_empty_source_column_is_merged_into_kind(self):
        """「来源」不再作为独立列；有值时并入「类型」列。

        实测 16 个插件无一有 source_path，该列长期全空却固定占宽。改为并入
        类型列后，常见情况下表格少一列，且 link: 依赖的溯源信息不丢失。
        """
        fn = self._fn("renderDshPlugins")
        self.assertNotIn("<th>来源</th>", fn,
                         "「来源」仍是独立列 —— 实测该列恒空，白占宽度")
        self.assertIn("kindCell", fn, "未把来源并入类型列")
        self.assertIn("r.source_path", fn,
                      "类型列未处理 source_path，link: 依赖的溯源信息会丢失")

    def _fn(self, name):
        """截取某个 JS 函数的源码体（到下一个顶层 function 之前）。"""
        start = self.body.find(f"function {name}(")
        self.assertNotEqual(-1, start, f"找不到函数 {name}()")
        nxt = self.body.find("\nfunction ", start + 1)
        return self.body[start:nxt if nxt != -1 else len(self.body)]


if __name__ == "__main__":
    unittest.main()
