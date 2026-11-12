"""Live technical audio -> VAD -> STT -> translation probe, no Google bypass API.

Only a fixed locally synthesized test phrase is sent. Temporary internal test
credentials/database are never exposed as a login option or a real account.
"""

import asyncio
import io
import json
import tempfile
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
from aiohttp import ClientSession, WSMsgType, web

from local_component.call_translator_local.engine import Engine
from local_component.call_translator_local.voices import VoiceStore
from server.app import IDENTITY, STORE, create_app
from server.config import Settings


async def main():
    trust = json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    voices = VoiceStore(Path('build/local-voices'), trust)
    voice, folder = voices.resolve('uk-basic')
    engine = Engine()
    try:
        audio = engine.render(voice, folder, 'Привіт! Це перевірка голосу.')
    finally:
        engine.close()
    with wave.open(io.BytesIO(audio), 'rb') as source:
        rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2')
    positions = np.arange(int(len(samples)*16000/rate))*rate/16000
    converted = np.interp(positions, np.arange(len(samples)), samples).astype('<i2').tobytes()
    converted += bytes((-len(converted)) % 640) + bytes(640*25)
    if len(converted) > 640*500:
        raise ValueError('Technical fixture exceeds 10-second bound')
    report = {'live_provider_requests': True, 'fixed_synthetic_phrase_only': True,
              'live_google_login': False, 'real_user_balance_touched': False,
              'full_meet_call_verified': False, 'listening_test_performed': False}
    with tempfile.TemporaryDirectory(prefix='ct-audio-probe-') as temp:
        settings = replace(Settings.from_env(), database=Path(temp)/'probe.sqlite3', experimental_audio=True,
                           public_url='http://localhost:5086')
        app = create_app(settings)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            account = app[STORE].register('internal-audio-probe-not-google-user')
            code = app[IDENTITY].new_pairing(account)
            token, _ = app[IDENTITY].redeem_pairing(code)
            received = []
            translated = asyncio.Event()
            async with ClientSession() as session:
                async with session.ws_connect(f'http://127.0.0.1:{port}/ws') as socket:
                    await socket.send_json({'token': token, 'source': 'en', 'target': 'uk'})
                    ready = await socket.receive_json(timeout=20)
                    if ready.get('type') != 'ready':
                        raise ValueError('Technical stream not ready')

                    async def read_results():
                        async for message in socket:
                            if message.type == WSMsgType.TEXT:
                                event = json.loads(message.data)
                                received.append(event)
                                if event.get('type') in ('translation', 'stopped'):
                                    translated.set()

                    reader = asyncio.create_task(read_results())
                    try:
                        for offset in range(0, len(converted), 640):
                            if socket.closed:
                                break
                            await socket.send_bytes(b'\x00'+bytes(640))
                            await socket.send_bytes(b'\x01'+converted[offset:offset+640])
                            await asyncio.sleep(0.02)
                        await asyncio.wait_for(translated.wait(), timeout=12)
                        if not socket.closed:
                            await socket.send_json({'type': 'stop'})
                        await asyncio.wait_for(reader, timeout=10)
                    finally:
                        if not reader.done():
                            reader.cancel()
                            await asyncio.gather(reader, return_exceptions=True)
            translations = [item for item in received if item.get('type') == 'translation']
            report['translation_received'] = any(item.get('text', '').strip() for item in translations)
            report['translation_direction'] = translations[0]['direction'] if translations else None
            report['translation_language'] = translations[0]['language'] if translations else None
            report['synthetic_fixture_audio_ms'] = len(converted)//640*20
            report['detected_speech_ms'] = app[STORE].db.execute('SELECT speech_ms FROM calls WHERE id=?', (ready['call_id'],)).fetchone()[0]
            report['unused_reserve_released'] = app[STORE].balance(account) == 300000-report['detected_speech_ms']
            report['sent_stt_audio_ms'] = app[STORE].db.execute('SELECT coalesce(sum(audio_ms),0) FROM stt_usage').fetchone()[0]
            report['translation_usage'] = dict(zip(('input_tokens', 'output_tokens', 'reasoning_tokens'), app[STORE].db.execute(
                'SELECT coalesce(sum(input_tokens),0),coalesce(sum(output_tokens),0),coalesce(sum(reasoning_tokens),0) FROM translation_usage').fetchone()))
            report['status'] = 'ok' if report['translation_received'] and report['detected_speech_ms'] > 0 and report['unused_reserve_released'] else 'failed'
        finally:
            await runner.cleanup()
    Path('build/audio-pipeline-probe.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'ok' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        raise SystemExit('Technical audio pipeline probe failed; no provider bodies, tokens or transcripts printed')
