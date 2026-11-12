import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from tools.stage_deployment import ROOT, stage


class DeploymentArchiveTests(unittest.TestCase):
    def test_release_contains_only_source_public_trust_and_verified_installer(self):
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build', prefix='archive-test-') as temp:
            folder = Path(temp)
            (folder/'installer-output').mkdir()
            binary = b'MZ-installer-fixture'
            (folder/'installer-output/CallTranslatorSetup.exe').write_bytes(binary)
            (folder/'installer-manifest.json').write_text(json.dumps({'installer_compiled': True,
                'installer_sha256': hashlib.sha256(binary).hexdigest()}), encoding='utf-8-sig')
            output = folder/'release.tar.gz'
            stage(folder, output)
            with tarfile.open(output) as archive:
                names = archive.getnames()
                checksums = json.load(archive.extractfile('release-manifest.json'))['files']
                for member in archive.getmembers():
                    self.assertTrue(member.isfile())
                    path = PurePosixPath(member.name)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn('..', path.parts)
                    self.assertNotIn(path.name, ('.env', 'connection.json'))
                    self.assertNotIn(path.suffix, ('.pem', '.key', '.onnx', '.sqlite3', '.pyc'))
                    if member.name != 'release-manifest.json':
                        self.assertEqual(hashlib.sha256(archive.extractfile(member).read()).hexdigest(), checksums[member.name])
                self.assertIn('server/downloads.py', names)
                self.assertIn('downloads/CallTranslatorSetup.exe', names)
                self.assertIn('local_component/call_translator_local/catalog-trust.json', names)
                self.assertFalse(any('local-voices' in name or 'reference/' in name for name in names))
            (folder/'installer-output/CallTranslatorSetup.exe').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'Verified compiled installer'):
                stage(folder, folder/'corrupt.tar.gz')
            self.assertFalse((folder/'corrupt.tar.gz').exists())
