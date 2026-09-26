"""R11/R14 回归：配置写入必须落在 overlay，临时文件列表不得混入提示串。

R11（``git_sync.fix_unified_dir``）：此前用 ``yaml.dump`` 整文件回写版本受控的
trunk ``config.yaml`` —— 既把个人机器路径写进受控文件，又丢掉全部注释与键序。
现在改为委托 ``config_store.set_unified_dir``（写进 gitignored overlay）。

R14（``workspace_cleaner_read.scan_temp_files``）：截断时把
``"... (更多省略)"`` 塞进返回值，而调用方用 ``len()`` 当计数 ——
``temp_file_count`` 因此恒偏大 1，该字符串还会被当成一个路径参与渲染。

**隔离要点（踩过的坑）**：``config_store._overlay_target`` 读的是传入 config 的
``profile_sources``，取「第一个已存在的 overlay 文件」。如果测试只把 config 拷进
临时目录、却没有让 ``profile_sources`` 指向临时目录内的 overlay，写入就会落到
**仓库真实**的 ``data/local_overrides.yaml`` 上（污染开发者本地配置）。
所以这里显式构造 ``profile_sources`` 指向临时 overlay。
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import workspace_cleaner_read  # noqa: E402


class ScanTempFilesTruncationTest(unittest.TestCase):
    def test_truncation_keeps_only_real_paths(self):
        """超过 50 个时截断，但返回值必须全是真实路径、且不含提示串。"""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            for i in range(60):
                Path(d, f"f{i}.log").write_text("x", encoding="utf-8")

            files = workspace_cleaner_read.scan_temp_files(d)

            self.assertEqual(len(files), 50, "上限应为 50")
            for f in files:
                self.assertNotIn("省略", f, "提示串不得混进路径列表（会让计数偏大 1）")
                self.assertTrue(os.path.isabs(f), f"应为绝对路径: {f}")


class FixUnifiedDirWritesOverlayTest(unittest.TestCase):
    def test_trunk_is_untouched_and_value_lands_in_overlay(self):
        """trunk config.yaml 必须原样保留（含注释与键序），值写进 overlay。"""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d, "config.yaml")
            overlay = Path(d, "overlay.yaml")
            # 关键：让 profile_sources 指向临时目录内**已存在**的 overlay，
            # 这样 _overlay_target() 不会去碰仓库的 data/local_overrides.yaml。
            overlay.write_text("existing_key: 1\n", encoding="utf-8")
            original = (
                "# 这是注释\n"
                "unified_skills_dir: ~/old/path\n"
                "# 键序也要保住\n"
                "other_key: 1\n"
                f"profile_sources:\n  - {overlay}\n"
            )
            cfg.write_text(original, encoding="utf-8")

            code = (
                "import sys, os, yaml;"
                f"sys.path.insert(0, {str(CORE)!r});"
                "import git_sync;"
                "r = git_sync.fix_unified_dir(os.environ['CFG']);"
                "print(r.get('fixed')); print(r.get('overlay_path'));"
                "print(open(os.environ['CFG'], encoding='utf-8').read() == os.environ['ORIG'])"
            )
            proc = subprocess.run(
                [sys.executable, "-c", code],
                env=dict(os.environ, CFG=str(cfg), ORIG=original),
                capture_output=True, text=True, cwd=str(d),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
            lines = proc.stdout.strip().splitlines()
            self.assertEqual(lines[0], "True", f"应成功: {proc.stdout}")
            self.assertEqual(Path(lines[1]).resolve(), overlay.resolve(),
                             "写入目标必须是 overlay，而不是 trunk")
            self.assertEqual(lines[2], "True", "trunk config.yaml 被改动了")
            self.assertEqual(cfg.read_text(encoding="utf-8"), original,
                             "trunk 的注释与键序必须完整保留")


if __name__ == "__main__":
    unittest.main()
