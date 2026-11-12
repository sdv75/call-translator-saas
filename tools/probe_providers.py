"""Bounded live provider probe. Never print credentials, bodies or transcripts.

Sends 1 second of silence to each of two STT streams and translates one fixed,
non-personal sentence. Uses a temporary database, never real customer balances.
"""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, WSMsgType

from server.accounting import Accounting
from server.config import Settings
from server.economics import Usage
from server.providers import Providers
from server.speech import FRAME_BYTES


def failure(exc):
    # Exception strings can include request/provider details. Only known safe
    # fields are allowed in the report; no str(exc), response bodies or headers.
    data = {'status': 'failed', 'error_type': type(exc).__name__}
    status = getattr(exc, 'status', None)
    if type(status) is int and 100 <= status <= 599:
        data['http_status'] = status
    return data


async def stt_probe(providers, call, direction, language):
    stream = None
    try:
        stream = await providers.open_stt(call, direction, language)
        for _ in range(50):
            await stream.send(bytes(FRAME_BYTES))
        await stream.websocket.send_json({'type': 'CloseStream'})
        duration = None
        async with asyncio.timeout(12):
            async for message in stream.websocket:
                if message.type == WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if data.get('type') == 'Error':
                        return {'status': 'failed', 'error_type': 'provider_error_event'}
                    if data.get('type') == 'Metadata' and isinstance(data.get('duration'), (int, float)):
                        duration = data['duration']
                elif message.type == WSMsgType.ERROR:
                    return {'status': 'failed', 'error_type': 'websocket_error'}
        return {'status': 'ok' if duration is not None else 'accepted_without_final_metadata',
                'sent_audio_ms': 1000, 'provider_duration_seconds': duration}
    except Exception as exc:
        return failure(exc)
    finally:
        if stream is not None:
            await stream.close()


async def probe(settings):
    results = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
               'live_provider_requests': bool(settings.deepgram_key or settings.groq_key), 'live_google_login': False,
               'full_call_verified': False, 'economics_validated': False}
    with tempfile.TemporaryDirectory(prefix='ct-provider-probe-') as temp:
        store = Accounting(Path(temp)/'probe.sqlite3')
        try:
            call = store.start(store.register('internal-technical-probe-not-a-google-account'))
            usage = Usage(store)
            async with ClientSession(timeout=ClientTimeout(total=20)) as session:
                providers = Providers(settings, session, usage)
                if settings.deepgram_key:
                    # Sequential, bounded diagnostics; no automatic reruns.
                    results['stt_outgoing_ru'] = await stt_probe(providers, call, 'outgoing', 'ru')
                    results['stt_incoming_en'] = await stt_probe(providers, call, 'incoming', 'en')
                else:
                    results['deepgram'] = {'status': 'not_configured'}
                if settings.groq_key:
                    try:
                        text = await providers.translate(call, 'Hello. This is a technical test.', 'en', 'ru')
                        results['translation_en_ru'] = {'status': 'ok', 'nonempty_result': bool(text.strip())}
                    except Exception as exc:
                        results['translation_en_ru'] = failure(exc)
                else:
                    results['groq'] = {'status': 'not_configured'}
            results['usage'] = dict(zip(('input_tokens', 'output_tokens', 'reasoning_tokens', 'retry_attempts'),
                store.db.execute('SELECT coalesce(sum(input_tokens),0),coalesce(sum(output_tokens),0),coalesce(sum(reasoning_tokens),0),coalesce(sum(retry),0) FROM translation_usage').fetchone()))
            results['usage']['sent_stt_audio_ms'] = store.db.execute('SELECT coalesce(sum(audio_ms),0) FROM stt_usage').fetchone()[0]
            store.stop(call)
            results['customer_billing_ms'] = store.db.execute('SELECT speech_ms FROM calls WHERE id=?', (call,)).fetchone()[0]
        finally:
            store.close()
    return results


def main():
    try:
        results = asyncio.run(probe(Settings.from_env()))
    except Exception as exc:
        print(json.dumps(failure(exc)))
        return 1
    output = Path('build/provider-probe.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(results, indent=2))
    failures = any(isinstance(value, dict) and value.get('status') not in ('ok',) for value in results.values() if isinstance(value, dict) and 'status' in value)
    return int(failures)


if __name__ == '__main__':
    raise SystemExit(main())
