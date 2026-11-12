"""Install and synthesize the signed technical voice in this workspace only."""

import base64
import argparse
import io
import json
import time
import wave
from pathlib import Path

from local_component.call_translator_local.application import Application
from local_component.call_translator_local.engine import Engine
from local_component.call_translator_local.voices import VoiceStore


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--voice-id',default='uk-basic')
    parser.add_argument('--catalog',default='catalog/voices.signed.json')
    args=parser.parse_args()
    trust = json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    envelope = Path(args.catalog).read_bytes()
    store = VoiceStore(Path('build/local-voices'), trust)
    engine = Engine()
    started = time.monotonic()
    voice = store.install(envelope, args.voice_id, engine.smoke)
    app = Application(store, engine)
    messages = list(app.handle({'id': 1, 'type': 'preview-voice', 'voice_id': voice['id']}))
    if not messages or messages[-1].get('type') != 'audio-end':
        raise ValueError('Native audio generation failed')
    chunks = messages[:-1]
    if any(message.get('index') != index for index, message in enumerate(chunks)):
        raise ValueError('Native audio chunks out of order')
    audio = base64.b64decode(''.join(item['data'] for item in chunks), validate=True)
    if len(audio) != messages[-1]['bytes']:
        raise ValueError('Native audio byte count mismatch')
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        report = {'voice_id': voice['id'], 'language': voice['language'], 'release_status': voice['release_status'],
                  'sample_rate': wav.getframerate(), 'audio_seconds': wav.getnframes()/wav.getframerate(),
                  'wav_bytes': len(audio), 'native_audio_chunks': len(chunks),
                  'elapsed_seconds': round(time.monotonic()-started, 3), 'listening_test_performed': False,
                  'clean_windows_verified': False, 'full_call_verified': False}
    suffix='' if args.voice_id=='uk-basic' else '-'+args.voice_id
    Path('build/local-voice-preview'+suffix+'.wav').write_bytes(audio)
    Path('build/local-voice-smoke'+suffix+'.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    engine.close()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Local voice smoke failed; inspect installation and dependencies without logging request text')
