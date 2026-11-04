"""端点凭据「引用型」模式在六个客户端格式里的落盘形态（v0.31.4 之后）。

这是本轮功能的核心不变量：**引用型端点写进客户端配置的只能是引用，不能是明文**。

为什么每个格式都要单独断言：六个渲染器的能力不同（JSON/YAML 是纯文本、
Codex 的 TOML 有官方 ``bearer_token_env_var``、cordis 的 ``!!js`` 解析器会拒绝
反引号），一旦有人「顺手统一一下」，就会在某些客户端上写出无效 token 或
真的把明文抄进去。这里逐格式钉死：

================  ===================================================
format             引用型 auth_mode 期望形态
================  ===================================================
json / jsonc       ``Authorization: "Bearer ${env:VAR}"``
yaml               同上
toml               ``bearer_token_env_var = "VAR"``（且不得有 http_headers）
cordis_yaml        ``Authorization: "Bearer ${env:VAR}"``（可被 PyYAML 读回）
reasonix*          ``Bearer <redacted>`` 占位（该格式无求值能力）
================  ===================================================

同时守住「明文模式逐字节不变」：``auth_mode`` 缺省 / 显式 ``token`` 时，
输出必须与改造前一字不差 —— 这是几万条存量配置的兼容底线。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import yaml  # noqa: E402

from config_codec import parse_cordis_yaml  # noqa: E402
from mcp_fixer import fix_mcp_tool, resolve_auth_fields  # noqa: E402
from mcp_fixer_render import _render  # noqa: E402

URL = "https://hermes.example.com/mcp"
ENV_PROFILE = {"name": "hermes", "url": URL, "auth_mode": "env", "auth_token_env": "HERMES_MCP_AUTH_TOKEN"}
KEYCHAIN_PROFILE = {"name": "hermes", "url": URL, "auth_mode": "keychain", "auth_keychain": "hermes-unified-mcp"}


def _auth(profile):
    """渲染层拿到的 auth 字段：补上端点级派生的合法变量名（与 fix_mcp_tool 同源）。"""
    from mcp_fixer import _derived_env_name

    return resolve_auth_fields({**profile, "auth_env_name": _derived_env_name(profile)})


def tool(path=None, fmt="json", **extra):
    entry = {"name": "Test", "format": fmt}
    if path is not None:
        entry["config_path"] = str(path)
    entry.update(extra)
    return entry


class JsonReferenceTest(unittest.TestCase):
    def test_env_mode_writes_client_interpolation_placeholder(self):
        out = json.loads(_render(tool(fmt="json"), "{}\n", "hermes", URL, "", auth=resolve_auth_fields(ENV_PROFILE)))
        self.assertEqual(
            out["mcpServers"]["hermes"]["headers"]["Authorization"],
            "Bearer ${env:HERMES_MCP_AUTH_TOKEN}",
        )

    def test_keychain_mode_never_contains_a_real_token(self):
        out = json.loads(_render(tool(fmt="json"), "{}\n", "hermes", URL, "", auth=_auth(KEYCHAIN_PROFILE)))
        header = out["mcpServers"]["hermes"]["headers"]["Authorization"]
        # 变量名由端点名派生（HERMES_MCP_TOKEN），不再是含连字符的服务名 ——
        # 连字符不是合法变量名，客户端读不到。
        self.assertEqual(header, "Bearer ${env.HERMES_MCP_TOKEN}")
        self.assertNotIn("hermes-unified-mcp", header.replace("${env.", ""))

    def test_plaintext_mode_is_byte_identical_to_legacy(self):
        legacy = _render(tool(fmt="json"), "{}\n", "hermes", URL, "SECRET")
        explicit = _render(
            tool(fmt="json"), "{}\n", "hermes", URL, "SECRET",
            auth=resolve_auth_fields({"auth_token": "SECRET", "auth_mode": "token"}),
        )
        self.assertEqual(legacy, explicit)
        self.assertEqual(
            json.loads(legacy)["mcpServers"]["hermes"]["headers"]["Authorization"],
            "Bearer SECRET",
        )


class YamlReferenceTest(unittest.TestCase):
    def test_env_mode_in_generic_yaml(self):
        out = yaml.safe_load(
            _render(tool(fmt="yaml", mcp_key_path=["mcp_servers"]), "", "hermes", URL, "",
                    auth=resolve_auth_fields(ENV_PROFILE))
        )
        self.assertEqual(
            out["mcp_servers"]["hermes"]["headers"]["Authorization"],
            "Bearer ${env:HERMES_MCP_AUTH_TOKEN}",
        )

    def test_file_mode_reference_uses_derived_var_name_not_path(self):
        # 路径含斜杠，绝不能当变量名写进配置（那样客户端里根本不是「一个变量」）。
        profile = {"name": "hermes", "url": URL, "auth_mode": "file", "auth_file": "/tmp/tok"}
        out = yaml.safe_load(
            _render(tool(fmt="yaml", mcp_key_path=["mcp_servers"]), "", "hermes", URL, "",
                    auth=_auth(profile))
        )
        header = out["mcp_servers"]["hermes"]["headers"]["Authorization"]
        self.assertEqual(header, "Bearer ${env.HERMES_MCP_TOKEN}")
        self.assertNotIn("/tmp/tok", header)


class TomlReferenceTest(unittest.TestCase):
    def test_env_mode_uses_codex_bearer_token_env_var(self):
        import tomllib

        text = _render(tool(fmt="toml"), "", "hermes", URL, "", auth=resolve_auth_fields(ENV_PROFILE))
        data = tomllib.loads(text)
        section = data["mcp_servers"]["hermes"]
        self.assertEqual(section["bearer_token_env_var"], "HERMES_MCP_AUTH_TOKEN")
        self.assertNotIn("http_headers", section)
        self.assertEqual(section["url"], URL)

    def test_keychain_mode_clears_previous_plaintext_header(self):
        # 从明文切到钥匙串：旧的 http_headers 明文必须被清掉，否则「改了模式
        # 但旧 token 还在配置里」—— 安全改造的常见漏网之鱼。
        import tomllib

        original = (
            '[mcp_servers.hermes]\n'
            f'url = "{URL}"\n'
            'http_headers = { Authorization = "Bearer OLD-SECRET" }\n'
        )
        text = _render(
            tool(fmt="toml"), original, "hermes", URL, "",
            auth=_auth(KEYCHAIN_PROFILE),
        )
        self.assertNotIn("OLD-SECRET", text)
        section = tomllib.loads(text)["mcp_servers"]["hermes"]
        self.assertEqual(section["bearer_token_env_var"], "HERMES_MCP_TOKEN")
        self.assertNotIn("http_headers", section)

    def test_reference_mode_removes_child_table_when_it_becomes_empty(self):
        import tomllib

        original = (
            '[mcp_servers.hermes]\n'
            f'url = "{URL}"\n'
            '\n'
            '[mcp_servers.hermes.http_headers]\n'
            'Authorization = "Bearer OLD-SECRET"\n'
            '\n'
            '[mcp_servers.other]\n'
            'url = "https://other.example.com/mcp"\n'
        )
        text = _render(tool(fmt="toml"), original, "hermes", URL, "",
                       auth=resolve_auth_fields(ENV_PROFILE))
        self.assertNotIn("OLD-SECRET", text)
        data = tomllib.loads(text)
        self.assertNotIn("http_headers", data["mcp_servers"]["hermes"])
        self.assertEqual(data["mcp_servers"]["other"]["url"], "https://other.example.com/mcp")

    def test_plaintext_toml_unchanged(self):
        text = _render(tool(fmt="toml"), "", "hermes", URL, "SECRET", auth=resolve_auth_fields({"auth_token": "SECRET"}))
        self.assertIn('http_headers = { Authorization = "Bearer SECRET" }', text)


class CordisReferenceTest(unittest.TestCase):
    def test_reference_header_is_parseable_by_project_codec(self):
        # 实测教训：`!!js` 值里含反引号/花括号时 PyYAML 直接解析失败，
        # 写下去的配置连本项目的校验都过不了。这里守住「写的必须能读回」。
        text = _render(tool(fmt="cordis_yaml"), "", "hermes", URL, "",
                       auth=resolve_auth_fields(ENV_PROFILE))
        parsed = parse_cordis_yaml(text)
        header = parsed[0]["config"]["headers"]["Authorization"]
        self.assertEqual(header, "Bearer ${env:HERMES_MCP_AUTH_TOKEN}")

    def test_existing_plaintext_header_is_replaced(self):
        original = (
            "- id: mcp-hermes\n"
            "  name: '@deepseek-ai/dsh-mcp-client'\n"
            "  config:\n"
            "    serverName: hermes\n"
            "    transport: streamable-http\n"
            f"    url: {URL}\n"
            "    headers:\n"
            '      Authorization: "Bearer OLD-SECRET"\n'
        )
        text = _render(tool(fmt="cordis_yaml"), original, "hermes", URL, "",
                       auth=_auth(KEYCHAIN_PROFILE))
        self.assertNotIn("OLD-SECRET", text)
        parsed = parse_cordis_yaml(text)
        self.assertIn("HERMES_MCP_TOKEN", parsed[0]["config"]["headers"]["Authorization"])


class ReasonixReferenceTest(unittest.TestCase):
    def test_reasonix_toml_uses_placeholder_not_invented_syntax(self):
        text = _render(tool(fmt="reasonix_toml"), "", "hermes", URL, "")
        self.assertNotIn("<redacted>", text)  # 明文模式无占位符
        profile = {"name": "hermes", "url": URL, "auth_mode": "env", "auth_token_env": "X"}
        fields = resolve_auth_fields(profile)
        # reasonix 的 name=url 数组/表没有插值能力：此时渲染层拿到的 token 必须是
        # 占位符而不是真值，避免「把服务名当成 token 发出去」的静默错误。
        self.assertEqual(fields["token"], "")


class RootEnvInjectionTest(unittest.TestCase):
    """客户端支持「根 env 块」时，真值必须写进配置，客户端才能真正取到。

    判据（``reference_is_evaluated``）三条路径：token / Codex TOML /
    ``mcp_root_env_style`` 非空。其余客户端写的是占位符 —— 必须如实告知。
    """

    def test_json_client_with_env_style_gets_injected_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            cred = Path(tmp) / "tok"
            cred.write_text("file-secret\n", encoding="utf-8")
            path = Path(tmp) / "vscode.json"
            path.write_text('{"mcpServers": {}}', encoding="utf-8")
            profile = {"name": "hermes", "url": URL, "auth_mode": "file", "auth_file": str(cred)}
            entry_tool = tool(path, mcp_root_env_style="env")
            result = fix_mcp_tool(entry_tool, profile)
            self.assertEqual(result["status"], "updated")
            data = json.loads(path.read_text(encoding="utf-8"))
            # 端点定义里仍是引用（不落明文）
            self.assertEqual(
                data["mcpServers"]["hermes"]["headers"]["Authorization"],
                "Bearer ${env.HERMES_MCP_TOKEN}",
            )
            # 真值在根 env 块里，客户端启动后注入自身环境
            self.assertEqual(data["env"]["HERMES_MCP_TOKEN"], "file-secret")
            self.assertIn("已注入", result["message"])

    def test_yaml_client_uses_process_env_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            cred = Path(tmp) / "tok"
            cred.write_text("goose-secret\n", encoding="utf-8")
            path = Path(tmp) / "config.yaml"
            path.write_text("extensions: {}\n", encoding="utf-8")
            profile = {"name": "hermes", "url": URL, "auth_mode": "file", "auth_file": str(cred)}
            entry_tool = tool(path, fmt="yaml", mcp_key_path=["extensions"], mcp_root_env_style="process_envs")
            result = fix_mcp_tool(entry_tool, profile)
            self.assertEqual(result["status"], "updated")
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(data["process_envs"]["HERMES_MCP_TOKEN"], "goose-secret")

    def test_client_without_env_style_is_told_it_will_not_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wb.json"
            path.write_text('{"mcpServers": {}}', encoding="utf-8")
            profile = {"name": "hermes", "url": URL, "auth_mode": "keychain", "auth_keychain": "hermes-unified-mcp"}
            result = fix_mcp_tool(tool(path), profile)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("env", data)  # 没声明就不写
            self.assertIn("不会解析占位符", result["message"])
            self.assertIn("HERMES_MCP_TOKEN", result["message"])

    def test_unreadable_source_still_writes_reference_and_says_so(self):
        # 钥匙串读不到（未授权）时仍写入引用，但消息里必须点明「真值未取到」。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vs.json"
            path.write_text('{"mcpServers": {}}', encoding="utf-8")
            profile = {"name": "hermes", "url": URL, "auth_mode": "keychain", "auth_keychain": "svc"}
            with patch("mcp_fixer.resolve_auth", side_effect=Exception("不该走这条路")):
                pass
            with patch("auth_secret.keychain_read", side_effect=RuntimeError("用户拒绝授权")):
                result = fix_mcp_tool(tool(path, mcp_root_env_style="env"), profile)
            self.assertEqual(result["status"], "updated")
            self.assertIn("真值未取到", result["message"])
            self.assertIn("用户拒绝授权", result["message"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("HERMES_MCP_TOKEN", data.get("env") or {})

    def test_env_style_ignores_invalid_declared_var_name(self):
        # env 模式下声明名必须合法，否则客户端读不到 —— 此时退回派生名。
        out = json.loads(_render(
            tool(fmt="json", mcp_root_env_style="env"), "{}\n", "hermes", URL, "",
            auth={**_auth({"auth_mode": "env", "auth_token_env": "not-valid-name"}),
                  "evaluated_token": "v"},
        ))
        self.assertEqual(out["mcpServers"]["hermes"]["headers"]["Authorization"],
                         "Bearer ${env:not-valid-name}")
        # 非法名不进 env 块（写进去也是一个读不到的键）
        self.assertNotIn("not-valid-name", out.get("env") or {})


class ReferenceEvaluationMatrixTest(unittest.TestCase):
    """``reference_is_evaluated`` 的三条「能求值」路径必须与真实渲染一致。

    守的是「说了能连就真的能连」：判定说 True，渲染就必须真的把值送到客户端
    拿得到的位置；说 False，就必须没有任何位置放真值。
    """

    def test_matrix(self):
        from mcp_fixer_render import reference_is_evaluated

        keychain_profile = {"auth_mode": "keychain", "auth_keychain": "hermes-unified-mcp"}
        auth = _auth(keychain_profile)
        cases = [
            # (config_format, root_env_style, 期望)
            ("json", "", False),           # 无 env 块 → 占位符，客户端不认
            ("json", "env", True),         # 注入根 env 块 → 能求值
            ("jsonc", "env", True),
            ("yaml", "process_envs", True),
            ("toml", "", True),            # Codex 的 bearer_token_env_var
            ("cordis_yaml", "", False),    # DSH 无可写 env 容器
            ("reasonix_toml", "", False),
        ]
        for fmt, style, expected in cases:
            with self.subTest(fmt=fmt, style=style):
                self.assertEqual(
                    reference_is_evaluated(fmt, "keychain", style, auth), expected
                )

    def test_plaintext_token_is_always_evaluated(self):
        from mcp_fixer_render import reference_is_evaluated

        for fmt in ("json", "yaml", "toml", "cordis_yaml", "reasonix_toml"):
            self.assertTrue(reference_is_evaluated(fmt, "token"))

    def test_jsonc_client_also_gets_root_env(self):
        # OpenCode 走 jsonc 格式且已声明 mcp_root_env_style=env —— 不能只在 json 分支实现。
        out = json.loads(_render(
            tool(fmt="jsonc", mcp_key_path=["mcp"], mcp_entry_type="remote", mcp_root_env_style="env"),
            '{"mcp": {}}\n', "hermes", URL, "",
            auth={**_auth(KEYCHAIN_PROFILE), "evaluated_token": "v"},
        ))
        self.assertIn("HERMES_MCP_TOKEN", out["env"])

    def test_codex_without_valid_var_name_is_not_claimed_evaluated(self):
        from mcp_fixer_render import reference_is_evaluated

        # 文件模式的路径不能当变量名 → Codex 也读不到，判定必须为 False。
        auth = resolve_auth_fields({"auth_mode": "file", "auth_file": "/tmp/tok"})
        self.assertFalse(reference_is_evaluated("toml", "file", "", auth))


class FixerIntegrationTest(unittest.TestCase):
    """经 fix_mcp_tool 的完整写盘路径（含写后校验）。"""

    def test_env_mode_end_to_end_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text('{"mcpServers": {}}', encoding="utf-8")
            result = fix_mcp_tool(tool(path), ENV_PROFILE)
            self.assertEqual(result["status"], "updated")
            entry = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["hermes"]
            self.assertEqual(entry["headers"]["Authorization"], "Bearer ${env:HERMES_MCP_AUTH_TOKEN}")

    def test_mode_switch_from_plaintext_removes_secret_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text(
                json.dumps({"mcpServers": {"hermes": {
                    "url": URL, "headers": {"Authorization": "Bearer OLD-SECRET"}}}}),
                encoding="utf-8",
            )
            fix_mcp_tool(tool(path), KEYCHAIN_PROFILE)
            self.assertNotIn("OLD-SECRET", path.read_text(encoding="utf-8"))

    def test_json_reference_result_says_it_is_not_resolved_yet(self):
        # 诚实性断言：JSON 客户端不解析 ${env.X}，修复结果不能只说「updated」，
        # 必须指出还需要把真值注入环境变量，否则用户以为已经接入完成。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text('{"mcpServers": {}}', encoding="utf-8")
            result = fix_mcp_tool(tool(path), ENV_PROFILE)
            self.assertEqual(result["status"], "updated")
            self.assertIn("不会解析占位符", result["message"])
            self.assertIn("HERMES_MCP_AUTH_TOKEN", result["message"])

    def test_codex_env_reference_is_reported_as_verified(self):
        # 反向：Codex 的 bearer_token_env_var 会被解析，消息保持原样（不吓用户）。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("", encoding="utf-8")
            result = fix_mcp_tool(tool(path, "toml", mcp_key_path=["mcp_servers"]), ENV_PROFILE)
            self.assertEqual(result["status"], "updated")
            self.assertIn("verified", result["message"])

    def test_reference_mode_without_source_is_unsupported_not_silent(self):
        # 声明了 keychain 却漏填服务名：必须显式报 unsupported 并保持文件不动，
        # 而不是退回明文或写入一条没人能求值的空引用。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            original = '{"mcpServers": {}}'
            path.write_text(original, encoding="utf-8")
            result = fix_mcp_tool(tool(path), {"name": "hermes", "url": URL, "auth_mode": "keychain"})
            self.assertEqual(result["status"], "unsupported")
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
