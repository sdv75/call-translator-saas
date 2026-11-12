import base64
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from local_component.call_translator_local.application import Application
from local_component.call_translator_local.catalog import canonical, signed, verify
from local_component.call_translator_local.download import SafeRedirects, download
from local_component.call_translator_local.voices import VoiceStore
from local_component.call_translator_local.locking import VoiceBusy


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = Ed25519PrivateKey.generate()
        self.trust = {'keys': {'test': base64.b64encode(self.key.public_key().public_bytes_raw()).decode()},
                      'asset_origins': ['https://assets.example']}
        self.contents = {'model.onnx': b'fake-model', 'config.json': b'{}', 'LICENSE.txt': b'License fixture'}
        self.voice = {'id': 'english', 'version': '1.0.0', 'language': 'en', 'display_name': 'English',
                      'gender': 'unspecified', 'min_component': '0.1.0', 'format': 'onnx-v1',
                      'license': 'CC0-1.0', 'release_status': 'technical_preview', 'files': [
            {'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'url': 'https://assets.example/'+name}
            for name, data in self.contents.items()]}
        self.store = VoiceStore(Path(self.temp.name), self.trust)

    def tearDown(self):
        self.temp.cleanup()

    def envelope(self, voice=None, revision=1):
        return signed({'schema': 1, 'revision': revision, 'voices': [voice or self.voice]}, 'test', self.key)

    def fetch(self, asset, path):
        path.write_bytes(self.contents[asset['name']])

    def install(self, **kwargs):
        return self.store.install(self.envelope(**kwargs), self.voice['id'], lambda *_: None, fetch=self.fetch)

    def test_signature_and_unknown_keys_reject_before_download(self):
        envelope = json.loads(self.envelope())
        envelope['payload'] = base64.b64encode(canonical({'schema': 1, 'revision': 2, 'voices': []})).decode()
        with self.assertRaises(InvalidSignature):
            verify(canonical(envelope), self.trust)
        envelope['key_id'] = 'unknown'
        with self.assertRaises(ValueError):
            verify(canonical(envelope), self.trust)

    def test_atomic_activation_selection_and_corruption_disables_voice(self):
        self.install()
        self.store.select('incoming', 'english')
        reopened = VoiceStore(Path(self.temp.name), self.trust)
        self.assertEqual(reopened.selected('incoming')[0]['language'], 'en')
        self.assertEqual(len(reopened.installed()), 1)
        voice, folder = reopened.resolve('english')
        (folder/'model.onnx').write_bytes(b'corrupt')
        self.assertEqual(reopened.installed(), [])
        with self.assertRaises(ValueError):
            reopened.selected('incoming')

    def test_remove_clears_both_selections_and_can_reinstall(self):
        self.install()
        self.store.select('incoming','english');self.store.select('outgoing','english')
        _,folder=self.store.resolve('english')
        # Corrupt model data must still be removable via signed ownership metadata.
        (folder/'model.onnx').write_bytes(b'bad')
        self.store.remove('english')
        self.assertFalse(folder.exists())
        self.assertEqual(self.store.state()['selection'],{})
        self.assertEqual(self.store.installed(),[])
        self.install()
        self.assertEqual(len(self.store.installed()),1)

    def test_remove_rejects_active_call_and_foreign_files(self):
        self.install()
        lease=self.store.call_lease()
        try:
            with self.assertRaises(VoiceBusy):self.store.remove('english')
        finally:lease.close()
        _,folder=self.store.resolve('english')
        (folder/'personal.txt').write_text('keep')
        with self.assertRaises(ValueError):self.store.remove('english')
        self.assertTrue((folder/'personal.txt').exists())
        self.assertEqual(len(self.store.installed()),1)

    def test_remove_rejects_path_escape_without_touching_other_files(self):
        self.install()
        outside=Path(self.temp.name).parent/'do-not-delete-credit-test.txt'
        # No file outside the temporary voice store is created or modified.
        state=self.store.state();state['active']['english']='../'+outside.name;self.store.write_state(state)
        with self.assertRaises(ValueError):self.store.remove('english')
        self.assertEqual(self.store.state()['active']['english'],'../'+outside.name)

    def test_failed_smoke_preserves_active_version(self):
        self.install()
        state = self.store.state()
        newer = copy.deepcopy(self.voice)
        newer['version'] = '2.0.0'
        def broken(*_):
            raise ValueError('synthesis failed')
        with self.assertRaises(ValueError):
            self.store.install(self.envelope(newer, 2), 'english', broken, fetch=self.fetch)
        self.assertEqual(self.store.state(), state)
        self.assertEqual(self.store.resolve('english')[0]['version'], '1.0.0')

    def test_bad_download_cannot_activate(self):
        def wrong(asset, path):
            path.write_bytes(b'wrong')
        with self.assertRaises(ValueError):
            self.store.install(self.envelope(), 'english', lambda *_: None, fetch=wrong)
        self.assertEqual(self.store.installed(), [])

    def test_path_origin_format_and_compatibility_checks(self):
        for mutate in (lambda v: v.update(id='../escape'), lambda v: v['files'][0].update(name='../model.onnx'),
                       lambda v: v['files'][0].update(url='https://attacker.example/model'),
                       lambda v: v.update(format='executable'), lambda v: v.update(min_component='99.0.0')):
            voice = copy.deepcopy(self.voice)
            mutate(voice)
            with self.assertRaises(ValueError):
                self.store.install(self.envelope(voice), voice['id'], lambda *_: None, fetch=self.fetch)
        self.assertEqual(self.store.installed(), [])

    def test_catalog_rollback_and_same_revision_conflicts(self):
        self.install(revision=2)
        with self.assertRaises(ValueError):
            self.install(revision=1)
        changed = copy.deepcopy(self.voice)
        changed['display_name'] = 'Replaced metadata'
        with self.assertRaises(ValueError):
            self.install(voice=changed, revision=2)

    def test_updates_blocked_during_call_and_errors_are_generic(self):
        self.install()
        class Engine:
            def close(self):
                pass
        app = Application(self.store, Engine())
        app.busy = True
        result = list(app.handle({'id': 1, 'type': 'install-voice', 'catalog': json.loads(self.envelope()), 'voice_id': 'english'}))
        self.assertEqual(result[0]['error'], 'call_active')
        self.assertNotIn('private-text', str(list(app.handle({'id': 2, 'type': 'synthesize', 'text': 'private-text', 'direction': 'missing'}))))

    def test_two_language_selection_and_native_audio_chunks(self):
        import wave
        ukrainian = copy.deepcopy(self.voice)
        ukrainian.update(id='ukrainian', language='uk')
        envelope = signed({'schema': 1, 'revision': 1, 'voices': [self.voice, ukrainian]}, 'test', self.key)
        for voice_id in ('english', 'ukrainian'):
            self.store.install(envelope, voice_id, lambda *_: None, fetch=self.fetch)
        self.store.select('incoming', 'english')
        self.store.select('outgoing', 'ukrainian')
        class FakeEngine:
            def smoke(self, voice, folder):
                pass
            def render(self, voice, folder, text):
                result = io.BytesIO()
                with wave.open(result, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(bytes(300000))
                return result.getvalue()
            def close(self):
                pass
        app = Application(self.store, FakeEngine())
        self.assertEqual(list(app.handle({'id': 1, 'type': 'begin-call', 'source': 'uk', 'target': 'en'}))[0]['error'], 'local_operation_failed')
        self.assertEqual(list(app.handle({'id': 2, 'type': 'begin-call', 'source': 'en', 'target': 'uk'}))[0]['type'], 'call-ready')
        second = Application(VoiceStore(Path(self.temp.name), self.trust), FakeEngine())
        response = list(second.handle({'id': 20, 'type': 'select-voice', 'direction': 'incoming', 'voice_id': 'english'}))
        self.assertEqual(response[0]['error'], 'local_busy')
        messages = list(app.handle({'id': 3, 'type': 'synthesize', 'direction': 'incoming', 'text': 'private-text'}))
        from unittest.mock import patch
        with patch.object(app.store,'selected',side_effect=AssertionError('Must use warmed voice during call')):
            repeated=list(app.handle({'id':30,'type':'synthesize','direction':'incoming','text':'synthetic repeat'}))
        self.assertEqual(repeated[-1]['type'],'audio-end')
        self.assertEqual(messages[-1]['type'], 'audio-end')
        self.assertEqual(messages[-1]['chunks'], 2)
        self.assertNotIn('private-text', str(messages))
        self.assertEqual(len(base64.b64decode(''.join(item['data'] for item in messages[:-1]))), messages[-1]['bytes'])
        list(app.handle({'id': 4, 'type': 'end-call'}))
        self.assertEqual(app.call_voices,{})
        self.assertFalse(app.busy)
        from local_component.call_translator_local.__main__ import serve, write_message
        stdin = io.BytesIO()
        write_message(stdin, {'id': 5, 'type': 'begin-call', 'source': 'en', 'target': 'uk'})
        stdin.seek(0)
        self.assertEqual(serve(stdin, io.BytesIO(), app), 0)
        self.assertFalse(app.busy)
        # EOF releases the OS call lease, so a different host may change voices.
        second.store.select('incoming', 'english')


    def test_failed_voice_warmup_releases_lease_and_never_reports_ready(self):
        ukrainian = copy.deepcopy(self.voice)
        ukrainian.update(id='ukrainian', language='uk')
        envelope = signed({'schema': 1, 'revision': 1, 'voices': [self.voice, ukrainian]}, 'test', self.key)
        for voice_id in ('english', 'ukrainian'):
            self.store.install(envelope, voice_id, lambda *_: None, fetch=self.fetch)
        self.store.select('incoming', 'english')
        self.store.select('outgoing', 'ukrainian')

        class FailingEngine:
            def __init__(self):
                self.warmed = []
                self.closed = False

            def smoke(self, voice, folder):
                self.warmed.append(voice['language'])
                if voice['language'] == 'uk':
                    raise RuntimeError('private inference details')

            def close(self):
                self.closed = True

        engine = FailingEngine()
        app = Application(self.store, engine)
        response = list(app.handle({'id': 1, 'type': 'begin-call', 'source': 'en', 'target': 'uk'}))
        self.assertEqual(response, [{'id': 1, 'error': 'local_operation_failed'}])
        self.assertEqual(engine.warmed, ['en', 'uk'])
        self.assertTrue(engine.closed)
        self.assertFalse(app.busy)
        self.assertIsNone(app.lease)
        # A failed preparation must not lock out another native host.
        VoiceStore(Path(self.temp.name), self.trust).select('incoming', 'english')


class DownloadTests(unittest.TestCase):
    def test_interrupted_download_resumes(self):
        data = b'0123456789'
        asset = {'url': 'https://assets.example/model', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        requests = []

        class Response(io.BytesIO):
            status = 206
            headers = {'Content-Range': 'bytes 3-9/10'}

        def opener(request, timeout):
            requests.append(request.get_header('Range'))
            return Response(data[3:])

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'model.onnx'
            path.with_name('model.onnx.part').write_bytes(data[:3])
            download(asset, path, opener=opener)
            self.assertEqual(requests, ['bytes=3-'])
            self.assertEqual(path.read_bytes(), data)
            self.assertFalse(path.with_name('model.onnx.part').exists())

    def test_bad_hash_and_oversize_rejected(self):
        class Response(io.BytesIO):
            status = 200
            headers = {}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'model'
            for body in (b'bad', b'toolong'):
                asset = {'url': 'https://assets.example/model', 'size': 3, 'sha256': hashlib.sha256(b'yes').hexdigest()}
                with self.assertRaises(ValueError):
                    download(asset, path, opener=lambda *a, **k: Response(body))
                self.assertFalse(path.exists())
