"""配置导入/导出契约（v0.30.0，设计 2026-10-21 §3.2/§3.3/§4）。

## 隔离纪律（实测教训，必须遵守）

``config_store._overlay_target`` 在 config 的 ``profile_sources`` 里没有已存在
文件时会**回落到仓库真实的 ``data/local_overrides.yaml``**。本文件每个用例的
tmp config 都必须：

1. ``profile_sources`` 指向 tmp 内的 overlay 文件（且该文件已存在）；
2. monkeypatch ``config_porter._discovered_file`` 指向 tmp。

否则写入会落到仓库真实文件（历史上已发生过两次：见
``test_config_overlay_writes`` 的注释与本文件创建当日的冒烟事故——
真实 overlay 的 disabled_tools 曾被覆盖成 null，靠侦察记录手工恢复）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import config_porter  # noqa: E402
from config_porter import (  # noqa: E402
    EXPORT_KIND,
    REDACTED,
    export_config,
    import_config,
    resolve_port_path,
)


TRUNK = """\
schema_version: 1
active_profile: generic-http
auto_discover:
  enabled: false
settings:
  patrol_enabled: false
  patrol_interval_minutes: 15
hooks:
  default_command: ''
  clients:
  - name: Claude Code
    template: {}
profiles:
  generic-http:
    name: my-mcp
    url: https://example.internal/mcp
    transport: streamable-http
