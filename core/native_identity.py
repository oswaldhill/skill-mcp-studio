"""Native MCP identity governance. Local control plane; never sends MCP requests.

Read-only inspection, optimistic plans, private backups, safe rollback, and
verification from exact native host histories. No hooks, bridge, or outbox API.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import re
import secrets
import struct
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from auth_secret import resolve_auth
from config_codec import parse_cordis_yaml, iter_cordis_mcp_entries
from file_atomic import atomic_write
from native_evidence import collect_evidence, compare_conversations
from native_patch import native_patch_spec

HOSTS = {
    'workbuddy': {'name': 'WorkBuddy', 'app': 'WorkBuddy.app', 'version': '5.9.3',
        'config': '.workbuddy/mcp.json', 'skills': '.workbuddy/skills',
        'conversation_source': 'native_skill_substitution'},
    'deepseek-harness': {'name': 'DeepSeek Harness', 'app': 'DeepSeek Harness.app',
        'version': '0.2.2-rc.1', 'config': '.dsh/profiles/desktop/cordis.patch.yml',
        'skills': '.dsh/skills', 'conversation_source': 'runtime_env_single_read'},
}


class NativeIdentityError(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def adapter_id(value):
    aliases = {'workbuddy': 'workbuddy', 'codebuddy': 'workbuddy', 'dsh': 'deepseek-harness',
               'deepseek': 'deepseek-harness', 'deepseekharness': 'deepseek-harness',
               'deepseek-harness': 'deepseek-harness'}
    key = re.sub(r'\s+', '', str(value)).lower()
    if key not in aliases:
        raise NativeIdentityError('unsupported_native_host')
    return aliases[key]


cordis_entries = iter_cordis_mcp_entries


def _cordis_node(text, target_id, key):
    """Find exact scalar range without evaluating !!js or reserializing other entries."""
    root = yaml.compose(text, Loader=yaml.SafeLoader)

    def visit(node):
        if isinstance(node, yaml.MappingNode):
            fields = {k.value: v for k, v in node.value if isinstance(k, yaml.ScalarNode)}
            if fields.get('id') and fields['id'].value == target_id:
                return fields.get(key)
            for name in ('insert', 'entries', 'plugins'):
                if name in fields:
                    found = visit(fields[name])
                    if found is not None:
                        return found
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                found = visit(child)
                if found is not None:
                    return found
        return None
    return visit(root)


def _endpoint(endpoint):
    url = str(endpoint.get('url', ''))
    parsed = urlsplit(url)
    name = str(endpoint.get('name') or 'hermes')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', name)):
        raise NativeIdentityError('native_https_endpoint_and_safe_namespace_required')
    return url, name


def _js_header(endpoint):
    """A native DSH runtime expression, not a helper process or MCP bridge."""
    mode = endpoint.get('auth_mode', 'token')
    if mode == 'keychain':
        service = endpoint.get('auth_keychain', '')
        if not service:
            raise NativeIdentityError('credential_reference_required')
        args = ['find-generic-password', '-s', service]
        if endpoint.get('auth_keychain_account'):
            args += ['-a', endpoint['auth_keychain_account']]
        args += ['-w']
        expr = "'Bearer ' + process.getBuiltinModule('child_process').execFileSync('/usr/bin/security', "
        expr += json.dumps(args) + ", {encoding:'utf8',stdio:['ignore','pipe','ignore']}).trim()"
    elif mode == 'env' and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', endpoint.get('auth_token_env', '')):
        expr = "'Bearer ' + process.env[" + json.dumps(endpoint['auth_token_env']) + ']'
    elif mode == 'file' and endpoint.get('auth_file'):
        expr = "'Bearer ' + process.getBuiltinModule('fs').readFileSync("
        expr += json.dumps(os.path.expanduser(endpoint['auth_file'])) + ", 'utf8').trim()"
    else:
        raise NativeIdentityError('native_dsh_requires_keychain_env_or_file_reference')
    return '!!js ' + json.dumps(expr)


class NativeIdentityService:
    def __init__(self, *, home=None, app_root=None, system=None):
        self.home = Path(home) if home is not None else Path.home()
        self.apps = Path(app_root or '/Applications')
        self.system = system or platform.system()
        self.state_root = self.home / '.local/share/skill-mcp-studio/native-mcp'

    def _host(self, host):
        key = adapter_id(host)
        return key, HOSTS[key], self.home / HOSTS[key]['config']

    def _read(self, path):
        if path.is_symlink() or not path.resolve().is_relative_to(self.home.resolve()):
            raise NativeIdentityError('unsafe_native_config_path')
        if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
            raise NativeIdentityError('native_config_size_limit')
        return path.read_text() if path.exists() else ''

    def _version(self, spec):
        path = self.apps / spec['app']
        try:
            info = plistlib.loads((path / 'Contents/Info.plist').read_bytes())
            return path.exists(), str(info.get('CFBundleShortVersionString', ''))
        except (OSError, ValueError, plistlib.InvalidFileException):
            return path.exists(), ''

    def _config(self, key, text, endpoint):
        url, name = _endpoint(endpoint)
        if key == 'workbuddy':
            data = json.loads(text or '{}')
            if not isinstance(data, dict) or not isinstance(data.get('mcpServers', {}), dict):
                raise NativeIdentityError('invalid_native_config')
            servers = data.get('mcpServers', {})
            if any(not isinstance(v, dict) for v in servers.values()):
                raise NativeIdentityError('invalid_native_server_entry')
            matching = [(n, v) for n, v in servers.items() if isinstance(v, dict) and v.get('url') == url]
            if len(matching) > 1:
                raise NativeIdentityError('ambiguous_native_connections')
            for candidate in ('WorkBuddy', name):
                if candidate in servers and servers[candidate].get('command'):
                    raise NativeIdentityError('legacy_stdio_preserved_not_replaced')
            if matching:
                selected, config = matching[0]
                if selected != 'WorkBuddy' and 'WorkBuddy' in servers:
                    raise NativeIdentityError('native_connection_name_conflict')
                if config.get('command'):
                    raise NativeIdentityError('mixed_native_transport')
                if config.get('disabled') is True:
                    raise NativeIdentityError('native_connection_disabled_use_host_flow')
            else:
                if 'WorkBuddy' in servers or name in servers:
                    raise NativeIdentityError('native_endpoint_conflict')
                selected, config = None, {}
            return data, selected, config
        data = parse_cordis_yaml(text or '[]')
        if not isinstance(data, list):
            raise NativeIdentityError('invalid_native_cordis_config')
        candidates = [e for e in cordis_entries(data)
                      if e['config'].get('serverName') == name]
        if len(candidates) > 1:
            raise NativeIdentityError('ambiguous_native_connections')
        if candidates:
            entry = candidates[0]
            if entry['config'].get('transport') != 'streamable-http':
                raise NativeIdentityError('legacy_stdio_preserved_not_replaced')
            if entry['config'].get('url') != url or entry.get('disabled'):
                raise NativeIdentityError('native_endpoint_conflict_or_disabled')
            if not entry.get('id') or not entry.get('name'):
                raise NativeIdentityError('native_plugin_identity_required')
            return data, entry, entry['config']
        return data, None, {}

    def inspect(self, host, endpoint=None):
        key, spec, path = self._host(host)
        installed, version = self._version(spec)
        out = {'adapter_id': key, 'name': spec['name'], 'installed': installed,
            'app_version': version or None,
            'supported_version': self.system == 'Darwin' and version == spec['version'],
            'config_path': str(path), 'config_state': 'absent', 'client_name_state': 'unchecked',
            'authentication': 'unchecked', 'conversation': 'unchecked', 'trust': 'unknown',
            'conversation_source': spec['conversation_source'],
            'reporting_mode': 'explicit_session_tool_argument',
            'all_call_propagation_verified': False}
        if endpoint is not None:
            try:
                _, selected, _ = self._config(key, self._read(path), endpoint)
                out['config_state'] = 'configured' if selected else 'absent'
                if key == 'workbuddy':
                    out['client_name_state'] = 'configured' if selected == 'WorkBuddy' else 'mismatch'
                    out['credential_strategy'] = 'protected_static_header'
                    if selected:
                        approvals = self.home / '.workbuddy/mcp-approvals.json'
                        if approvals.exists():
                            entries = json.loads(self._read(approvals))
                            out['trust'] = 'host_recheck_required' if any(
                                str(k).endswith('::WorkBuddy') for k in entries) else 'pending'
                else:
                    out['credential_strategy'] = 'native_runtime_reference'
            except (ValueError, OSError, yaml.YAMLError):
                out['config_state'] = 'invalid'
        return out

    def skill_text(self, host):
        key, spec, _ = self._host(host)
        source = ('Load this via the native Skill tool.\n'
            'SMS_NATIVE_CONVERSATION_ID=${CODEBUDDY_SESSION_ID}\n'
            'Reject unresolved placeholders; never Read a file to obtain this ID.' if key == 'workbuddy'
            else 'Use only the native terminal to run: printf \'%s\\n\' "$DSH_SESSION_ID".\n'
                 'Read only this non-credential variable; the terminal must not connect MCP.')
        return (f'---\nname: sms-{key}-native-identity\n'
            f'description: Native MCP identity verification for {spec["name"]} only.\n---\n\n'
            f'# {spec["name"]} native MCP identity\n\n{source}\n\n'
            'Use the SMS_NATIVE_RUN and SMS_NATIVE_SLOT challenge from the current user prompt. '
            'Never reuse an earlier chat ID or generate one. Use native ToolSearch if needed. '
            f'Call native hermes_continuity_auth_check, require clientInfo name {spec["name"]}. '
            'Call native hermes_continuity_project_resolve_identity with the exact '
            'SMS_REPOSITORY_KEY from the prompt UNCHANGED, including the final |. suffix. '
            'Only use matched project_id/repo_fingerprint. Call native hermes_continuity_session_binding_get '
            'with the current native conversation ID and that matched identity. '
            'Report actual results; unbound is valid and remains unchanged. '
            'Only these three read-only MCP operations are allowed in this verification. '
            'Do not create/bind tasks, write notes/memory/files, invoke hooks/workers/bridges, '
            'read credentials, dump the environment, or use a terminal/HTTP client to connect MCP. '
            'Do not claim generic MCP calls automatically carry conversation IDs.\n')

    def _skill_path(self, key):
        return self.home / HOSTS[key]['skills'] / ('sms-' + key + '-native-identity/SKILL.md')

    def _material(self, host, endpoint, inject=False):
        key, spec, path = self._host(host)
        text = self._read(path)
        row = self.inspect(key, endpoint)
        if not row['installed'] or not row['supported_version']:
            raise NativeIdentityError('native_host_absent_or_unsupported_version')
        data, selected, config = self._config(key, text, endpoint)
        url, name = _endpoint(endpoint)
        changes = []
        module = None
        if key == 'workbuddy':
            if selected != 'WorkBuddy':
                changes.append('rename_connection' if selected else 'add_native_connection')
            if not isinstance(config.get('headers', {}), dict):
                raise NativeIdentityError('invalid_native_headers')
            header = config.get('headers', {}).get('Authorization', '')
            if not isinstance(header, str):
                raise NativeIdentityError('invalid_native_authorization_header')
            if not header or '${' in header:
                changes.append('inject_existing_credential')
                if inject:
                    resolved = resolve_auth(endpoint)
                    if not resolved.get('ok') or not resolved.get('token'):
                        raise NativeIdentityError('credential_unavailable')
                    header = 'Bearer ' + resolved['token']
            entry = dict(config)
            entry['url'] = url
            if inject and header:
                entry['headers'] = {**entry.get('headers', {}), 'Authorization': header}
            servers = dict(data.get('mcpServers', {}))
            if selected and selected != 'WorkBuddy':
                servers.pop(selected)
            servers['WorkBuddy'] = entry
            data['mcpServers'] = servers
            rendered = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
            # A compliant entry does not need reformatting, replacing, or credential reads.
            if not changes:
                rendered = text
        else:
            try:
                patch = native_patch_spec(self.apps / spec['app'])
            except (ValueError, OSError, KeyError, struct.error):
                raise NativeIdentityError('unsupported_native_plugin_baseline') from None
            module_path = self.state_root / 'plugins/deepseek-0.2.2-rc.1/lib/index.js'
            if selected:
                existing = Path(selected['name'])
                safe_roots = (self.home / '.dsh/native-plugins', self.state_root / 'plugins')
                if any(existing.is_relative_to(p) for p in safe_roots) and existing.is_file():
                    if existing.read_text() == patch['content']:
                        module_path = existing
                if selected['name'] != str(module_path):
                    node = _cordis_node(text, selected['id'], 'name')
                    if node is None:
                        raise NativeIdentityError('native_plugin_scalar_not_found')
                    rendered = text[:node.start_mark.index] + json.dumps(str(module_path)) + text[node.end_mark.index:]
                    changes.append('adapt_native_client_name')
                else:
                    rendered = text
                header = config.get('headers', {}).get('Authorization', '')
                if not header or '${' in header:
                    raise NativeIdentityError('existing_native_header_requires_explicit_credential_migration')
            else:
                header = _js_header(endpoint)
                rendered = text + ('\n' if text and not text.endswith('\n') else '')
                rendered += ('- insert:\n    - id: sms-native-' + name + '\n      name: '
                    + json.dumps(str(module_path)) + '\n      config:\n        serverName: '
                    + json.dumps(name) + '\n        transport: streamable-http\n        url: '
                    + json.dumps(url) + '\n        headers:\n          Authorization: ' + header + '\n')
                changes.append('add_native_connection')
            parse_cordis_yaml(rendered)
            module = (module_path, patch)
        skill = self._skill_path(key)
        if not skill.exists() or skill.read_text() != self.skill_text(key):
            changes.append('install_native_identity_skill')
        if path.exists() and path.stat().st_mode & 0o777 != 0o600:
            changes.append('protect_config_permissions')
        return key, path, text, rendered, changes, module

    def plan(self, host, endpoint):
        key, _, path = self._host(host)
        status, error, changes = 'ready', None, []
        rendered, module = '', None
        try:
            _, _, text, rendered, changes, module = self._material(key, endpoint)
        except (ValueError, OSError, yaml.YAMLError) as exc:
            status, error, text = 'blocked', str(exc) if isinstance(exc, NativeIdentityError) else 'invalid_native_configuration', self._read(path)
        skill = self._skill_path(key)
        fingerprint = {'adapter': key, 'config': _hash(text.encode()),
            'skill': _hash(skill.read_bytes()) if skill.exists() else None,
            'target': {k: endpoint.get(k) for k in ('name', 'url', 'auth_mode', 'auth_keychain',
                'auth_keychain_account', 'auth_token_env', 'auth_file')},
            'credential_digest': _hash(str(endpoint.get('auth_token', '')).encode()),
            'app_version': self._version(HOSTS[key])[1],
            'planned_changes': changes, 'rendered_digest': _hash(rendered.encode()),
            'plugin_target': str(module[0]) if module else None,
            'existing_plugin_digest': _hash(module[0].read_bytes()) if module and module[0].exists() else None}
        return {'adapter_id': key, 'status': status, 'error_code': error,
            'plan_hash': _hash(json.dumps(fingerprint, sort_keys=True).encode()),
            'config_path': str(path), 'changes': changes,
            'native_transport': 'streamable-http', 'verification': 'not_run',
            'trust_action': 'normal_host_trust_flow' if key == 'workbuddy' else 'not_required',
            'reload_action': 'wait_until_host_idle_then_native_reload',
            'queue_action': 'none', 'credential_values_included': False}

    def _save(self, relative, value):
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.state_root.resolve().is_relative_to(self.home.resolve()):
            raise NativeIdentityError('unsafe_native_state_directory')
        os.chmod(self.state_root, 0o700)
        path = self.state_root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.resolve().is_relative_to(self.state_root.resolve()):
            raise NativeIdentityError('unsafe_native_state_path')
        atomic_write(str(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n', 0o600)

    def _load(self, group, identifier):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise NativeIdentityError('invalid_native_record_selector')
        path = self.state_root / group / (identifier + '.json')
        if not path.resolve().is_relative_to(self.state_root.resolve()):
            raise NativeIdentityError('unsafe_native_state_path')
        return json.loads(path.read_text())

    def apply(self, host, endpoint, expected_hash):
        plan = self.plan(host, endpoint)
        if plan['status'] != 'ready' or plan['plan_hash'] != expected_hash:
            raise NativeIdentityError('blocked_or_stale_native_plan')
        key, path, original, rendered, changes, module = self._material(host, endpoint, inject=True)
        identifier = secrets.token_hex(16)
        receipt = {'receipt_id': identifier, 'adapter_id': key, 'at': _now(),
                   'verification': 'not_run', 'queue_action': 'none', 'files': []}
        writes = [(path, rendered), (self._skill_path(key), self.skill_text(key))]
        if module and (not module[0].exists() or module[0].read_text() != module[1]['content']):
            writes += [(module[0], module[1]['content']),
                       (module[0].parent.parent / 'patch-manifest.json', json.dumps(module[1]['manifest'], indent=2) + '\n')]
        try:
            for target, content in writes:
                if target.exists() and target.read_text() == content and target.stat().st_mode & 0o777 == 0o600:
                    continue
                if not target.resolve().is_relative_to(self.home.resolve()):
                    raise NativeIdentityError('unsafe_native_write_target')
                before = target.read_text() if target.exists() else None
                if target == path and before != (original if original else None) and before != original:
                    raise NativeIdentityError('native_config_changed_during_apply')
                backup_key = 'backups/' + identifier + '/' + str(len(receipt['files'])) + '.json'
                self._save(backup_key, {'path': str(target), 'content': before})
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(str(target), content, 0o600)
                receipt['files'].append({'path': str(target), 'backup_key': backup_key,
                                         'applied_hash': _hash(content.encode())})
            if path.read_text() != rendered:
                raise NativeIdentityError('native_config_readback_failed')
            self._config(key, path.read_text(), endpoint)
            receipt['status'] = 'applied' if changes else 'unchanged'
            self._save('receipts/' + identifier + '.json', receipt)
            return receipt
        except Exception:
            self._restore_files(receipt)
            raise NativeIdentityError('native_apply_failed_rolled_back') from None

    def _restore_files(self, receipt):
        for item in reversed(receipt['files']):
            target = Path(item['path'])
            if not target.exists() or _hash(target.read_bytes()) != item['applied_hash']:
                raise NativeIdentityError('native_rollback_conflict')
            backup = json.loads((self.state_root / item['backup_key']).read_text())
            if backup['path'] != str(target) or not target.resolve().is_relative_to(self.home.resolve()):
                raise NativeIdentityError('unsafe_native_rollback_target')
            if backup['content'] is None:
                target.unlink()  # Only a file this receipt created, with exact post-write hash.
            else:
                atomic_write(str(target), backup['content'], 0o600)

    def rollback(self, receipt_id):
        receipt = self._load('receipts', receipt_id)
        # Preflight ALL files before mutation; preserve every concurrent edit.
        for item in receipt['files']:
            p = Path(item['path'])
            if not p.is_file() or _hash(p.read_bytes()) != item['applied_hash']:
                raise NativeIdentityError('native_rollback_conflict')
        self._restore_files(receipt)
        return {'status': 'rolled_back', 'receipt_id': receipt_id, 'queue_action': 'none'}

    def start_verification(self, host, endpoint, repository_key):
        key = adapter_id(host)
        _endpoint(endpoint)
        if not re.fullmatch(r'v1\|[^|\s]+\|[^|\s]+', repository_key):
            raise NativeIdentityError('canonical_repository_key_required')
        identifier = secrets.token_hex(16)  # Run correlation only, NEVER a conversation ID.
        prompts = {slot: (f'SMS_NATIVE_RUN={identifier};SMS_NATIVE_SLOT={slot}\n'
            f'SMS_REPOSITORY_KEY={repository_key}\n'
            f'Load sms-{key}-native-identity using your native Skill tool. '
            'Obtain your CURRENT native conversation ID yourself. Perform only the three '
            'read-only native MCP identity checks in that skill and report actual results. '
            'Pass the full SMS_REPOSITORY_KEY unchanged, including its |. suffix; never split it. '
            'Do not reuse a prior chat ID, change files, write memory, create or bind tasks, '
            'read credentials, invoke hooks/bridges/workers, or replay any queue.') for slot in ('A', 'B')}
        run = {'run_id': identifier, 'adapter_id': key, 'started_at': _now(),
               'repository_key': repository_key, 'endpoint_url_hash': _hash(endpoint['url'].encode()),
               'server_name': endpoint.get('name', 'hermes'),
               'config_fingerprint': _hash(self._read(self._host(key)[2]).encode()),
               'app_version': self._version(HOSTS[key])[1],
               'prompts': prompts, 'slots': {}, 'status': 'awaiting_native_conversations'}
        self._save('runs/' + identifier + '.json', run)
        return run

    def capture(self, run_id, slot, session_id):
        run = self._load('runs', run_id)
        if slot not in ('A', 'B'):
            raise NativeIdentityError('invalid_native_verification_slot')
        if (run.get('config_fingerprint') != _hash(self._read(self._host(run['adapter_id'])[2]).encode())
                or run.get('app_version') != self._version(HOSTS[run['adapter_id']])[1]):
            raise NativeIdentityError('native_verification_config_or_version_changed')
        challenge = f'SMS_NATIVE_RUN={run_id};SMS_NATIVE_SLOT={slot}'
        observation = collect_evidence(run['adapter_id'], self.home, session_id, challenge,
                                       run['repository_key'], run.get('server_name', 'hermes'))
        run['slots'][slot] = observation
        self._save('runs/' + run_id + '.json', run)
        return {'run_id': run_id, 'slot': slot, 'observation': observation}

    def verify(self, run_id):
        run = self._load('runs', run_id)
        if set(run['slots']) != {'A', 'B'}:
            return {'run_id': run_id, 'ok': False, 'status': 'awaiting_native_conversations'}
        # Re-read native source, not an editable imported assertion/receipt.
        for slot in ('A', 'B'):
            self.capture(run_id, slot, run['slots'][slot]['native_session_id'])
        run = self._load('runs', run_id)
        result = compare_conversations(run['slots']['A'], run['slots']['B'])
        run['result'] = result
        run['status'] = 'verified_for_declared_scope' if result['ok'] else 'failed'
        self._save('runs/' + run_id + '.json', run)
        return {'run_id': run_id, 'status': run['status'], **result, 'slots': run['slots']}

    def runs(self):
        rows = []
        for path in sorted((self.state_root / 'runs').glob('*.json'), reverse=True):
            value = json.loads(path.read_text())
            rows.append({k: value.get(k) for k in ('run_id', 'adapter_id', 'started_at', 'status', 'result')})
        return sorted(rows, key=lambda r: r.get('started_at') or '', reverse=True)

    def show_run(self, run_id):
        return self._load('runs', run_id)
