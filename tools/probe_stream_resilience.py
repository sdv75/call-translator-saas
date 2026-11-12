"""VPS-only diagnostic with injected fixed synthetic PCM, never user audio.

Prepend FIXTURES={direction: base64_pcm} before streaming this source over SSH.
Uses a temporary app/database, real providers, and bounded repeated audio bursts.
Prints only counts/status; never credentials, transcripts or provider bodies.
"""
import asyncio
import base64
import json
import tempfile
import statistics
from dataclasses import replace
from pathlib import Path

from aiohttp import ClientSession, WSMsgType, web
from server.app import IDENTITY, STORE, create_app
from server.config import Settings


async def main():
    fixtures = {key: base64.b64decode(value) for key, value in FIXTURES.items()}
    length = max(map(len, fixtures.values()))
    frames = (length+639)//640+100
    if frames > 400:
        raise ValueError('Fixture too long')
    fixtures = {key: value+bytes(frames*640-len(value)) for key, value in fixtures.items()}
    counts = {'incoming': 0, 'outgoing': 0}
    stopped = None
    timings=[]
    prefix_recognized={'incoming':False,'outgoing':False}
    prefix_translated={'incoming':False,'outgoing':False}
    with tempfile.TemporaryDirectory(prefix='ct-burst-probe-') as temp:
        settings = replace(Settings.from_env(), database=Path(temp)/'probe.sqlite3', experimental_audio=True,
                           public_url='http://localhost:5086')
        app = create_app(settings)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            account = app[STORE].register('internal-fixed-synthetic-burst-probe')
            token, _ = app[IDENTITY].redeem_pairing(app[IDENTITY].new_pairing(account))
            async with ClientSession() as client:
                async with client.ws_connect(f'http://127.0.0.1:{port}/ws') as socket:
                    await socket.send_json({'token': token, 'source': 'ru', 'target': 'uk'})
                    ready = await socket.receive_json(timeout=20)
                    if ready.get('type') != 'ready':
                        raise ValueError('Not ready')

                    async def read():
                        nonlocal stopped
                        async for message in socket:
                            if message.type == WSMsgType.TEXT:
                                event = json.loads(message.data)
                                if event.get('type') == 'translation':
                                    counts[event['direction']] += 1
                                    if event.get('timing'):timings.append(event['timing'])
                                    expected='последняя' if event['direction']=='incoming' else 'остання'
                                    prefix_translated[event['direction']] |= expected in event.get('text','').lower()
                                if event.get('type')=='recognized':
                                    expected='остання' if event['direction']=='incoming' else 'последняя'
                                    prefix_recognized[event['direction']] |= expected in event.get('original','').lower()
                                if event.get('type') == 'stopped':
                                    stopped = event.get('reason')
                                    return

                    reader = asyncio.create_task(read())
                    try:
                        for _ in range(3):
                            for first in range(0, frames, 25):
                                size = min(25, frames-first)
                                for index in range(first, first+size):
                                    for direction, code in (('outgoing', 0), ('incoming', 1)):
                                        await socket.send_bytes(bytes([code])+fixtures[direction][index*640:(index+1)*640])
                                await asyncio.sleep(size*.02)
                        await socket.send_json({'type': 'stop'})
                        await asyncio.wait_for(reader, timeout=12)
                    finally:
                        reader.cancel()
                        await asyncio.gather(reader, return_exceptions=True)
            report = {'status': 'ok' if stopped == 'user_stop' and min(counts.values()) >= 2 else 'failed',
                      'translations': counts, 'stop_reason': stopped, 'rounds': 3,
                      'burst_frames': 25, 'audio_ms_per_direction': frames*20*3,
                      'real_providers': True, 'synthetic_fixture_only': True,
                      'customer_database_touched': False, 'full_meet_verified': False}
            report['server_timings_ms']={key:{'median':round(statistics.median(values)),'max':max(values)}
                for key in ('translation_ms','translation_queue_ms','stt_backlog_ms')
                if (values:=[sample[key] for sample in timings if key in sample])}
            report['test_prefix_recognized']=prefix_recognized
            report['test_prefix_translated']=prefix_translated
            print(json.dumps(report))
            return 0 if report['status'] == 'ok' else 1
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__, 'details_suppressed': True}))
        raise SystemExit(1)
