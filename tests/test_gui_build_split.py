"""S10 构建期拆分：源文件保持单文件，发布产物拆分（既有测试零改动）。

`scripts/build_gui.py` 把 `gui/dashboard.html` 的内联 `<script>` 切成
`gui/dist/dashboard.html` + `gui/dist/app.js`。本文件守三类不变量：

1. **产物里没有内联 `<script>`** —— 这是「关掉 CSP `'unsafe-inline'`」的前置条件之一
   （外置脚本后 `script-src` 才可能不再需要 `'unsafe-inline'`；样式仍受 77 处内联
   `style=` 属性约束，见清单的 S2 专节）。顺带这条断言本身也防止「有人图省事
   又把脚本塞回产物」。
2. **拆分无损** —— 把 `<script src="app.js" defer></script>` 换回
   `<script>脚本体</script>` 必须**逐字节还原**源文件。拆分不能丢内容、不能改空白，
   否则发布产物与测试所测的源文件就不是同一个东西了。
3. **与 Tauri 配置对齐** —— `tauri.conf.json` 的 `frontendDist` 指向 `gui/dist`，
   且窗口 `url` 在产物目录里真实存在。这三者（配置、产物、窗口 URL）任一漂移，
   发行构建就会打出一个打不开窗口的包 —— 而这一点只能靠本地断言兜住，
   因为 `tauri build` 不在门禁里跑。

另外测 `--check`：CI 用它判断 `gui/dist/` 是否与源文件同步（防止有人改了源文件却忘了重新构建）。
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests._gui_source import page_source  # noqa: E402

BUILD = ROOT / "scripts" / "build_gui.py"
CONF = ROOT / "src-tauri" / "tauri.conf.json"
DIST = ROOT / "gui" / "dist"
INDEX = DIST / "dashboard.html"
APP_JS = DIST / "app.js"
SCRIPT_TAG = '<script src="app.js" defer></script>'


class BuildSplitTest(unittest.TestCase):
    def setUp(self):
        """每个用例前重建产物，消除用例间的顺序耦合。

        为什么不能用 setUpClass 只建一次：本套件里有会**改动** `gui/dist` 的用例
        （漂移检测用例临时往 app.js 追加内容），若产物只在类级建一次，
        后续用例读到的就是别人留下的中间状态 —— 实测出现过一次偶发失败
        （974 用例 1 failed，重跑即绿）。每例重建约 0.15s，代价可接受，换来确定性。
        """
        r = subprocess.run(
            [sys.executable, str(BUILD)], cwd=ROOT, capture_output=True, text=True
        )
        if r.returncode != 0:
            raise AssertionError(f"构建失败：\n{r.stdout}\n{r.stderr}")

    def test_dist_files_exist(self):
        self.assertTrue(INDEX.is_file(), "缺少 gui/dist/dashboard.html")
        self.assertTrue(APP_JS.is_file(), "缺少 gui/dist/app.js")

    def test_dist_has_no_inline_script(self):
        html = INDEX.read_text(encoding="utf-8")
        inline = re.findall(r"<script(?![^>]*\bsrc=)", html)
        self.assertEqual(inline, [], f"发布产物里仍有内联 <script>：{inline}")

    def test_dist_references_external_script(self):
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn(SCRIPT_TAG, html, "发布产物没有引用外置脚本")

    def test_app_js_carries_the_page_script(self):
        app = APP_JS.read_text(encoding="utf-8")
        # 抽一个真实存在的顶层函数，确认搬过去的是页面脚本本体而不是空文件
        self.assertIn("function renderMcpClients", app)

    def test_split_is_lossless(self):
        """把产物拼回单文件形态，必须与源文件逐字节一致。"""
        html = INDEX.read_text(encoding="utf-8")
        app = APP_JS.read_text(encoding="utf-8")
        rebuilt = html.replace(SCRIPT_TAG, "<script>" + app + "</script>", 1)
        self.assertEqual(rebuilt, page_source(), "拆分不是无损的（内容/空白被改动）")

    # ------------------------------------------------------------ 与 Tauri 配置对齐

    def test_tauri_frontend_dist_points_at_dist(self):
        conf = json.loads(CONF.read_text(encoding="utf-8"))
        frontend = conf["build"]["frontendDist"]
        self.assertEqual(
            frontend.replace("\\", "/"),
            "../gui/dist",
            "frontendDist 未指向拆分产物目录（gui/dist）",
        )

    def test_tauri_before_build_command_builds_the_split(self):
        conf = json.loads(CONF.read_text(encoding="utf-8"))
        cmd = conf["build"].get("beforeBuildCommand", "")
        self.assertIn(
            "build_gui.py",
            cmd,
            "beforeBuildCommand 未调用 build_gui.py —— 发行构建会缺少 gui/dist",
        )

    def test_before_build_command_works_from_either_cwd(self):
        """`beforeBuildCommand` 必须**在两种可能的工作目录下都成功**。

        为什么这条必须测：`tauri-cli` 不在 cargo registry 里（它是 npm 包），
        我们无法从源码确认 hook 的 cwd 是**仓库根**还是 **src-tauri/**；
        而三个构建 workflow 是用 `working-directory: src-tauri` 跑 `tauri build` 的。
        猜错的后果是**三平台发行构建全挂**，且只能在 CI 上发现。

        所以配置里写成「多候选 `||` 链」，本用例把那个字符串**原样**在两个目录各跑一遍，
        把「cwd 是哪个」这个未知量消掉 —— 这样无需 `tauri build` 也能验证接线正确。
        """
        conf = json.loads(CONF.read_text(encoding="utf-8"))
        cmd = conf["build"]["beforeBuildCommand"]

        # 只断言「命令能跑通并产出产物」，不断言「产物本来不存在」——
        # 早期版本会先 rmtree(DIST) 再重建，那会与同进程内读产物的用例竞态，
        # 表现为偶发 1 个失败（实测踩到过）。现在改成：跑完只要产物在即算通过，
        # 再单独断言内容与源文件一致（见 test_split_is_lossless / --check 用例）。
        for cwd in (ROOT, ROOT / "src-tauri"):
            with self.subTest(cwd=str(cwd)):
                r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
                self.assertEqual(
                    r.returncode,
                    0,
                    f"beforeBuildCommand 在 cwd={cwd} 下失败：\n{r.stdout}\n{r.stderr}",
                )
                self.assertTrue(
                    INDEX.is_file(),
                    f"beforeBuildCommand 在 cwd={cwd} 下退出码为 0 但没生成产物",
                )

    def test_tauri_window_url_exists_in_dist(self):
        """窗口 url 必须能在 frontendDist 目录里找到，否则打包出来是个打不开的窗口。"""
        conf = json.loads(CONF.read_text(encoding="utf-8"))
        dist_dir = (CONF.parent / conf["build"]["frontendDist"]).resolve()
        self.assertEqual(dist_dir, DIST.resolve(), "frontendDist 解析后不是 gui/dist")

        urls = [w.get("url") for w in conf["app"]["windows"]]
        self.assertTrue(urls, "配置里没有窗口 url")
        for url in urls:
            self.assertTrue(
                (dist_dir / url).is_file(),
                f"窗口 url={url!r} 在 {dist_dir} 里不存在",
            )

    def test_split_page_actually_runs_like_the_source_page(self):
        """端到端：把拆分产物交给 node 崩溃定位 harness 真跑一遍。

        为什么必须有这条：上面那些断言只证明「产物长对了」，**没有**证明它**跑得起来**。
        而真正会被打进安装包的是拆分产物（`tauri.conf.json` 的 `frontendDist`）——
        源文件跑得起来不等于产物跑得起来。

        harness（`tools/dash_crash_harness.js`）在桩 DOM 下**完整执行**页面脚本、
        真实派发点击，因此能给出「顶层未抛错 + 按钮链路通」这种运行期结论。
        本用例对**源文件**与**拆分产物**各跑一次，要求两者结论一致。
        """
        harness = ROOT / "tools" / "dash_crash_harness.js"
        self.assertTrue(harness.is_file(), "缺少 tools/dash_crash_harness.js")

        reports = {}
        for label, page in (("源文件", ROOT / "gui" / "dashboard.html"), ("拆分产物", INDEX)):
            out = ROOT / ".pytest_cache" / f"_split_e2e_{label}.txt"
            out.parent.mkdir(exist_ok=True)
            r = subprocess.run(
                ["node", str(harness), str(page), str(out)],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(
                r.returncode, 0, f"{label} harness 退出码非 0：\n{r.stdout}\n{r.stderr}"
            )
            reports[label] = out.read_text(encoding="utf-8")

        for label, report in reports.items():
            self.assertIn("顶层执行未抛错", report, f"{label} 顶层脚本执行抛错：\n{report}")
            self.assertIn(
                "全部按钮点击链路端到端通过", report, f"{label} 按钮链路断裂：\n{report}"
            )

    def test_dist_contains_every_referenced_asset(self):
        """产物目录必须**自包含**：页面引用的每个静态资源都要在 dist 里找得到。

        为什么必须有这条：Tauri 只嵌入 `frontendDist` 这一个目录。页面除了 `app.js`，
        还在 `@font-face` 里 `url('assets/fonts/*.woff2')` 引用 3 个字体，它们原本
        只躺在 `gui/assets/`。

        **这是实测踩到的真缺陷**：`frontendDist` 由 `../gui` 改为 `../gui/dist` 后，
        字体不跟着进产物，打出来的包会缺字体（界面回退系统等宽字体 + 控制台 404）。
        修法是构建时把 `gui/assets/` 复制进 `gui/dist/assets/`。
        """
        html = INDEX.read_text(encoding="utf-8")
        refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", html)
        refs += re.findall(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", html)
        checked = 0
        for ref in refs:
            if ref.startswith(("data:", "blob:", "#", "http://", "https://", "//", "/")):
                continue
            rel = ref.split("?", 1)[0].split("#", 1)[0]
            if not rel:
                continue
            checked += 1
            self.assertTrue(
                (DIST / rel).is_file(),
                f"产物缺少页面引用的资源：{rel}（frontendDist 只嵌入 gui/dist）",
            )
        self.assertGreater(checked, 0, "没有解析到任何资源引用，断言失去意义")
        # 字体是当前唯一的外部资源，单独点名，避免将来正则失效却静默通过
        self.assertTrue((DIST / "assets" / "fonts").is_dir(), "产物缺少 assets/fonts")

    def test_check_mode_passes_when_in_sync(self):
        r = subprocess.run(
            [sys.executable, str(BUILD), "--check"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0, f"--check 应通过：\n{r.stdout}\n{r.stderr}")

    def test_check_mode_detects_newline_drift(self):
        """`--check` 必须能抓到「只差换行」的漂移。

        Round 32 的真实教训：`--check` 原用 `Path.read_text()` 比较，而 read_text
        走 universal newlines，会把 CRLF 归一成 LF —— 于是 Windows 上生成的
        CRLF 产物会被判定为「与源文件同步」，漂移检测形同虚设。
        改成按字节比较后才能真正抓到。这条用例把该行为钉住。
        """
        original = APP_JS.read_bytes()
        try:
            APP_JS.write_bytes(original.replace(b"\n", b"\r\n"))
            r = subprocess.run(
                [sys.executable, str(BUILD), "--check"], cwd=ROOT, capture_output=True, text=True
            )
            self.assertNotEqual(r.returncode, 0, "CRLF 漂移未被 --check 抓到")
        finally:
            APP_JS.write_bytes(original)

    def test_dist_artifacts_are_lf_only(self):
        """产物必须是纯 LF —— 否则跨平台构建结果不一致。

        `write_text` 默认 `newline=None` 会做换行翻译，在 Windows 上把 \\n
        写成 \\r\\n。脚本已显式 `newline="\\n"`；这条断言保证它不被改回去。
        """
        for path in (INDEX, APP_JS):
            with self.subTest(path=path.name):
                self.assertNotIn(
                    b"\r",
                    path.read_bytes(),
                    f"{path.name} 含 CR —— 产物换行随平台漂移了",
                )

    def test_build_workflows_declare_python(self):
        """三个打包 workflow 必须显式装 Python。

        Round 32 的 CI 事故：`beforeBuildCommand` 跑 `scripts/build_gui.py`（Python），
        但 `build-{linux,macos,windows}.yml` 都没装 Python —— macOS/Linux runner
        自带 python3 侥幸通过，Windows 上四段 `||` 全失败、`tauri build` 中止
        （HEAD 7fb4d22 的 Build Windows App = failure）。
        构建依赖注入 CI 配置后，这条断言防止它再被悄悄漏掉。
        """
        for name in ("build-linux", "build-macos", "build-windows"):
            wf = ROOT / ".github" / "workflows" / f"{name}.yml"
            with self.subTest(workflow=name):
                self.assertTrue(wf.is_file(), f"{name}.yml 不存在")
                text = wf.read_text(encoding="utf-8")
                self.assertIn(
                    "actions/setup-python@",
                    text,
                    f"{name}.yml 未声明 Python —— beforeBuildCommand 里的 "
                    "scripts/build_gui.py 将无解释器可跑（Windows 上会直接失败）",
                )
                # gui/dist 被 .gitignore 排除，全新 checkout 时不存在，
                # 因此 CI 必须显式先跑一次生成 + --check（而不是只靠
                # Tauri 的 beforeBuildCommand —— 那样失败时只剩一个 exit code）。
                self.assertIn(
                    "Generate frontend dist",
                    text,
                    f"{name}.yml 没有显式生成 gui/dist 的步骤",
                )

    def test_check_mode_detects_drift(self):
        """临时改动产物后 `--check` 必须报不同步，然后恢复。"""
        original = APP_JS.read_text(encoding="utf-8")
        try:
            APP_JS.write_text(original + "\n// drift\n", encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(BUILD), "--check"], cwd=ROOT, capture_output=True, text=True
            )
            self.assertNotEqual(r.returncode, 0, "--check 未发现产物漂移")
        finally:
            APP_JS.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
