import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from mcp_checker import load_mcp_servers
from mcp_fixer import fix_mcp_tool

URL = 'https://mcp.example.test/mcp'


class NativeConfigProtectionTests(unittest.TestCase):
    def test_cordis_insert_and_custom_native_plugin_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'cordis.patch.yml'
            p.write_text('- insert:\n    - id: mcp-hermes-native\n'
                '      name: /native/identity/lib/index.js\n      config:\n'
                '        serverName: hermes\n        transport: streamable-http\n'
                '        url: ' + URL + '\n')
            self.assertEqual(load_mcp_servers(str(p), 'cordis_yaml', ['hermes'])['hermes']['url'], URL)

    def test_generic_repair_does_not_rewrite_native_headers_or_create_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'mcp.json'
            p.write_text(json.dumps({'mcpServers': {'WorkBuddy': {'url': URL,
                'headers': {'Authorization': 'Bearer preserved'}}}}))
            before = p.read_bytes()
            tool = {'name': 'WorkBuddy', 'config_path': str(p), 'format': 'json',
                    'mcp_key_path': ['mcpServers'], 'fix_supported': True, 'mcp_root_env_style': 'env'}
            with patch('mcp_fixer.resolve_auth', side_effect=AssertionError('must not fetch credentials')):
                result = fix_mcp_tool(tool, {'name': 'hermes', 'url': URL, 'auth_mode': 'keychain',
                                            'auth_keychain': 'test'})
            self.assertEqual(result['status'], 'unchanged')
            self.assertEqual(p.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
