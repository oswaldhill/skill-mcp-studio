"""`--set-setting` 必须是独立早返回出口（2026-10-12 用户截图反馈）。

## 为什么需要这条门禁

用户截图：设置页保存 Hook 事件时报「保存 Hook 事件失败」，错误详情是**整段
1600 字符的技能扫描报告**。根因不是写入失败 —— CLI 明明打印了
`✅ hook_events = [...]`，但它是**主流程末尾**的一段，于是：

1. 一次纯设置写入会顺带把 11 阶段审计跑完（慢、输出噪声大）；
2. 退出码**继承审计结论** —— 本机有 6 个技能目录缺失，`result_ok` 为假，
   `main()` 返回 1 → GUI 判「保存失败」并把 stdout 当错误详情展示。

修法：与 `--get-setting` / `--list-hooks` / `--snapshot` 同为**早返回出口**，
退出码只反映写入本身。本文件把这两条钉死，防止回退成「主流程末尾的一段」。
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
SCAN = ROOT / "scan.py"


def _run(args, **kw):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "core")
    return subprocess.run([sys.executable, str(SCAN)] + args,
                          capture_output=True, text=True, cwd=str(ROOT), env=env, **kw)


class SetSettingEarlyReturnTest(unittest.TestCase):
    def test_scan_py_has_early_return_route(self):
        """静态判据：早期出口区必须有 --set-setting 路由，且主流程不应再有旧段。

        取「早返回区」= `--get-setting` 路由所在位置；`--set-setting` 必须在它
        附近（同一个早返回块），而不是落在文件后段的主流程里。
        """
        src = SCAN.read_text(encoding="utf-8")
        self.assertIn("_run_set_setting(args, config_path)", src,
                      "缺少 --set-setting 的早返回路由")
        i_route = src.index('getattr(args, "set_setting", None)')
        i_get = src.index('getattr(args, "get_setting", None)')
        self.assertLess(abs(i_route - i_get), 800,
                        "--set-setting 路由必须与 --get-setting 同处早期出口区")
        self.assertNotIn("    if args.set_setting:\n", src,
                         "主流程末尾的旧 set_setting 段应已删除（否则会跑两遍）")

    def test_cli_modes_treats_set_setting_as_explicit(self):
        """`resolve_modes` 必须把 set_setting 视为显式模式。

        否则它会连带启用 skills/mcp/hooks 默认检查 —— 那正是退出码被审计结论
        污染、以及输出里混入整段扫描报告的来源。
        """
        from cli_modes import resolve_modes  # noqa: E402

        class _A:
            def __init__(self, **kw):
                for n in ("full skills mcp hooks probe_mcp report sync clean push fix "
                          "fix_skills fix_mcp remove_legacy_mcp setup_all hermes "
                          "ai_memory all_profiles").split():
                    setattr(self, n, False)
                for k, v in kw.items():
                    setattr(self, k, v)

        a = resolve_modes(_A(set_setting="hook_events=Stop"))
        self.assertFalse(a.skills or a.mcp or a.hooks,
                         "set_setting 被当成隐式模式，会连带跑 skills/mcp/hooks 检查")

    def test_exit_code_reflects_write_not_audit(self):
        """真跑一次：写入必须退出 0，且输出里不得混入审计报告。

        用临时配置路径不现实（CLI 固定写仓库 config.yaml），故这里对**真实
        config.yaml 写回它当前的值**（幂等，不改变内容），只验证退出码与输出。
        """
        import yaml
        cur = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        val = ",".join(cur["settings"]["hook_events"])
        r = _run(["--set-setting", "hook_events=" + val])
        self.assertEqual(r.returncode, 0,
                         f"--set-setting 应退出 0，实际 {r.returncode}；stdout 尾部：\n{r.stdout[-600:]}")
        for noise in ("Skills 统一化检查报告", "Phase 1", "Phase 7", "frontmatter 契约审计"):
            self.assertNotIn(noise, r.stdout,
                             f"--set-setting 输出混入了审计报告（{noise}）—— 说明它又在跑主流程")

    def test_rejects_unknown_key_with_exit_2(self):
        r = _run(["--set-setting", "not_a_key=1"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("不支持的设置键", r.stdout)


if __name__ == "__main__":
    unittest.main()
