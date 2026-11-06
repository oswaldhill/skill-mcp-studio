"""Portable native adapter regressions; no production credentials or network."""
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from native_identity import NativeIdentityService
from native_evidence import collect_evidence, parse_records, EvidenceError
from native_patch import native_patch_spec
from config_codec import iter_cordis_mcp_entries, parse_cordis_yaml
from mcp_fixer import fix_mcp_tool
from tests.test_native_identity import native_records, REPO, URL


class NativeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.apps = Path(self.temp.name) / 'apps'
        self.home.mkdir()
        info = self.apps / 'DeepSeek Harness.app/Contents'
        info.mkdir(parents=True)
        (info / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '0.2.2-rc.1'}))
        self.svc = NativeIdentityService(home=self.home, app_root=self.apps, system='Darwin')
        self.endpoint = {'name': 'hermes', 'url': URL, 'auth_mode': 'keychain', 'auth_keychain': 'fixture'}

    def test_deepseek_adapts_only_native_entry_preserving_runtime_header(self):
        path = self.home / '.dsh/profiles/desktop/cordis.patch.yml'
        path.parent.mkdir(parents=True)
        before = ('# retain comment\n- insert:\n    - id: native-test\n      name: "@deepseek-ai/dsh-mcp-client"\n'
            '      config:\n        serverName: hermes\n        transport: streamable-http\n'
            '        url: ' + URL + '\n        headers:\n          Authorization: !!js "runtimeReference()"\n'
            '    - id: unrelated\n      name: unrelated-plugin\n      config: {unchanged: true}\n')
        path.write_text(before)
        with patch('native_identity.native_patch_spec', return_value={'content': 'native fixture', 'manifest': {}}):
            plan = self.svc.plan('dsh', self.endpoint)
            self.assertEqual(plan['status'], 'ready')
            with patch('native_identity.resolve_auth', side_effect=AssertionError('must not read credential')):
                receipt = self.svc.apply('dsh', self.endpoint, plan['plan_hash'])
            self.assertIn('Authorization: !!js "runtimeReference()"', path.read_text())
            self.assertIn('name: unrelated-plugin', path.read_text())
            self.svc.rollback(receipt['receipt_id'])
            self.assertEqual(path.read_text(), before)

    def test_deepseek_unsupported_plugin_baseline_blocks_before_writes(self):
        with patch('native_identity.native_patch_spec', side_effect=ValueError('unknown baseline')):
            plan = self.svc.plan('dsh', self.endpoint)
        self.assertEqual(plan['error_code'], 'unsupported_native_plugin_baseline')
        self.assertFalse(self.svc.state_root.exists())

    def test_disabled_cordis_parent_does_not_prove_active_native_connection(self):
        entries = list(iter_cordis_mcp_entries(parse_cordis_yaml(
            '- disabled: true\n  insert:\n    - id: native\n      config: {serverName: hermes}\n')))
        self.assertTrue(entries[0]['disabled'])

    def test_corrupt_application_archive_is_never_patched(self):
        archive = self.apps / 'DeepSeek Harness.app/Contents/Resources/app.asar'
        archive.parent.mkdir()
        archive.write_bytes(b'corrupt fixture')
        with self.assertRaises(Exception):
            native_patch_spec(self.apps / 'DeepSeek Harness.app')
        self.assertEqual(archive.read_bytes(), b'corrupt fixture')

    def test_generic_repair_defers_registered_native_adapter_even_without_config(self):
        target = self.home / 'missing/mcp.json'
        result = fix_mcp_tool({'name': 'WorkBuddy', 'config_path': str(target),
            'native_identity_adapter': 'workbuddy'}, self.endpoint)
        self.assertEqual(result['status'], 'unchanged')
        self.assertFalse(target.exists())

    def test_collector_reads_exact_artifact_and_rejects_ambiguous_selector(self):
        sid = 'fixture-session'
        path = self.home / '.workbuddy/projects/fixture' / (sid + '.jsonl')
        path.parent.mkdir(parents=True)
        content = '\n'.join(json.dumps(r) for r in native_records(sid))
        path.write_text(content)
        obs = collect_evidence('workbuddy', self.home, sid, 'run=A', REPO)
        self.assertEqual(obs['native_session_id'], sid)
        other = path.parent.parent / 'other' / path.name
        other.parent.mkdir()
        other.write_text(content)
        with self.assertRaisesRegex(EvidenceError, 'ambiguous'):
            collect_evidence('workbuddy', self.home, sid, 'run=A', REPO)
        with self.assertRaisesRegex(EvidenceError, 'selector'):
            collect_evidence('workbuddy', self.home, '../fixture-session', 'run=A', REPO)

    def test_auth_project_allowlist_and_native_namespace_are_checked(self):
        rows = native_records('fixture')
        for row in rows:
            if row.get('callId') == '1' and row['type'] == 'function_call_result':
                result = json.loads(row['output']['text'])
                result['allowed_project_ids'] = []
                row['output']['text'] = json.dumps(result)
        with self.assertRaisesRegex(EvidenceError, 'project_identity_mismatch'):
            parse_records('workbuddy', rows, 'fixture', 'run=A', REPO)
        rows = native_records('fixture')
        rows[4]['arguments'] = rows[4]['arguments'].replace('mcp__WorkBuddy__', 'mcp__other__')
        with self.assertRaisesRegex(EvidenceError, 'namespace'):
            parse_records('workbuddy', rows, 'fixture', 'run=A', REPO)


if __name__ == '__main__':
    unittest.main()
