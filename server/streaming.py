"""Experimental device-authenticated duplex PCM WebSocket lifecycle."""

import asyncio
import json
import logging
import time

from aiohttp import WSMsgType, web

from .accounting import CallRejected
from .providers import LANGUAGES
from .speech import FRAME_BYTES, FRAME_MS, SpeechMeter

logger = logging.getLogger(__name__)


class AudioAhead(ValueError):
    def __init__(self, wait_ms):
        super().__init__('Audio exceeds realtime allowance')
        self.wait_ms = wait_ms


class AudioClock:
    """Server arrival anchor plus bounded sample cursors, no client timestamps.

    This preliminary mapping must be validated with real capture/network jitter
    before billing is enabled for a pilot.
    """
    def __init__(self):
        self.ends = {}

    def stamp(self, direction, now_ms):
        if now_ms < 0:
            raise ValueError('Invalid server clock')
        anchor = max(0, now_ms-FRAME_MS)//FRAME_MS*FRAME_MS
        start = self.ends.get(direction, anchor)
        if now_ms-start > 500:
            start = anchor
        if start+FRAME_MS > now_ms+200:
            raise AudioAhead(start+FRAME_MS-now_ms-200)
        self.ends[direction] = start+FRAME_MS
        return start

    async def stamp_realtime(self, direction, elapsed_ms):
        # Chrome may deliver buffered worklet frames in bursts after a short
        # scheduling pause. Drain at realtime speed instead of ending the call.
        # stamp() still bounds accepted audio time; socket backpressure bounds
        # memory. Never discard speech or advance billing faster than realtime.
        while True:
            try:
                return self.stamp(direction, elapsed_ms())
            except AudioAhead as ahead:
                await asyncio.sleep(ahead.wait_ms/1000)


