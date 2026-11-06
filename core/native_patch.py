"""Version-pinned adaptation of a released native DSH plugin, not a bridge/build."""
import hashlib
import json
import re
import struct
from pathlib import Path

UPSTREAM_SHA256 = '64dfc9127a47d9d453d72022b47d3b8d8a5c82cad756ac1114b09faf1a956120'
ENTRY = 'dsh/node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js'


def native_patch_spec(app_path):
    archive = Path(app_path) / 'Contents/Resources/app.asar'
    with archive.open('rb') as stream:
        header = struct.unpack('<IIII', stream.read(16))
        if header[3] > 32 * 1024 * 1024:
            raise ValueError('native_archive_header_limit')
        tree = json.loads(stream.read(header[3]))

        def read(path):
            node = tree
            for part in path.split('/'):
                node = node['files'][part]
            if node.get('unpacked') or node.get('size', 0) > 2 * 1024 * 1024:
                raise ValueError('unsupported_native_archive_entry')
            stream.seek(8 + header[1] + int(node['offset']))
            return stream.read(node['size'])

        original = read(ENTRY)
        if hashlib.sha256(original).hexdigest() != UPSTREAM_SHA256:
            raise ValueError('unsupported_native_plugin_baseline')
        expected = original.replace(b'name: "dsh-mcp-client",', b'name: "DeepSeek Harness",')
        if expected == original:
            raise ValueError('native_patch_anchor_missing')
        imports = {}
        for spec in re.findall(rb'from "([^"]+)"', original):
            spec = spec.decode()
            if spec.startswith('node:'):
                continue
            parts = spec.split('/')
            count = 2 if spec.startswith('@') else 1
            package = '/'.join(parts[:count])
            subpath = '.' if len(parts) == count else './' + '/'.join(parts[count:])
            info = json.loads(read('dsh/node_modules/' + package + '/package.json'))
            target = info['exports'][subpath]
            while isinstance(target, dict):
                target = target.get('import', target.get('default'))
            if not isinstance(target, str) or '..' in target.split('/'):
                raise ValueError('unsupported_native_peer_export')
            relative = 'dsh/node_modules/' + package + '/' + target.removeprefix('./')
            read(relative)  # Fail before writes if an original peer is missing.
            uri = (archive / relative).as_uri().replace('%40', '@')
            imports[spec] = uri
            expected = expected.replace(('from "' + spec + '"').encode(),
                                        ('from "' + uri + '"').encode())
    return {'content': expected.decode(), 'manifest': {
        'upstream_package': '@deepseek-ai/dsh-mcp-client', 'version': '0.2.2-rc.1',
        'upstream_entry_sha256': UPSTREAM_SHA256,
        'patched_entry_sha256': hashlib.sha256(expected).hexdigest(),
        'original_application_imports': imports, 'app_bundle_modified': False,
        'build_performed': False}}
