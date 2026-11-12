"""Native commands; trust/path/URLs cannot be supplied by extension messages."""

import base64
import json
import time
from pathlib import Path

from . import __version__
from .catalog import ComponentUpdateRequired, canonical, semver, verify
from .engine import Engine
from .voices import VoiceStore, default_root
from .locking import VoiceBusy
from .language_data import CALL_LANGUAGES,voice_test_text
from .transcripts import TranscriptFolders,choose_folder

TRUST_FILE = Path(__file__).with_name('catalog-trust.json')


class Application:
    def __init__(self, store=None, engine=None):
        if store is None and TRUST_FILE.is_file():
            store = VoiceStore(default_root(), json.loads(TRUST_FILE.read_text(encoding='utf-8')))
        self.store = store
        self.engine = engine or Engine()
        self.busy = False
        self.lease = None
        self.call_voices = {}
        self.transcripts = TranscriptFolders(self.store.root.parent/'transcript-folder.json') if self.store else None

    def close(self):
        self.busy = False
        self.call_voices.clear()
        if self.lease:
            self.lease.close()
            self.lease = None
        self.engine.close()

    def handle(self, request):
        request_id = request.get('id')
        if (type(request_id) is not int and not (isinstance(request_id, str) and len(request_id) <= 64)):
            yield {'error': 'invalid_request_id'}
            return
        try:
            command = request.get('type')
            if command == 'status':
                installed = self.store.installed() if self.store else []
                ready = bool(installed) and self.engine.available()
                yield {'id': request_id, 'version': __version__, 'protocol': 1,
                    'ready': ready, 'reason': None if ready else ('local_dependencies_missing' if installed else 'voice_setup_required'),
                    'busy': self.busy, 'capabilities':['remove-voice','language-variants','transcript-folders'], 'voices': [{key: voice[key] for key in
                        ('id', 'language', 'display_name', 'gender', 'version', 'license', 'release_status')} for voice in installed],
                    'selected': self.store.state()['selection'] if self.store else {}}
                return
            if command in ('transcript-folder-status','transcript-folder-choose','transcript-folder-default','transcript-folder-open','transcript-write'):
                if self.transcripts is None:raise ValueError('Local settings unavailable')
                if self.busy and command in ('transcript-folder-choose','transcript-folder-default'):
                    raise VoiceBusy()
                if command=='transcript-folder-choose':
                    folder=choose_folder(self.transcripts.current(request.get('downloaded')))
                    if folder is not None:self.transcripts.configure(folder)
                elif command=='transcript-folder-default':self.transcripts.configure(None)
                elif command=='transcript-folder-open':self.transcripts.open(request.get('downloaded'))
                elif command=='transcript-write':self.transcripts.write(request['day'],request['filename'],request['html'])
                yield {'id':request_id,'type':command,**self.transcripts.status()}
                return
            if command not in ('catalog-info', 'install-voice', 'remove-voice', 'select-voice', 'begin-call', 'end-call', 'synthesize', 'preview-voice'):
                yield {'id': request_id, 'error': 'unsupported_request'}
                return
            if self.store is None:
                yield {'id': request_id, 'error': 'voice_setup_required'}
                return
            if command in ('install-voice', 'remove-voice', 'select-voice') and self.busy:
                yield {'id': request_id, 'error': 'call_active'}
                return
            if command == 'catalog-info':
                catalog = verify(canonical(request['catalog']), self.store.trust,
                                 minimum_revision=self.store.state()['revision'])
                yield {'id': request_id, 'type': 'catalog-info', 'revision': catalog['revision'],
                    'voices': [{**{key: voice[key] for key in ('id', 'version', 'language', 'display_name', 'gender', 'license', 'release_status')},
                                'compatible': semver(voice['min_component']) <= semver(__version__),
                                'download_bytes': sum(asset['size'] for asset in voice['files'])} for voice in catalog['voices']]}
            elif command == 'install-voice':
                voice = self.store.install(canonical(request['catalog']), request['voice_id'], self.engine.smoke)
                self.engine.close()
                yield {'id': request_id, 'type': 'voice-installed', 'voice_id': voice['id']}
            elif command == 'select-voice':
                self.store.select(request['direction'], request['voice_id'])
                yield {'id': request_id, 'type': 'voice-selected'}
            elif command == 'remove-voice':
                self.engine.close()
                self.store.remove(request['voice_id'])
                yield {'id':request_id,'type':'voice-removed'}
            elif command == 'begin-call':
                if self.busy:
                    raise VoiceBusy()
                source, target = request.get('source'), request.get('target')
                if source not in CALL_LANGUAGES or target not in CALL_LANGUAGES or source == target:
                    raise ValueError('Invalid language pair')
                lease = self.store.call_lease()
                prepared = {}
                try:
                    for direction, language in (('incoming', source), ('outgoing', target)):
                        selected = self.store.selected(direction)
                        if selected is None or selected[0]['language'] != language:
                            raise ValueError('Both direction voices must be selected')
                        # Load AND run inference before reporting call-ready.
                        # Setup/model warmup is never part of a billed call.
                        self.engine.smoke(*selected)
                        prepared[direction] = selected
                except BaseException:
                    lease.close()
                    self.engine.close()
                    raise
                self.lease = lease
                self.call_voices = prepared
                self.busy = True
                yield {'id': request_id, 'type': 'call-ready'}
            elif command == 'end-call':
                self.close()
                yield {'id': request_id, 'type': 'call-ended'}
            elif command in ('synthesize', 'preview-voice'):
                if command == 'synthesize':
                    direction = request['direction']
                    if not self.busy or direction not in ('incoming', 'outgoing'):
                        raise ValueError('Call is not ready')
                    selected = self.call_voices.get(direction)
                    text = request['text']
                else:
                    if self.busy:
                        raise ValueError('Call active')
                    selected = self.store.resolve(request['voice_id'])
                    text = voice_test_text(selected[0]['language'])
                if selected is None:
                    raise ValueError('Voice not selected')
                voice, folder = selected
                # Incoming playback is in the user's language; outgoing playback
                # is in the other participants' language, selected independently.
                began = time.monotonic()
                data = self.engine.render(voice, folder, text)
                synthesis_ms = round((time.monotonic()-began)*1000)
                chunk_size = 192*1024
                count = 0
                for offset in range(0, len(data), chunk_size):
                    yield {'id': request_id, 'type': 'audio-chunk', 'index': count,
                           'data': base64.b64encode(data[offset:offset+chunk_size]).decode('ascii')}
                    count += 1
                yield {'id': request_id, 'type': 'audio-end', 'chunks': count, 'bytes': len(data),
                       'synthesis_ms': synthesis_ms}
                if command == 'preview-voice':
                    self.engine.close()
        except ComponentUpdateRequired:
            yield {'id': request_id, 'error': 'component_update_required'}
        except VoiceBusy:
            yield {'id': request_id, 'error': 'local_busy'}
        except Exception:
            # No exception strings: download URLs, local paths and speech text
            # must not appear on stdout or in a product error message.
            yield {'id': request_id, 'error': 'local_operation_failed'}
