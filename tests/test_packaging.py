import json
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.extension_id import extension_id
from tools.stage_installer import ROOT, stage


class PackagingTests(unittest.TestCase):
    def test_installer_rejects_unbuilt_binary_and_wildcard_origin(self):
        manifest = json.loads((ROOT/'extension/manifest.json').read_text(encoding='utf-8'))
        identity = extension_id(manifest)
        self.assertEqual(len(identity), 32)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'build-manifest.json').write_text('{"build_verified": false}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Exact Chrome extension ID'):
                stage(root, '*', root/'license.txt', root/'staged')
            with self.assertRaisesRegex(ValueError, 'successfully built'):
                stage(root, identity, root/'license.txt', root/'staged')
            self.assertFalse((root/'staged').exists())

    def test_stage_requires_matching_native_smoke_and_keeps_source_allowlist(self):
        identity = extension_id(json.loads((ROOT/'extension/manifest.json').read_text(encoding='utf-8')))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = b'MZ-test-fixture'
            checksum = hashlib.sha256(executable).hexdigest()
            (root/'CallTranslatorLocal.exe').write_bytes(executable)
            with zipfile.ZipFile(root/'runtime.zip', 'w') as runtime:
                runtime.writestr('LICENSE.txt', 'Python license fixture')
                runtime.writestr('Lib/site-packages/example.dist-info/licenses/LICENSE', 'Dependency notice fixture')
            manifest = {'build_verified': True, 'pyapp_executable_sha256': checksum,
                        'prepared_runtime_sha256': hashlib.sha256((root/'runtime.zip').read_bytes()).hexdigest()}
            (root/'build-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (root/'LICENSE.txt').write_text('PyApp license fixture', encoding='utf-8')
            smoke = {'pyapp_executable_verified': True, 'first_boot_native_framing': True, 'executable_sha256': 'outdated'}
            (root/'pyapp-smoke.json').write_text(json.dumps(smoke), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Matching first-boot'):
                stage(root, identity, root/'LICENSE.txt', root/'staged')
            self.assertFalse((root/'staged').exists())
            smoke['executable_sha256'] = checksum
            (root/'pyapp-smoke.json').write_text(json.dumps(smoke), encoding='utf-8')
            stage(root, identity, root/'LICENSE.txt', root/'staged')
            output = root/'staged'
            self.assertTrue((output/'extension/offscreen.js').is_file())
            self.assertTrue((output/'extension/licenses/legacy-MIT.txt').is_file())
            self.assertEqual((output/'licenses/python/example.dist-info/licenses/LICENSE').read_text(), 'Dependency notice fixture')
            self.assertFalse(any(path.name.startswith('test-') or path.name == '.env' for path in output.rglob('*')))
            host = json.loads((output/'native-host.json').read_text(encoding='utf-8'))
            self.assertEqual(host['allowed_origins'], [f'chrome-extension://{identity}/'])