async def serve_call(request, settings, store, identity, providers):
    if not settings.experimental_audio:
        return web.json_response({'error': 'audio_pipeline_not_ready'}, status=503)
    socket = web.WebSocketResponse(max_msg_size=4096, heartbeat=10)
    await socket.prepare(request)
    call = None
    streams = {}
    tasks = []
    reason = 'network_error'
    transcript_complete = False
    try:
        message = await asyncio.wait_for(socket.receive(), timeout=5)
        if message.type != WSMsgType.TEXT:
            raise ValueError('Expected authentication')
        auth = json.loads(message.data)
        token = auth.get('token') if isinstance(auth, dict) else None
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise ValueError('Invalid authentication')
        who = identity.authenticate(token, 'device')
        if who is None:
            reason = 'authentication_required'
            return socket
        source, target = auth.get('source'), auth.get('target')
        live_text = auth.get('live_text') is True
        if source not in LANGUAGES or target not in LANGUAGES or source == target:
            raise ValueError('Invalid language pair')
        try:
            call = store.start(who.account)
        except CallRejected as exc:
            reason = str(exc)
            return socket
        for direction, language in (('outgoing', source), ('incoming', target)):
            streams[direction] = await providers.open_stt(call, direction, language)
        meter = SpeechMeter(store, call)
        clock = AudioClock()
        started = time.monotonic()
        await socket.send_json({'type': 'ready', 'call_id': call, 'sample_rate': 16000,
                                'frame_ms': 20, 'experimental': True, 'graceful_stop': True})
        sequences = {'incoming': 0, 'outgoing': 0}

        async def read_audio():
            count = 0
            while True:
                message = await asyncio.wait_for(socket.receive(), timeout=15)
                if message.type == WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if isinstance(data, dict) and data.get('type') == 'stop':
                        return 'user_stop'
                    return 'protocol_error'
                if message.type != WSMsgType.BINARY:
                    return 'network_error'
                if len(message.data) != FRAME_BYTES+1 or message.data[0] not in (0, 1):
                    return 'protocol_error'
                if identity.authenticate(token, 'device') is None:
                    return 'credential_revoked'
                direction = 'outgoing' if message.data[0] == 0 else 'incoming'
                start = await clock.stamp_realtime(direction, lambda: int((time.monotonic()-started)*1000))
                pcm = message.data[1:]
                # Forward silence too; a failed send must not debit this frame.
                await asyncio.wait_for(streams[direction].send(pcm), timeout=3)
                meter.push(direction, pcm, start)
                state, balance_reserve = store.db.execute('SELECT state,reserve_ms FROM calls WHERE id=?', (call,)).fetchone()
                if state != 'active':
                    return 'balance_exhausted'
                count += 1
                if count % 50 == 0:
                    await asyncio.wait_for(socket.send_json({'type': 'balance', 'balance_ms': store.balance(who.account)+balance_reserve}), timeout=5)

        async def translate(direction, language, translated_language):
            queue = asyncio.Queue(maxsize=16)

            async def recognize():
                try:
                    async for result in streams[direction].results():
                        if result.get('partial'):
                            if live_text:
                                await asyncio.wait_for(socket.send_json({'type':'interim','direction':direction,
                                    'sequence':sequences[direction]+1,'original':result['text']}),timeout=5)
                            continue
                        sequences[direction] += 1
                        sequence = sequences[direction]
                        received = time.monotonic()
                        await asyncio.wait_for(socket.send_json({'type':'recognized','direction':direction,
                            'sequence':sequence,'original':result['text'],'uncertain':result['uncertain']}),timeout=5)
                        await queue.put((sequence,result,received))
                except Exception as exc:
                    await queue.put(exc)
                else:
                    await queue.put(None)

            reader = asyncio.create_task(recognize())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        return 'provider_error'
                    if isinstance(item,Exception):
                        raise item
                    sequence,result,received = item
                    begin = time.monotonic()
                    text = await providers.translate(call,result['text'],language,translated_language)
                    timing={'translation_queue_ms':round((begin-received)*1000),
                            'translation_ms':round((time.monotonic()-begin)*1000)}
                    if 'stt_backlog_ms' in result:
                        timing['stt_backlog_ms']=result['stt_backlog_ms']
                    await asyncio.wait_for(socket.send_json({'type':'translation','direction':direction,
                        'sequence':sequence,'original':result['text'],'text':text,'language':translated_language,
                        'uncertain':result['uncertain'],'timing':timing}),timeout=5)
            finally:
                reader.cancel()
                await asyncio.gather(reader,return_exceptions=True)

        async def watchdog():
            while True:
                await asyncio.sleep(1)
                if identity.authenticate(token, 'device') is None:
                    return 'credential_revoked'
                if meter.check_silence_timeout(int((time.monotonic()-started)*1000)):
                    return 'silence_timeout'

        tasks = [asyncio.create_task(read_audio()), asyncio.create_task(translate('outgoing', source, target)),
                 asyncio.create_task(translate('incoming', target, source)), asyncio.create_task(watchdog())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # A simultaneous provider failure wins over a normal client stop.
        outcomes = []
        phases = dict(zip(tasks, ('audio_ingress', 'outgoing_translation', 'incoming_translation', 'silence_watchdog')))
        for task in done:
            try:
                outcomes.append(task.result())
            except ValueError:
                logger.warning('Audio task failed: phase=%s kind=invalid_value', phases[task])
                outcomes.append('protocol_error')
            except asyncio.TimeoutError:
                logger.warning('Audio task failed: phase=%s kind=timeout', phases[task])
                outcomes.append('network_error')
            except Exception:
                logger.warning('Audio task failed: phase=%s kind=provider_failure', phases[task])
                outcomes.append('provider_error')
        reason = next((candidate for candidate in ('provider_error', 'protocol_error', 'credential_revoked',
                       'balance_exhausted', 'network_error', 'silence_timeout') if candidate in outcomes), 'user_stop')
        if reason == 'user_stop':
            # Credit stops immediately. Text already sent to providers may still
            # finish for the LOCAL journal; no capture/replay is charged here.
            store.stop(call, 'user_stop')
            tasks[0].cancel()
            tasks[3].cancel()
            if all(hasattr(stream, 'finish') for stream in streams.values()):
                try:
                    await asyncio.wait_for(asyncio.gather(*(stream.finish() for stream in streams.values())), timeout=2)
                    await asyncio.wait_for(asyncio.gather(tasks[1], tasks[2]), timeout=5)
                    transcript_complete = True
                except Exception:
                    transcript_complete = False
    except (ValueError, json.JSONDecodeError):
        reason = 'protocol_error'
    except asyncio.TimeoutError:
        reason = 'network_error'
    except Exception:
        reason = 'provider_error'
    finally:
        if call:
            # Fixed enums only: never log credentials, content or exception text.
            logger.warning('Audio call ended: reason=%s', reason)
        for task in tasks:
            task.cancel()
        if call:
            store.stop(call, reason if reason != 'balance_exhausted' else 'user_stop')
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(stream.close() for stream in streams.values()), return_exceptions=True)
        if not socket.closed:
            try:
                await asyncio.wait_for(socket.send_json({'type': 'stopped', 'reason': reason, 'restore_microphone': True,
                                                        'transcript_complete': transcript_complete}), timeout=2)
            except Exception:
                pass
            await socket.close()
    return socket