"""


class _TmpEnv:
    """tmp 环境：trunk + 已存在的 overlay（profile_sources 指向它）+ discovered。"""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.trunk = self.dir / "config.yaml"
        self.overlay = self.dir / "data" / "local_overrides.yaml"
        self.discovered = self.dir / "data" / "discovered_tools.yaml"
        self.overlay.parent.mkdir(parents=True, exist_ok=True)
        self.trunk.write_text(TRUNK, encoding="utf-8")
        self.overlay.write_text("active_profile: k8s-uat\n", encoding="utf-8")
        self.trunk.write_text(
            TRUNK + f"profile_sources:\n  - {self.overlay}\n", encoding="utf-8"
        )
        # 隔离纪律：discovered 必须指到 tmp（见模块 docstring）
        self._patcher = mock.patch.object(
            config_porter, "_discovered_file", lambda: str(self.discovered)
        )
        self._patcher.start()
        return self

    def __exit__(self, *exc):
        self._patcher.stop()
        self.tmp.cleanup()
        return False


class ResolvePathTest(unittest.TestCase):
    """``icloud`` 别名解析。"""

    def test_plain_path_expanded(self):
        self.assertEqual(resolve_port_path("~/x.json"), os.path.expanduser("~/x.json"))

    def test_icloud_alias_on_macos(self):
        if sys.platform != "darwin":
            self.skipTest("仅 macOS")
        resolved = resolve_port_path("icloud")
        self.assertIn("Library/Mobile Documents", resolved.replace("\\", "/"))
        self.assertIn("skill-mcp-studio/config-export.json", resolved.replace("\\", "/"))

    def test_icloud_alias_rejected_off_macos(self):
        if sys.platform == "darwin":
            self.skipTest("仅非 macOS")
        with self.assertRaises(ValueError):
            resolve_port_path("icloud")


class ExportTest(unittest.TestCase):
    """导出：结构 / 脱敏 / dry-run。"""

    def test_payload_structure_and_redaction(self):
        with _TmpEnv() as env:
            # 给端点加 auth_token（trunk 里没有，写进 overlay 的 profiles）
            env.overlay.write_text(
                "active_profile: k8s-uat\n"
                "profiles:\n"
                "  secret-endpoint:\n"
                "    name: sec\n"
                "    url: https://sec/mcp\n"
                "    auth_token: real-secret-value\n",
                encoding="utf-8",
            )
            out = env.dir / "export.json"
            r = export_config(str(out), config_path=str(env.trunk))

            self.assertEqual(r["status"], "ok")
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], EXPORT_KIND)
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("exported_at", payload)
            self.assertIn("app_version", payload)
            # 生效视图：overlay 的 active_profile 赢过 trunk
            self.assertEqual(payload["config"]["active_profile"], "k8s-uat")
            # 脱敏
            self.assertEqual(
                payload["profiles"]["secret-endpoint"]["auth_token"], REDACTED
            )
            self.assertNotIn("real-secret-value", out.read_text(encoding="utf-8"))

    def test_dry_run_does_not_write(self):
        with _TmpEnv() as env:
            out = env.dir / "export.json"
            r = export_config(str(out), config_path=str(env.trunk), dry_run=True)
            self.assertEqual(r["status"], "dry-run")
            self.assertFalse(out.exists())
            self.assertIn("payload", r)

    def test_skip_discovered_omits_section(self):
        with _TmpEnv() as env:
            out = env.dir / "export.json"
            export_config(str(out), config_path=str(env.trunk), include_discovered=False)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("discovered_tools", payload)


class ImportTest(unittest.TestCase):
    """导入：分流 / 合并 / redacted / 备份 / 校验。"""

    @staticmethod
    def _make_export(env, *, with_token=False, with_discovered=False):
        """在 env 里生成一份导出包（模拟「另一台机器」的配置）。"""
        payload = {
            "kind": EXPORT_KIND,
            "schema_version": 1,
            "exported_at": "2026-10-21T13:00:00+08:00",
            "app_version": "0.30.0",
            "config": {
                "active_profile": "prod",
                "auto_discover": {"enabled": True},
                "unified_skills_dir": "~/skills-prod",
                "settings": {"patrol_enabled": True, "patrol_interval_minutes": 30},
                "hooks": {
                    "default_command": "notify {event}",
                    "clients": [
                        {"name": "Claude Code",
                         "template": {"SessionStart": "echo {event} start"}}
                    ],
                },
                "disabled_tools": None,
            },
            "profiles": {
                "prod": {"name": "prod", "url": "https://prod/mcp",
                         **({"auth_token": REDACTED} if with_token else {})},
            },
        }
        if with_discovered:
            payload["discovered_tools"] = [
                {"name": ".cc-switch", "type": "AI Assistant", "skills_paths": ["~/.cc-switch/skills"]},
            ]
        path = env.dir / "incoming.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_import_writes_overlay_and_trunk_channels(self):
        with _TmpEnv() as env:
            src = self._make_export(env)
            r = import_config(str(src), config_path=str(env.trunk))

            self.assertEqual(r["status"], "ok")
            # overlay 通道：active_profile / auto_discover / unified_skills_dir / profiles
            import yaml
            ov = yaml.safe_load(env.overlay.read_text(encoding="utf-8"))
            self.assertEqual(ov["active_profile"], "prod")
            self.assertEqual(ov["auto_discover"]["enabled"], True)
            self.assertEqual(ov["unified_skills_dir"], "~/skills-prod")
            self.assertEqual(ov["profiles"]["prod"]["url"], "https://prod/mcp")
            # trunk 通道：settings / hooks（text-rewrite，保注释）
            raw = env.trunk.read_text(encoding="utf-8")
            self.assertIn("schema_version: 1", raw)  # trunk 其余内容原样
            trunk = yaml.safe_load(raw)
            self.assertEqual(trunk["settings"]["patrol_enabled"], True)
            self.assertEqual(trunk["settings"]["patrol_interval_minutes"], 30)
            self.assertEqual(trunk["hooks"]["default_command"], "notify {event}")
            self.assertEqual(
                trunk["hooks"]["clients"][0]["template"]["SessionStart"],
                "echo {event} start",
            )
            # 导入后生效（load_config 合并链）
            from scanner import load_config
            cfg = load_config(str(env.trunk))
            self.assertEqual(cfg["active_profile"], "prod")
            self.assertEqual(cfg["auto_discover"]["enabled"], True)

    def test_none_value_does_not_wipe_local_overlay_key(self):
        """导出包里未设置的键（None）不得清掉本地 overlay 已有值。

        实测教训：导出端没有 disabled_tools 时，导入曾把本地停用清单
        覆盖成 null（真实 overlay 事故的复现用例）。
        """
        with _TmpEnv() as env:
            import yaml
            env.overlay.write_text(
                "active_profile: k8s-uat\ndisabled_tools:\n- ZZProbeAgent\n",
                encoding="utf-8",
            )
            src = self._make_export(env)  # disabled_tools: None
            import_config(str(src), config_path=str(env.trunk))
            ov = yaml.safe_load(env.overlay.read_text(encoding="utf-8"))
            self.assertEqual(ov["disabled_tools"], ["ZZProbeAgent"])

    def test_redacted_token_skipped_and_local_kept(self):
        with _TmpEnv() as env:
            import yaml
            env.overlay.write_text(
                "active_profile: k8s-uat\n"
                "profiles:\n  prod:\n    name: prod\n    url: https://old/mcp\n"
                "    auth_token: local-secret\n",
                encoding="utf-8",
            )
            src = self._make_export(env, with_token=True)
            r = import_config(str(src), config_path=str(env.trunk))

            ov = yaml.safe_load(env.overlay.read_text(encoding="utf-8"))
            # redacted 跳过：本地密钥保留，url 用导入值
            self.assertEqual(ov["profiles"]["prod"]["auth_token"], "local-secret")
            self.assertEqual(ov["profiles"]["prod"]["url"], "https://prod/mcp")
            self.assertEqual(r["skipped_tokens"], [])

    def test_redacted_token_flagged_when_local_missing(self):
        with _TmpEnv() as env:
            src = self._make_export(env, with_token=True)
            r = import_config(str(src), config_path=str(env.trunk))
            self.assertEqual(r["skipped_tokens"], ["prod"])
            self.assertIn("auth_token", r["message"])

    def test_backups_actually_created(self):
        """备份必须是真实文件（backup_path 只给路径，复制要自己做）。"""
        with _TmpEnv() as env:
            src = self._make_export(env)
            r = import_config(str(src), config_path=str(env.trunk))
            for label, bak in r["backups"].items():
                self.assertTrue(os.path.isfile(bak), f"{label} 备份未真正生成: {bak}")

    def test_discovered_merged_by_name(self):
        with _TmpEnv() as env:
            import yaml
            env.discovered.write_text(
                yaml.safe_dump([{"name": ".existing", "type": "X"}]),
                encoding="utf-8",
            )
            src = self._make_export(env, with_discovered=True)
            r = import_config(str(src), config_path=str(env.trunk))

            merged = yaml.safe_load(env.discovered.read_text(encoding="utf-8"))
            names = [e["name"] for e in merged]
            self.assertEqual(names.count(".cc-switch"), 1)  # 去重
            self.assertIn(".existing", names)               # 本地保留

    def test_invalid_kind_rejected(self):
        with _TmpEnv() as env:
            bad = env.dir / "bad.json"
            bad.write_text(json.dumps({"kind": "something-else", "schema_version": 1}),
                           encoding="utf-8")
            with self.assertRaises(ValueError):
                import_config(str(bad), config_path=str(env.trunk))

    def test_unsupported_schema_version_rejected(self):
        with _TmpEnv() as env:
            bad = env.dir / "bad.json"
            bad.write_text(json.dumps({"kind": EXPORT_KIND, "schema_version": 99}),
                           encoding="utf-8")
            with self.assertRaises(ValueError):
                import_config(str(bad), config_path=str(env.trunk))

    def test_dry_run_reports_plan_without_writing(self):
        with _TmpEnv() as env:
            before_overlay = env.overlay.read_text(encoding="utf-8")
            before_trunk = env.trunk.read_text(encoding="utf-8")
            src = self._make_export(env)
            r = import_config(str(src), config_path=str(env.trunk), dry_run=True)

            self.assertEqual(r["status"], "dry-run")
            self.assertTrue(any("active_profile" in c for c in r["changes"]))
            self.assertTrue(any("settings" in c for c in r["changes"]))
            self.assertEqual(env.overlay.read_text(encoding="utf-8"), before_overlay)
            self.assertEqual(env.trunk.read_text(encoding="utf-8"), before_trunk)

    def test_same_values_are_noop(self):
        """语义值相同 → 不写盘、不虚报变更（引号风格差异不算变更）。"""
        with _TmpEnv() as env:
            src = self._make_export(env)
            import_config(str(src), config_path=str(env.trunk))
            # 第二次导入同一份包：全部值已一致
            r2 = import_config(str(src), config_path=str(env.trunk))
            self.assertEqual(r2["changes"], [])
            self.assertEqual(r2["status"], "ok")


class CliEntryTest(unittest.TestCase):
    """``--export-config`` / ``--import-config`` CLI 入口（subprocess 端到端）。

    隔离纪律（同模块 docstring，CLI 层同样适用）：
    - tmp config 的 ``profile_sources`` 必须指向 tmp overlay（否则导入写入
      会落到仓库真实 ``data/local_overrides.yaml``——CLI 端到端实测踩过两次）；
    - 导出用 ``--skip-discovered`` 生成导入源，避免读写真实
      ``data/discovered_tools.yaml``（subprocess 内无法 monkeypatch）。
    """

    def _env(self):
        env = _TmpEnv()
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)
        return env

    def _cli(self, *argv):
        import subprocess
        return subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), *argv],
            capture_output=True, text=True, timeout=120,
        )

    def test_export_then_import_roundtrip(self):
        env = self._env()
        # 隔离基线：记录真实 overlay 的当前内容（具体值随用户合法配置漂移，
        # 断言「前后不变」而不是断言某个具体值——硬编码值会在用户改配置后误报）。
        real_overlay = ROOT / "data" / "local_overrides.yaml"
        baseline = real_overlay.read_text(encoding="utf-8") if real_overlay.exists() else None
        out = env.dir / "export.json"
        # 导出（--skip-discovered：不读真实 discovered 文件）
        r = self._cli("--config", str(env.trunk), "--export-config", str(out),
                      "--skip-discovered")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("已导出", r.stdout)
        self.assertTrue(out.exists())

        # 导入到「新机器」（trunk2 带 profile_sources 指向自己的 tmp overlay）
        trunk2 = env.dir / "config2.yaml"
        overlay2 = env.dir / "data2" / "local_overrides.yaml"
        overlay2.parent.mkdir(parents=True, exist_ok=True)
        overlay2.write_text("active_profile: k8s-uat\n", encoding="utf-8")
        trunk2.write_text(
            TRUNK + f"profile_sources:\n  - {overlay2}\n", encoding="utf-8"
        )
        r2 = self._cli("--config", str(trunk2), "--import-config", str(out))
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("已导入", r2.stdout)

        import yaml
        ov2 = yaml.safe_load(overlay2.read_text(encoding="utf-8"))
        self.assertEqual(ov2["active_profile"], "k8s-uat")  # 导出包的生效值
        # 仓库真实 overlay 未被触碰（隔离断言：内容与基线逐字节一致）
        real = ROOT / "data" / "local_overrides.yaml"
        now = real.read_text(encoding="utf-8") if real.exists() else None
        self.assertEqual(now, baseline, "仓库真实 data/local_overrides.yaml 被测试写入污染")

    def test_import_dry_run_via_cli(self):
        env = self._env()
        out = env.dir / "export.json"
        self._cli("--config", str(env.trunk), "--export-config", str(out),
                  "--skip-discovered")
        r = self._cli("--config", str(env.trunk), "--import-config", str(out),
                      "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[dry-run]", r.stdout)

    def test_missing_file_fails_with_exit_2(self):
        env = self._env()
        r = self._cli("--config", str(env.trunk), "--import-config",
                      str(env.dir / "nope.json"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("不存在", r.stdout)

    def test_export_dry_run_prints_full_json(self):
        """设计 §3.4：导出 dry-run 打印将写的 JSON（脱敏后），可预览全文。"""
        env = self._env()
        out = env.dir / "export.json"
        r = self._cli("--config", str(env.trunk), "--export-config", str(out),
                      "--dry-run", "--skip-discovered")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("将导出到", r.stdout)          # 摘要行
        self.assertIn('"kind"', r.stdout)            # 完整 JSON
        self.assertIn(EXPORT_KIND, r.stdout)
        self.assertIn('"profiles"', r.stdout)        # 脱敏后的 profiles 可预览
        self.assertFalse(out.exists())               # dry-run 不落盘

    def test_list_config_backups_without_client_lists_engine_files(self):
        """设计 §3.3：不带 --client 时列引擎三件套备份（导入备份的列出入口）。"""
        env = self._env()
        r = self._cli("--config", str(env.trunk), "--list-config-backups")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("config.yaml 的备份", r.stdout)
        self.assertIn("overlay 的备份", r.stdout)
        self.assertIn("discovered_tools 的备份", r.stdout)
        self.assertIn("引擎配置备份", r.stdout)

    def test_icloud_alias_dry_run_on_macos(self):
        if sys.platform != "darwin":
            self.skipTest("仅 macOS")
        env = self._env()
        r = self._cli("--config", str(env.trunk), "--export-config", "icloud",
                      "--dry-run", "--skip-discovered")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Mobile Documents", r.stdout)


if __name__ == "__main__":
    unittest.main()
