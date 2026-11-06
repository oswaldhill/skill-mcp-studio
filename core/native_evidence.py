"""Read exact native host tool history. No MCP/network client or queue access."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
IDENTITIES = {'workbuddy': 'WorkBuddy', 'deepseek-harness': 'DeepSeek Harness'}
AUTH = 'hermes_continuity_auth_check'
PROJECT = 'hermes_continuity_project_resolve_identity'
BINDING = 'hermes_continuity_session_binding_get'


class EvidenceError(ValueError):
    pass


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key in ('text', 'content', 'message', 'data', 'stdout', 'output'):
            if key in value:
                yield from _strings(value[key])


def _rpc(value):
    """Unwrap only canonical native tool-result envelopes, never assistant prose."""
    for _ in range(8):
        value = _json(value)
        if not isinstance(value, dict) or value.get('isError') is True:
            raise EvidenceError('native_rpc_error_or_invalid_result')
        if any(k in value for k in ('authenticated', 'status')):
            return value
        if isinstance(value.get('structuredContent'), dict):
            value = value['structuredContent']
        elif value.get('type') == 'text':
            value = value.get('text')
        elif isinstance(value.get('content'), list) and value['content']:
            value = value['content'][0]
        else:
            raise EvidenceError('native_rpc_result_unavailable')
    raise EvidenceError('native_rpc_envelope_too_deep')


def parse_records(adapter, records, session_id, challenge, repository_key, server_name='hermes'):
    if adapter not in IDENTITIES:
        raise EvidenceError('unsupported_adapter')
    identity = False
    challenge_index = None
    source_sessions = []
    for i, row in enumerate(records):
        if row.get('type') in ('session-meta', 'session'):
            source_sessions.append(row.get('sessionId') or row.get('id'))
        if row.get('type') == 'message' and row.get('role') == 'user':
            user_text = ' '.join(_strings(row.get('content')))
        elif row.get('type') == 'user/message':
            user_text = ' '.join(_strings(row.get('data')))
        else:
            continue
        if challenge in user_text:
            challenge_index = i
    if source_sessions and set(source_sessions) != {session_id}:
        raise EvidenceError('native_artifact_session_mismatch')
    if challenge_index is None:
        raise EvidenceError('fresh_native_challenge_not_found')
    if not source_sessions:
        raise EvidenceError('native_session_header_missing')

    calls = {}
    auth = project = binding = None
    selected = []
    allowed_projects = []
    for row in records[challenge_index + 1:]:
        kind = row.get('type')
        data = row.get('data', {}) if kind in ('tool/call', 'tool/result') else row
        if kind in ('function_call', 'tool/call'):
            if row.get('sessionId', session_id) != session_id:
                raise EvidenceError('mixed_native_sessions')
            tool = data.get('name', '')
            args = _json(data.get('arguments'))
            if not isinstance(args, dict):
                raise EvidenceError('native_arguments_invalid')
            if tool == 'DeferExecuteTool':
                tool, args = args.get('toolName', ''), args.get('params', {})
            if tool.startswith('mcp__'):
                namespace = 'WorkBuddy' if adapter == 'workbuddy' else server_name
                if not tool.startswith('mcp__' + namespace + '__'):
                    raise EvidenceError('native_server_namespace_mismatch')
                tool = tool.rsplit('__', 1)[-1]
                if tool not in (AUTH, PROJECT, BINDING):
                    raise EvidenceError('unexpected_mcp_operation_in_identity_check')
            elif tool not in ('Skill', 'skill', 'ToolSearch', 'bash'):
                raise EvidenceError('unexpected_host_operation_in_identity_check')
            if tool == 'bash':
                command = args.get('command', '')
                # Only this one non-credential runtime variable; no shell/network fallback.
                if not re.fullmatch(r'''printf\s+['"]%s(?:\\+n)?['"]\s+\\*["']?\$DSH_SESSION_ID\\*["']?\s*''', command):
                    raise EvidenceError('identity_command_not_single_variable_read')
            calls[data.get('callId')] = (tool, args)
        elif kind in ('function_call_result', 'tool/result'):
            if kind == 'tool/result':
                message = data.get('message', {})
                call_id = message.get('toolCallId') or message.get('source', {}).get('callId')
                output = message
                failed = message.get('isError') is True
            else:
                call_id = data.get('callId')
                output = data.get('output')
                failed = data.get('status') not in ('completed', 'success')
            if call_id not in calls:
                continue
            tool, args = calls.pop(call_id)
            if failed:
                raise EvidenceError('native_tool_failed')
            if tool in ('Skill', 'skill'):
                if adapter == 'workbuddy' and args.get('skill', args.get('name')) == 'sms-workbuddy-native-identity':
                    identity = ('SMS_NATIVE_CONVERSATION_ID=' + session_id) in '\n'.join(_strings(output))
            elif tool == 'bash' and adapter == 'deepseek-harness':
                identity = session_id in '\n'.join(_strings(output))
            elif tool in (AUTH, PROJECT, BINDING):
                result = _rpc(output)
                selected.append({'call_id': call_id, 'tool': tool, 'arguments': args,
                                 'result_hash': hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()})
                if tool == AUTH:
                    client = result.get('connection', {}).get('client', {})
                    device = result.get('connection', {}).get('device', {})
                    if (result.get('authenticated') is not True or client.get('name') != IDENTITIES[adapter]
                            or client.get('source') != 'client_info' or not device.get('id')
                            or device.get('registered') is not True
                            or result.get('connection', {}).get('transport') != 'streamable-http'):
                        raise EvidenceError('native_auth_or_client_identity_mismatch')
                    allowed_projects = result.get('allowed_project_ids', [])
                    auth = {'device': {k: device.get(k) for k in ('id', 'display_name', 'registered')},
                            'client': {k: client.get(k) for k in ('name', 'version', 'source', 'protocol_version')}}
                elif tool == PROJECT:
                    if (not auth or args.get('repository_key') != repository_key
                            or result.get('status') != 'matched' or not result.get('project_id')
                            or result.get('project_id') not in allowed_projects
                            or not result.get('repo_fingerprint')):
                        raise EvidenceError('native_project_identity_mismatch')
                    project = {k: result.get(k) for k in ('project_id', 'repo_fingerprint')}
                else:
                    if (not identity or not auth or not project
                            or args.get('native_session_id') != session_id
                            or any(args.get(k) != v for k, v in project.items())
                            or result.get('status') not in ('bound', 'unbound')):
                        raise EvidenceError('native_conversation_or_binding_mismatch')
                    binding = {k: result.get(k) for k in ('status', 'task_id', 'binding_revision')}
                    if (binding['status'] == 'unbound' and binding['binding_revision'] != 0
                            or binding['status'] == 'bound' and
                            (not binding['task_id'] or not isinstance(binding['binding_revision'], int)
                             or binding['binding_revision'] < 1)):
                        raise EvidenceError('native_binding_result_inconsistent')
                    break
    if not identity or not binding:
        raise EvidenceError('complete_native_identity_evidence_required')
    return {'adapter_id': adapter, 'native_session_id': session_id, **auth,
            'project': project, 'binding': binding,
            'evidence_source': 'native_host_tool_history',
            'reporting_mode': 'explicit_session_tool_argument',
            'source_calls': selected,
            'evidence_hash': hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()}


def compare_conversations(a, b):
    checks = {
        'native_sources': all(x.get('evidence_source') == 'native_host_tool_history' for x in (a, b)),
        'same_adapter': a.get('adapter_id') == b.get('adapter_id'),
        'different_native_ids': bool(a.get('native_session_id') and b.get('native_session_id')
                                    and a['native_session_id'] != b['native_session_id']),
        'same_device': bool(a.get('device', {}).get('id') and a.get('device') == b.get('device')),
        'same_native_client': a.get('client', {}).get('name') == b.get('client', {}).get('name'),
        'same_project': bool(a.get('project') and a.get('project') == b.get('project')),
    }
    return {'ok': all(checks.values()), 'checks': checks,
            'scope': 'explicit_session_tool_argument',
            'all_call_propagation_verified': False, 'task_binding_changed': False}


def collect_evidence(adapter, home, session_id, challenge, repository_key, server_name='hermes'):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', session_id):
        raise EvidenceError('invalid_native_session_selector')
    home = Path(home)
    if adapter == 'workbuddy':
        root = home / '.workbuddy/projects'
        candidates = list(root.glob('*/' + session_id + '.jsonl'))
    elif adapter == 'deepseek-harness':
        root = home / '.dsh/sessions'
        candidates = list(root.glob('*/' + session_id + '/session.v4.jsonl.zstd'))
    else:
        raise EvidenceError('unsupported_adapter')
    if len(candidates) != 1:
        raise EvidenceError('exact_native_session_artifact_missing_or_ambiguous')
    path = candidates[0]
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise EvidenceError('unsafe_or_oversized_native_artifact')
    if adapter == 'deepseek-harness':
        zstd = shutil.which('zstd') or next((p for p in ('/opt/homebrew/bin/zstd',
            '/usr/local/bin/zstd') if Path(p).is_file()), None)
        if not zstd:
            raise EvidenceError('zstd_required_for_native_history_readback')
        with subprocess.Popen([zstd, '-d', '-c', str(path)], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as proc:
            data = proc.stdout.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                proc.kill()
                raise EvidenceError('native_artifact_decompressed_limit')
            if proc.wait(timeout=20):
                raise EvidenceError('native_artifact_decompression_failed')
    else:
        data = path.read_bytes()
    try:
        records = [json.loads(line) for line in data.splitlines() if line.strip()]
    except (ValueError, UnicodeError):
        raise EvidenceError('native_artifact_incomplete_or_invalid') from None
    observation = parse_records(adapter, records, session_id, challenge, repository_key, server_name)
    observation['artifact'] = str(path)
    # Persist filtered facts and source call hashes only, never transcripts/headers.
    return observation
