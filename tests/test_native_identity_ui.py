import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativeIdentityUiTests(unittest.TestCase):
    def test_panel_has_separate_native_actions_and_never_runs_a_bridge(self):
        src = (ROOT / 'gui/dashboard.html').read_text()
        self.assertIn('id="native-identity-panel"', src)
        self.assertIn('function nativeIdentityMarkup(', src)
        for flag in ['--native-plan', '--native-apply', '--native-start', '--native-capture', '--native-verify']:
            self.assertIn(flag, src)

    @unittest.skipUnless(shutil.which('node'), 'node required')
    def test_real_renderer_escapes_names_and_does_not_promote_config_to_auth(self):
        src = (ROOT / 'gui/dashboard.html').read_text()
        start = src.index('function nativeIdentityMarkup(')
        end = src.index('\n}\n', start) + 3
        fn = src[start:end]
        esc = re.search(r'const escapeHtml = \(v\) =>.*?&#39;"\);', src, re.S).group(0)
        state = {'hosts': [{'adapter_id': 'workbuddy', 'name': '<script>bad</script>',
            'installed': True, 'config_state': 'configured', 'authentication': 'unchecked',
            'conversation': 'unchecked', 'trust': 'unknown'}]}
        js = esc + '\n' + fn + '\nprocess.stdout.write(nativeIdentityMarkup(' + json.dumps(state) + ', []));'
        p = subprocess.run(['node', '-e', js], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('<script>bad</script>', p.stdout)
        self.assertIn('&lt;script&gt;', p.stdout)
        self.assertIn('unchecked', p.stdout)
        self.assertNotIn('验收通过', p.stdout)


if __name__ == '__main__':
    unittest.main()
