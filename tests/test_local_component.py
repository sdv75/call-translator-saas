import hashlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from local_component.call_translator_local.__main__ import read_message, serve, write_message
from tools.prepare_local import prepare


class NativeTests(unittest.TestCase):
    def test_multiple_framed_requests(self):
        requests = io.BytesIO()
        write_message(requests, {'id': 1, 'type': 'status'})
        write_message(requests, {'id': 2, 'type': 'unknown-request'})
        requests.seek(0)
        response = io.BytesIO()
        from local_component.call_translator_local.application import Application
        from local_component.call_translator_local.voices import VoiceStore
        with tempfile.TemporaryDirectory() as temp:
            app = Application(VoiceStore(Path(temp), {'keys': {}, 'asset_origins': []}))
            self.assertEqual(serve(requests, response, app), 0)
        response.seek(0)
        self.assertFalse(read_message(response)['ready'])
        self.assertEqual(read_message(response)['error'], 'unsupported_request')
        self.assertIsNone(read_message(response))

    def test_invalid_frames_fail_closed(self):
        for frame in (b'\x01', struct.pack('<I', 2)+b'{', struct.pack('<I', 2000000),
                      struct.pack('<I', 2)+b'[]'):
            with self.subTest(frame=frame):
                response = io.BytesIO()
                self.assertEqual(serve(io.BytesIO(frame), response), 1)
                response.seek(0)
                self.assertEqual(read_message(response)['error'], 'invalid_native_message')

    def test_runtime_preparation_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)/'runtime.zip'
            with zipfile.ZipFile(runtime, 'w') as archive:
                for name in ('python.exe', 'python311.dll', 'python311.zip', 'python311._pth', 'LICENSE.txt'):
                    archive.writestr(name, b'test fixture, not executable')
            checksum = hashlib.sha256(runtime.read_bytes()).hexdigest()
            manifest = prepare(runtime, checksum, Path(temp)/'prepared')
            self.assertEqual(manifest['environment']['PYAPP_SKIP_INSTALL'], '1')
            self.assertFalse(manifest['clean_windows_verified'])
            with zipfile.ZipFile(Path(temp)/'prepared'/'runtime.zip') as archive:
                self.assertIn('Lib/site-packages/call_translator_local/__main__.py', archive.namelist())
                self.assertIn(b'Lib/site-packages', archive.read('python311._pth'))
                self.assertIn('LICENSE.txt', archive.namelist())
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                prepare(runtime, '0'*64, Path(temp)/'rejected')
