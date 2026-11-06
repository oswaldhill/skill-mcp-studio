"""Native identity controls never turn into a transport or a queue worker."""
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))

from native_identity import NativeIdentityService, NativeIdentityError
from native_evidence import parse_records, compare_conversations, EvidenceError

URL = 'https://mcp.example.test/mcp'
REPO = 'v1|git.example.test/team/repo|.'


def native_records(sid, challenge='run=A', name='WorkBuddy', wrong_id=None):
    auth = {'authenticated': True, 'allowed_project_ids': ['project-1'], 'connection': {
        'transport': 'streamable-http', 'client': {'name': name, 'version': '1.0',
        'source': 'client_info', 'protocol_version': '2025-11-25'},
        'device': {'id': 'device-1', 'display_name': 'Laptop', 'registered': True}}}
    project = {'status': 'matched', 'project_id': 'project-1', 'repo_fingerprint': 'f' * 64}
    records = [{'type': 'session-meta', 'sessionId': sid}, {'type': 'message',
        'sessionId': sid, 'role': 'user', 'content': challenge}]
    calls = [('Skill', {'skill': 'sms-workbuddy-native-identity'},
              {'type': 'text', 'text': 'SMS_NATIVE_CONVERSATION_ID=' + sid}),
        ('hermes_continuity_auth_check', {}, auth),
        ('hermes_continuity_project_resolve_identity', {'repository_key': REPO,
            'subproject_root': '.'}, project),
        ('hermes_continuity_session_binding_get', {'native_session_id': wrong_id or sid,
            'project_id': 'project-1', 'repo_fingerprint': 'f' * 64},
            {'status': 'unbound', 'binding_revision': 0})]
    for i, (tool, args, result) in enumerate(calls):
        native = tool == 'Skill'
        records += [{'type': 'function_call', 'sessionId': sid, 'callId': str(i),
            'name': tool if native else 'DeferExecuteTool', 'arguments': json.dumps(args
                if native else {'toolName': 'mcp__WorkBuddy__' + tool, 'params': args})},
            {'type': 'function_call_result', 'sessionId': sid, 'callId': str(i),
             'name': tool if native else 'DeferExecuteTool', 'status': 'completed',
             'output': result if native else {'type': 'text', 'text': json.dumps(result)}}]
    return records


class NativeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.apps = Path(self.temp.name) / 'Applications'
        self.home.mkdir()
        self.service = NativeIdentityService(home=self.home, app_root=self.apps, system='Darwin')
        self.endpoint = {'name': 'hermes', 'url': URL, 'auth_mode': 'keychain',
                         'auth_keychain': 'test-service', 'auth_keychain_account': 'test-account'}

    def install(self, app='WorkBuddy', version='5.9.3'):
        p = self.apps / (app + '.app') / 'Contents'
        p.mkdir(parents=True)
        (p / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': version}))

    def config(self, data):
        p = self.home / '.workbuddy/mcp.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
        return p

    def test_residual_config_does_not_prove_installation_or_auth(self):
        self.config({'mcpServers': {'WorkBuddy': {'url': URL}}})
        row = self.service.inspect('workbuddy', self.endpoint)
        self.assertFalse(row['installed'])
        self.assertEqual(row['authentication'], 'unchecked')
        self.assertEqual(row['conversation'], 'unchecked')

    def test_plan_is_read_only_and_secret_free(self):
        self.install()
        p = self.config({'other': 5, 'mcpServers': {'hermes': {'url': URL,
            'headers': {'Authorization': 'Bearer SECRET-NOT-FOR-OUTPUT'}}, 'other': {'command': 'other'}}})
        before = p.read_bytes()
        plan = self.service.plan('workbuddy', self.endpoint)
        self.assertNotIn('SECRET-NOT-FOR-OUTPUT', json.dumps(plan))
        self.assertEqual(p.read_bytes(), before)
        self.assertFalse(self.service.state_root.exists())
        self.assertIn('rename_connection', plan['changes'])

    def test_apply_preserves_headers_and_other_services_and_installs_native_skill(self):
        self.install()
        p = self.config({'custom': 5, 'mcpServers': {'hermes': {'url': URL,
            'headers': {'Authorization': 'Bearer secret'}}, 'other': {'command': 'other'}}})
        plan = self.service.plan('workbuddy', self.endpoint)
        receipt = self.service.apply('workbuddy', self.endpoint, plan['plan_hash'])
        saved = json.loads(p.read_text())
        self.assertEqual(saved['mcpServers']['WorkBuddy']['headers']['Authorization'], 'Bearer secret')
        self.assertEqual(saved['mcpServers']['other'], {'command': 'other'})
        self.assertEqual(saved['custom'], 5)
        self.assertNotIn('hermes', saved['mcpServers'])
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('secret', json.dumps(receipt))
        self.assertEqual(receipt['verification'], 'not_run')
        self.assertTrue((self.home / '.workbuddy/skills/sms-workbuddy-native-identity/SKILL.md').exists())

    def test_stale_plan_cannot_overwrite_concurrent_edit(self):
        self.install()
        p = self.config({'mcpServers': {'hermes': {'url': URL}}})
        plan = self.service.plan('workbuddy', self.endpoint)
        p.write_text('{"mcpServers":{},"concurrent":true}')
        with self.assertRaises(NativeIdentityError):
            self.service.apply('workbuddy', self.endpoint, plan['plan_hash'])
        self.assertTrue(json.loads(p.read_text())['concurrent'])

    def test_keychain_is_resolved_only_on_explicit_apply(self):
        self.install()
        self.config({'mcpServers': {}})
        with patch('native_identity.resolve_auth', return_value={'ok': True, 'token': 'vault-secret'}) as get:
            plan = self.service.plan('workbuddy', self.endpoint)
            get.assert_not_called()
            self.service.apply('workbuddy', self.endpoint, plan['plan_hash'])
            get.assert_called_once()
        self.assertNotIn('vault-secret', json.dumps(self.service.inspect('workbuddy', self.endpoint)))

    def test_stdio_is_not_implicitly_replaced(self):
        self.install()
        self.config({'mcpServers': {'hermes': {'command': 'old-bridge', 'args': []}}})
        plan = self.service.plan('workbuddy', self.endpoint)
        self.assertEqual(plan['status'], 'blocked')
        with self.assertRaises(NativeIdentityError):
            self.service.apply('workbuddy', self.endpoint, plan['plan_hash'])

    def test_unknown_workbuddy_version_is_not_silently_supported(self):
        self.install(version='99.0')
        self.config({'mcpServers': {}})
        self.assertEqual(self.service.plan('workbuddy', self.endpoint)['status'], 'blocked')

    def test_rollback_rejects_user_edits_and_path_traversal(self):
        self.install()
        p = self.config({'mcpServers': {'hermes': {'url': URL, 'headers': {'Authorization': 'Bearer retained'}}}})
        r = self.service.apply('workbuddy', self.endpoint,
                               self.service.plan('workbuddy', self.endpoint)['plan_hash'])
        p.write_text('{"user":"changed"}')
        with self.assertRaises(NativeIdentityError):
            self.service.rollback(r['receipt_id'])
        with self.assertRaises(NativeIdentityError):
            self.service.rollback('../escape')

    def test_verification_instructions_do_not_contain_supplied_chat_ids_or_secret(self):
        self.install()
        run = self.service.start_verification('workbuddy', self.endpoint, REPO)
        self.assertNotEqual(run['prompts']['A'], run['prompts']['B'])
        self.assertIn('${CODEBUDDY_SESSION_ID}', self.service.skill_text('workbuddy'))
        self.assertIn('SMS_NATIVE_RUN=', run['prompts']['A'])
        self.assertNotIn('token', run['prompts']['A'])


class NativeEvidenceTests(unittest.TestCase):
    def parse(self, records=None, sid='chat-A', challenge='run=A'):
        return parse_records('workbuddy', records or native_records(sid), sid, challenge, REPO)

    def test_only_raw_native_calls_count_not_assistant_summary(self):
        records = [{'type': 'message', 'role': 'user', 'content': 'run=A'},
            {'type': 'message', 'role': 'assistant', 'content': 'authenticated true, all passed'}]
        with self.assertRaises(EvidenceError):
            self.parse(records)

    def test_real_source_and_rpc_parameters_must_agree(self):
        with self.assertRaises(EvidenceError):
            self.parse(native_records('chat-A', wrong_id='chat-B'))

    def test_unresolved_native_placeholder_is_rejected(self):
        r = native_records('chat-A')
        r[3]['output']['text'] = 'SMS_NATIVE_CONVERSATION_ID=${CODEBUDDY_SESSION_ID}'
        with self.assertRaises(EvidenceError):
            self.parse(r)

    def test_old_history_cannot_be_reused_for_new_challenge(self):
        with self.assertRaises(EvidenceError):
            self.parse(challenge='new-run=A')

    def test_native_name_mismatch_is_rejected(self):
        with self.assertRaises(EvidenceError):
            self.parse(native_records('chat-A', name='hermes'))

    def test_pair_rejects_same_chat_or_different_devices(self):
        a = self.parse()
        self.assertFalse(compare_conversations(a, a)['ok'])
        b = self.parse(native_records('chat-B'), sid='chat-B')
        self.assertTrue(compare_conversations(a, b)['ok'])
        b['device']['id'] = 'other-device'
        self.assertFalse(compare_conversations(a, b)['ok'])

    def test_receipt_does_not_promote_unbound_or_claim_all_call_propagation(self):
        a = self.parse()
        self.assertEqual(a['binding']['status'], 'unbound')
        self.assertEqual(a['evidence_source'], 'native_host_tool_history')
        self.assertEqual(a['reporting_mode'], 'explicit_session_tool_argument')
        self.assertNotIn('client_id', json.dumps(a))


if __name__ == '__main__':
    unittest.main()
