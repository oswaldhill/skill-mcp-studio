"""管理台「端点凭据」交互的可机检约束（v0.31.4 之后）。

守四条**会真正被破坏**的不变量：

1. 端点编辑弹窗提供四种认证方式，且取值与后端 ``auth_secret.AUTH_MODES`` 一致
   （两边各自硬编码 —— 后端接受 ``keychain``、前端只发 ``key_store`` 这种漂移
   不会报错，只会让保存静默落回明文）；
2. 引用型模式**不发送明文** ``--endpoint-auth-token``（而是发来源参数）；
3. 端点库表格不再把 ``auth_token`` 塞进 ``data-*`` 属性 —— 那是把长期令牌
   明文暴露给 DOM；
4. 设置页存在「凭据」卡片，且 JSON 状态读取走 ``--auth-secret-status all``。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from auth_secret import AUTH_MODES as BACKEND_MODES  # noqa: E402
from tests._gui_source import page_html, page_source  # noqa: E402


def _src():
    return page_source()


class AuthModeContractTest(unittest.TestCase):
    def test_frontend_modes_match_backend(self):
        src = _src()
        m = re.search(r"const AUTH_MODES = \{(.*?)\n\};", src, re.S)
        self.assertIsNotNone(m, "前端找不到 AUTH_MODES 定义")
        keys = set(re.findall(r"(?m)^\s*(\w+):\s*\{", m.group(1)))
        self.assertEqual(keys, set(BACKEND_MODES), "前后端认证方式取值不一致")

    def test_every_mode_has_a_chinese_label(self):
        src = _src()
        m = re.search(r"const AUTH_MODES = \{(.*?)\n\};", src, re.S)
        for label in ("明文 Token", "环境变量", "系统钥匙串", "凭据文件"):
            self.assertIn(label, m.group(1), f"认证方式缺少标签：{label}")

    def test_source_fields_map_to_cli_flags(self):
        src = _src()
        for flag in ("--endpoint-auth-env", "--endpoint-auth-keychain", "--endpoint-auth-file"):
            self.assertIn(flag, src, f"缺少来源参数 {flag}")

    def test_unknown_mode_falls_back_to_token(self):
        # 与后端 normalize_auth_mode 对齐：未知取值按明文处理，不能让弹窗崩掉
        src = _src()
        m = re.search(r"function endpointAuthMode\(ep\) \{(.*?)\n\}", src, re.S)
        self.assertIsNotNone(m)
        self.assertIn('|| "token"', m.group(1))


class NoSecretInDomTest(unittest.TestCase):
    def test_endpoint_table_has_no_data_auth_token_attribute(self):
        html = page_html()
        self.assertNotIn(
            'data-auth_token=', html,
            "端点库表格把 auth_token 写进了 DOM 属性，明文令牌会随页面源码泄露",
        )

    def test_edit_action_carries_only_the_key(self):
        html = page_html()
        m = re.search(r'data-action="edit-endpoint"[^>]*', html)
        self.assertIsNotNone(m)
        self.assertNotIn("data-url", m.group(0))
        self.assertIn("data-key=", m.group(0))


class CredentialCardTest(unittest.TestCase):
    def test_settings_has_credential_card(self):
        html = page_html()
        self.assertIn('id="endpoint-cred-card"', html)
        self.assertIn("MCP 端点凭据", html)

    def test_status_loaded_through_cli(self):
        src = _src()
        self.assertIn('"--auth-secret-status", "all"', src)

    def test_store_action_uses_set_auth_secret(self):
        src = _src()
        self.assertIn('"--set-auth-secret"', src)

    def test_check_action_asks_for_real_read(self):
        # 默认不读内容（钥匙串会弹授权）；只有用户点「检测」才加 --check-credential
        src = _src()
        self.assertIn('"--check-credential"', src)


class ReferenceModeSendsNoPlaintextTest(unittest.TestCase):
    def test_save_paths_only_send_token_in_plaintext_mode(self):
        src = _src()
        # 两处保存分支（新增 / 编辑）都必须以 auth.mode === "token" 守卫
        guarded = re.findall(r'if \(auth\.mode === "token"\)', src)
        self.assertGreaterEqual(len(guarded), 2, "保存分支没有按 auth.mode 守卫明文 token")


if __name__ == "__main__":
    unittest.main()
