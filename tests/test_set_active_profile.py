"""--set-active-profile / --set-auto-discover CLI 命令测试。

PRD §10 #1：此前只有只读展示，缺后端写命令。本文件验证两条新命令的
写入、校验与早返回行为。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = str(ROOT / "core")


def _run_cli(args, cwd):
    r = subprocess.run(
        [sys.executable, str(ROOT / "scan.py")] + args,
        capture_output=True, text=True, cwd=cwd, timeout=60,
        env={**os.environ, "PYTHONPATH": CORE},
    )
    return r


class SetActiveProfileTest(unittest.TestCase):
    """--set-active-profile 写入 overlay + 校验 key 存在性。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # overlay 文件（必须在 config profile_sources 里且真实存在，否则 _overlay_target fallback 到全局）
        self.overlay = Path(self.tmp) / "data" / "local_overrides.yaml"
        self.overlay.parent.mkdir(parents=True, exist_ok=True)
        self.overlay.write_text("{}", encoding="utf-8")
        (Path(self.tmp) / "config.yaml").write_text(
            "profiles:\n"
            "  hermes-home:\n"
            "    name: hermes\n"
            "    transport: streamable-http\n"
            "  k8s-uat:\n"
            "    name: K8s-uat\n"
            "    transport: streamable-http\n"
            "settings:\n"
            "  active_profile: hermes-home\n"
            f"profile_sources:\n"
            f"  - {self.overlay}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_set_existing_key(self):
        """写入已存在的 key 应成功（exit 0），overlay 含 active_profile。"""
        r = _run_cli(["--config", str(Path(self.tmp) / "config.yaml"),
                       "--set-active-profile", "k8s-uat"], self.tmp)
        self.assertEqual(r.returncode, 0, f"exit={r.returncode}, stderr={r.stderr[:200]}")
        self.assertIn("active_profile = k8s-uat", r.stdout)
        # overlay 写入了
        overlay = Path(self.tmp) / "data" / "local_overrides.yaml"
        self.assertTrue(overlay.exists(), "overlay 文件应被创建")

    def test_set_nonexistent_key_rejected(self):
        """写入不存在的 key 应拒绝（exit 2）。"""
        r = _run_cli(["--config", str(Path(self.tmp) / "config.yaml"),
                       "--set-active-profile", "nonexistent"], self.tmp)
        self.assertEqual(r.returncode, 2, f"应 exit 2，实际 {r.returncode}")
        self.assertIn("不存在", r.stdout)

    def test_clear_active_profile(self):
        """空字符串清除活动端点（exit 0）。"""
        r = _run_cli(["--config", str(Path(self.tmp) / "config.yaml"),
                       "--set-active-profile", ""], self.tmp)
        self.assertEqual(r.returncode, 0, f"exit={r.returncode}")
        self.assertIn("已清除", r.stdout)


class SetAutoDiscoverTest(unittest.TestCase):
    """--set-auto-discover 写入 overlay。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.overlay = Path(self.tmp) / "data" / "local_overrides.yaml"
        self.overlay.parent.mkdir(parents=True, exist_ok=True)
        self.overlay.write_text("{}", encoding="utf-8")
        (Path(self.tmp) / "config.yaml").write_text(
            "auto_discover:\n"
            "  enabled: true\n"
            "  scan_paths:\n"
            "    - ~/.config/*/skills\n"
            "settings:\n"
            "  active_profile: ''\n"
            f"profile_sources:\n"
            f"  - {self.overlay}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_disable(self):
        """enabled=false 写入 overlay（exit 0）。"""
        r = _run_cli(["--config", str(Path(self.tmp) / "config.yaml"),
                       "--set-auto-discover", "enabled=false"], self.tmp)
        self.assertEqual(r.returncode, 0, f"exit={r.returncode}")
        self.assertIn("auto_discover.enabled = False", r.stdout)

    def test_enable(self):
        """enabled=true 写入 overlay（exit 0）。"""
        r = _run_cli(["--config", str(Path(self.tmp) / "config.yaml"),
                       "--set-auto-discover", "enabled=true"], self.tmp)
        self.assertEqual(r.returncode, 0, f"exit={r.returncode}")
        self.assertIn("auto_discover.enabled = True", r.stdout)

    def test_unsupported_field_rejected(self):
        """不支持的字段应拒绝（exit 2）。"""
        r = _run_cli(["--config", str(Path(self.tmp) / "config.yaml"),
                       "--set-auto-discover", "scan_paths=~/.test"], self.tmp)
        self.assertEqual(r.returncode, 2, f"应 exit 2，实际 {r.returncode}")

    def test_written_value_takes_effect_on_reload(self):
        """写后生效回归（v0.30.0 修复的断链）。

        v0.28.0 的 ``--set-auto-discover`` 把 enabled 写进 overlay，但
        ``apply_profile_sources`` 此前不合并该键 —— ``load_config`` 读回的
        仍是 trunk 值，开关形同虚设。本用例守住「写 → 重新加载 → 生效」
        全链路（trunk=false / overlay=true 的暴露组合）。
        """
        cfg_path = Path(self.tmp) / "config.yaml"
        # trunk 关、overlay 开：断链时 load_config 会读回 False
        cfg_path.write_text(
            "auto_discover:\n"
            "  enabled: false\n"
            f"profile_sources:\n"
            f"  - {self.overlay}\n",
            encoding="utf-8",
        )
        self.overlay.write_text("auto_discover:\n  enabled: true\n", encoding="utf-8")

        sys.path.insert(0, str(ROOT / "core"))
        from scanner import load_config  # noqa: E402

        cfg = load_config(str(cfg_path))
        self.assertTrue(
            (cfg.get("auto_discover") or {}).get("enabled", False),
            "overlay 的 auto_discover.enabled=true 未生效（apply_profile_sources 断链回归）",
        )


if __name__ == "__main__":
    unittest.main()
