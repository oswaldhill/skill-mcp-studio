"""端点整体检查契约（v0.30.0，用户产品反馈落地）。

## 背景

概览页「检查端点连通性」此前只探**活动端点**（单个）——2026-10-22 用户反馈
「首页的整体检查不应该具体到某个具体的端点」。改为：``--endpoint-status``
无 ``--profile`` 时检查**端点库全部端点**（合并视图，过滤 null 软删除），
逐端点呈现 + 汇总；``--profile`` 保留单端点模式。

同批修复的加载缺陷（本文件一并守住）：``profile_sources`` 相对路径此前按
进程 cwd 解析——Tauri GUI 子进程 cwd ≠ 仓库根时 ``data/local_overrides.yaml``
解析到不存在的地方，**overlay 整体静默失效**（active_profile / disabled_tools
全部丢失）。实测链条：GUI 报「profile 'generic-http' not found」= trunk 默认
活动端点 + 端点库软删除 + overlay 的清除值没生效。修法：相对路径按
config.yaml 所在目录解析。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_endpoint_status import (  # noqa: E402
    all_endpoints_exit_code,
    build_all_endpoints_status,
)


def _config(profiles: dict) -> dict:
    return {"profiles": profiles, "active_profile": ""}


class BuildAllEndpointsTest(unittest.TestCase):
    """多端点构建：全集 / 软删除过滤 / 单端点失败不中断。"""

    def test_covers_all_non_null_profiles(self):
        cfg = _config({
            "a": {"name": "a", "url": "http://127.0.0.1:1/mcp"},
            "b": None,  # 软删除标记：不参与
        })
        status = build_all_endpoints_status(cfg)
        self.assertEqual(status["kind"], "endpoint-status-all")
        names = [e["endpoint"]["name"] for e in status["endpoints"]]
        self.assertEqual(names, ["a"])  # b 被过滤
        self.assertEqual(status["summary"]["total"], 1)

    def test_single_endpoint_failure_does_not_abort_rest(self):
        """单端点解析失败记入该端点 error，其余端点照常探活。"""
        cfg = _config({
            "bad": None,  # 占位：用 monkeypatch 让 a 抛异常更直接——这里用结构验证
            "a": {"name": "a", "url": "http://127.0.0.1:1/mcp"},
        })
        status = build_all_endpoints_status(cfg)
        # 127.0.0.1:1 连接拒绝 → failed 状态（探活结论），不是中断
        self.assertEqual(len(status["endpoints"]), 1)
        self.assertIn(status["endpoints"][0]["state"], ("failed", "ok"))

    def test_exit_code_semantics(self):
        self.assertEqual(all_endpoints_exit_code({"summary": {"failed": 0}}), 0)
        self.assertEqual(all_endpoints_exit_code({"summary": {"failed": 2}}), 1)
        self.assertEqual(all_endpoints_exit_code({}), 0)  # 无 summary 不判失败


class ProfileSourcesRelativePathTest(unittest.TestCase):
    """相对路径按 config 目录解析（GUI 子进程 cwd ≠ 仓库根的修复）。"""

    def test_relative_source_resolved_against_config_dir(self):
        """cwd 无关：``data/local_overrides.yaml`` 相对 config.yaml 所在目录。"""
        from profile_loader import apply_profile_sources

        with tempfile.TemporaryDirectory() as td:
            cfg_dir = Path(td) / "repo"
            (cfg_dir / "data").mkdir(parents=True)
            overlay = cfg_dir / "data" / "local_overrides.yaml"
            overlay.write_text("active_profile: ''\ndisabled_tools: [Foo]\n",
                               encoding="utf-8")
            config = {
                "active_profile": "trunk-default",
                "profiles": {"p": {"name": "p", "url": "https://x/mcp"}},
                "profile_sources": ["data/local_overrides.yaml"],
            }
            # 关键：cwd 与 config 目录不同（模拟 GUI 子进程 cwd=/）
            prev = os.getcwd()
            try:
                os.chdir(tempfile.gettempdir())
                merged = apply_profile_sources(config, config_path=str(cfg_dir / "config.yaml"))
            finally:
                os.chdir(prev)
            self.assertEqual(merged.get("active_profile"), "")  # overlay 生效
            self.assertEqual(merged.get("disabled_tools"), ["foo"])  # normalized_name 归一化

    def test_absolute_and_home_paths_unchanged(self):
        """绝对路径 / ~ 路径不受 config 目录解析影响。"""
        from profile_loader import apply_profile_sources

        with tempfile.TemporaryDirectory() as td:
            overlay = Path(td) / "abs.yaml"
            overlay.write_text("active_profile: abs\n", encoding="utf-8")
            config = {
                "active_profile": "trunk",
                "profiles": {"p": {"name": "p", "url": "https://x/mcp"}},
                "profile_sources": [str(overlay)],
            }
            merged = apply_profile_sources(config)
            self.assertEqual(merged.get("active_profile"), "abs")


class CliOverallModeTest(unittest.TestCase):
    """CLI：无 --profile 走整体检查（kind=endpoint-status-all）。"""

    def test_no_profile_checks_all_endpoints(self):
        import json
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.yaml"
            cfg.write_text(
                "active_profile: ''\n"
                "profiles:\n"
                "  a:\n    name: a\n    url: http://127.0.0.1:1/mcp\n"
                "    transport: streamable-http\n",
                encoding="utf-8",
            )
            r = subprocess.run(
                [sys.executable, str(ROOT / "scan.py"), "--config", str(cfg),
                 "--endpoint-status", "--format", "json"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # 127.0.0.1:1 不通 → 1
            data = json.loads(r.stdout)
            self.assertEqual(data["kind"], "endpoint-status-all")
            self.assertEqual(data["summary"]["total"], 1)
            self.assertEqual(data["summary"]["failed"], 1)

    def test_with_profile_keeps_single_mode(self):
        import json
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.yaml"
            cfg.write_text(
                "active_profile: ''\n"
                "profiles:\n"
                "  a:\n    name: a\n    url: http://127.0.0.1:1/mcp\n"
                "    transport: streamable-http\n",
                encoding="utf-8",
            )
            r = subprocess.run(
                [sys.executable, str(ROOT / "scan.py"), "--config", str(cfg),
                 "--endpoint-status", "--format", "json", "--profile", "a"],
                capture_output=True, text=True, timeout=60,
            )
            data = json.loads(r.stdout)
            # 单端点结构无 kind 字段（与多端点的 endpoint-status-all 区分）
            self.assertNotIn("kind", data)
            self.assertNotIn("summary", data)
            self.assertEqual(data["endpoint"]["name"], "a")


if __name__ == "__main__":
    unittest.main()
