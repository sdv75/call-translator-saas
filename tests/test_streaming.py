import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from server.app import IDENTITY, PROVIDERS, STORE, create_app
from server.config import Settings
from server.economics import Usage
from server.providers import ProviderFailed
from server.speech import FRAME_BYTES, SpeechMeter
from server.streaming import AudioClock


class FakeStream:
    def __init__(self, usage, call, direction, *, fail_send=False):
        self.usage, self.call, self.direction = usage, call, direction
        self.frames = []
        self.closed = False
        self.fail_send = fail_send
        self.queue = asyncio.Queue()

    async def send(self, pcm):
        if self.fail_send:
            raise ProviderFailed()
        self.frames.append(pcm)
        self.usage.stt_sent(f'{self.call}:{self.direction}:{len(self.frames)}', self.call, self.direction, 20)

    async def results(self):
        while True:
            result = await self.queue.get()
            if result is None:
                return
            yield result

    async def finish(self):
        await self.queue.put(None)

    async def close(self):
        self.closed = True


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(database=Path(self.temp.name)/'db.sqlite3',
                                      deepgram_key='test-stt-key', groq_key='test-translation-key', experimental_audio=True))
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.account = self.app[STORE].register('sub')
        identity = self.app[IDENTITY]
        code = identity.new_pairing(self.account)
        self.token, self.device = identity.redeem_pairing(code)
        self.streams = {}
        self.fail_send = False

        async def open_stream(call, direction, language):
            stream = FakeStream(Usage(self.app[STORE]), call, direction, fail_send=self.fail_send)
            self.streams[direction] = stream
            return stream

        self.patch = patch.object(self.app[PROVIDERS], 'open_stt', open_stream)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        await self.client.close()
        self.temp.cleanup()

    async def connect(self, token=None):
        socket = await self.client.ws_connect('/ws')
        await socket.send_json({'token': token or self.token, 'source': 'ru', 'target': 'en'})
        return socket, await socket.receive_json(timeout=5)

    async def test_auth_and_second_call_preserve_first(self):
        invalid, message = await self.connect('invalid-token')
        self.assertEqual(message['reason'], 'authentication_required')
        await invalid.close()
        socket, ready = await self.connect()
        self.assertEqual(ready['type'], 'ready')
        other, message = await self.connect()
        self.assertEqual(message['reason'], 'account_busy')
        await other.close()
        self.assertEqual(self.app[STORE].balance(self.account), 295000)
        await socket.send_json({'type': 'stop'})
        self.assertEqual((await socket.receive_json(timeout=5))['reason'], 'user_stop')
        await socket.close()
        self.assertEqual(self.app[STORE].balance(self.account), 300000)

    async def test_silence_forwarded_and_malformed_frame_releases(self):
        socket, _ = await self.connect()
        await socket.send_bytes(b'\x00'+bytes(FRAME_BYTES))
        await socket.send_bytes(b'\x01'+bytes(FRAME_BYTES))
        await socket.send_bytes(b'broken')
        message = await socket.receive_json(timeout=5)
        self.assertEqual(message['reason'], 'protocol_error')
        self.assertTrue(message['restore_microphone'])
        await socket.close()
        self.assertEqual(self.streams['incoming'].frames, [bytes(FRAME_BYTES)])
        self.assertEqual(self.streams['outgoing'].frames, [bytes(FRAME_BYTES)])
        self.assertTrue(all(stream.closed for stream in self.streams.values()))
        self.assertEqual(self.app[STORE].balance(self.account), 300000)

    async def test_failed_provider_frame_is_not_charged(self):
        self.fail_send = True
        socket, _ = await self.connect()
        await socket.send_bytes(b'\x00'+bytes(FRAME_BYTES))
        message = await socket.receive_json(timeout=5)
        self.assertEqual(message['reason'], 'provider_error')
        await socket.close()
        self.assertEqual(self.app[STORE].balance(self.account), 300000)

    async def test_buffered_duplex_frames_continue_without_protocol_stop(self):
        socket, _ = await self.connect()
        for _ in range(40):
            await socket.send_bytes(b'\x00'+bytes(FRAME_BYTES))
            await socket.send_bytes(b'\x01'+bytes(FRAME_BYTES))
        await socket.send_json({'type': 'stop'})
        events = []
        while not events or events[-1]['type'] != 'stopped':
            events.append(await socket.receive_json(timeout=5))
        self.assertEqual(events[-1]['reason'], 'user_stop')
        self.assertEqual(len(self.streams['incoming'].frames), 40)
        self.assertEqual(len(self.streams['outgoing'].frames), 40)
        self.assertEqual(self.app[STORE].balance(self.account), 300000)
        await socket.close()

    async def test_metered_speech_overlap_on_websocket(self):
        class Detector:
            def is_speech(self, pcm, rate):
                return True

        def meter(store, call):
            return SpeechMeter(store, call, detector_factory=Detector)

        with patch('server.streaming.SpeechMeter', meter), patch.object(AudioClock, 'stamp', return_value=0):
            socket, _ = await self.connect()
            await socket.send_bytes(b'\x00'+bytes(FRAME_BYTES))
            await socket.send_bytes(b'\x01'+bytes(FRAME_BYTES))
            await socket.send_json({'type': 'stop'})
            self.assertEqual((await socket.receive_json(timeout=5))['reason'], 'user_stop')
            await socket.close()
        self.assertEqual(self.app[STORE].balance(self.account), 299980)

    async def test_device_revoke_stops_media(self):
        socket, _ = await self.connect()
        self.app[IDENTITY].revoke_device(self.account, self.device)
        await socket.send_bytes(b'\x00'+bytes(FRAME_BYTES))
        self.assertEqual((await socket.receive_json(timeout=5))['reason'], 'credential_revoked')
        await socket.close()
        self.assertEqual(self.app[STORE].balance(self.account), 300000)

    async def test_duplex_speech_survives_watchdog_with_audio_clock_lead(self):
        class Detector:
            def is_speech(self, pcm, rate):
                return True

        def meter(store, call):
            return SpeechMeter(store, call, detector_factory=Detector)

        origin = time.monotonic()
        # Simulate ingress's accepted buffer lead while both streams continue.
        def stamp(clock, direction, now_ms):
            start = max(clock.ends.get(direction, 0), int((time.monotonic()-origin)*1000)+100)
            clock.ends[direction] = start+20
            return start

        with patch('server.streaming.SpeechMeter', meter), patch.object(AudioClock, 'stamp', stamp), \
                patch.object(self.app[PROVIDERS], 'translate', AsyncMock(return_value='translated')):
            socket, _ = await self.connect()
            events = []

            async def read():
                async for message in socket:
                    event = message.json()
                    events.append(event)
                    if event['type'] == 'stopped':
                        return

            reader = asyncio.create_task(read())
            try:
                for index in range(110):
                    for direction in (0, 1):
                        await socket.send_bytes(bytes([direction])+bytes(FRAME_BYTES))
                    if index in (5, 60, 100):
                        for stream in self.streams.values():
                            await stream.queue.put({'text': 'fixed fixture', 'uncertain': False})
                    await asyncio.sleep(.02)
                await socket.send_json({'type': 'stop'})
                await asyncio.wait_for(reader, timeout=5)
                self.assertEqual(events[-1]['reason'], 'user_stop')
                self.assertEqual(sum(event['type']=='translation' for event in events), 6)
                self.assertEqual({event['direction'] for event in events if event['type']=='translation'},
                                 {'incoming', 'outgoing'})
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
                await socket.close()

    async def test_recognition_precedes_translation_with_same_sequence(self):
        with patch.object(self.app[PROVIDERS], 'translate', AsyncMock(return_value='translated')):
            socket, _ = await self.connect()
            await self.streams['incoming'].queue.put({'text': 'fixture source', 'uncertain': True})
            recognized = await socket.receive_json(timeout=5)
            translated = await socket.receive_json(timeout=5)
            self.assertEqual(recognized['type'], 'recognized')
            self.assertEqual(translated['type'], 'translation')
            self.assertEqual(recognized['sequence'], translated['sequence'])
            self.assertTrue(translated['uncertain'])
            await socket.send_json({'type': 'stop'})
            self.assertTrue((await socket.receive_json(timeout=5))['transcript_complete'])
            await socket.close()

    async def test_slow_translation_does_not_block_live_recognition(self):
        release=asyncio.Event()

        async def translate(*args):
            await release.wait()
            return 'translated'

        with patch.object(self.app[PROVIDERS],'translate',AsyncMock(side_effect=translate)) as translator:
            socket=await self.client.ws_connect('/ws')
            await socket.send_json({'token':self.token,'source':'ru','target':'uk','live_text':True})
            self.assertEqual((await socket.receive_json(timeout=5))['type'],'ready')
            stream=self.streams['outgoing']
            await stream.queue.put({'text':'partial','uncertain':False,'partial':True})
            self.assertEqual((await socket.receive_json(timeout=5))['type'],'interim')
            for text in ('first','second'):
                await stream.queue.put({'text':text,'uncertain':False})
            first=await socket.receive_json(timeout=5)
            second=await socket.receive_json(timeout=5)
            self.assertEqual([first['type'],second['type']],['recognized','recognized'])
            self.assertEqual([first['sequence'],second['sequence']],[1,2])
            release.set()
            for _ in range(2):
                result=await socket.receive_json(timeout=5)
                self.assertEqual(result['type'],'translation')
                self.assertGreaterEqual(result['timing']['translation_ms'],0)
                self.assertGreaterEqual(result['timing']['translation_queue_ms'],0)
            self.assertEqual(translator.await_count,2,'Interim text must never be translated/billed')
            await socket.send_json({'type':'stop'})
            self.assertEqual((await socket.receive_json(timeout=5))['reason'],'user_stop')
            await socket.close()

    async def test_manual_stop_releases_credit_before_final_text_drain(self):
        with patch.object(self.app[PROVIDERS], 'translate', AsyncMock(return_value='tail translation')):
            socket, _ = await self.connect()
            for stream in self.streams.values():
                async def finish(stream=stream):
                    self.assertEqual(self.app[STORE].balance(self.account), 300000)
                    await stream.queue.put({'text': 'final fixture', 'uncertain': False})
                    await stream.queue.put(None)
                stream.finish = finish
            await socket.send_json({'type': 'stop'})
            events = []
            while True:
                event = await socket.receive_json(timeout=5)
                events.append(event)
                if event['type'] == 'stopped':
                    break
            self.assertTrue(events[-1]['transcript_complete'])
            self.assertEqual(sum(event['type'] == 'recognized' for event in events), 2)
            self.assertEqual(sum(event['type'] == 'translation' for event in events), 2)
            self.assertEqual(self.app[STORE].balance(self.account), 300000)
            await socket.close()


class ClockTests(unittest.TestCase):
    def test_client_cannot_flood_unbounded_audio_time(self):
        clock = AudioClock()
        for _ in range(10):
            clock.stamp('incoming', 0)
        with self.assertRaises(ValueError):
            clock.stamp('incoming', 0)
        self.assertEqual(clock.stamp('outgoing', 0), 0)
        self.assertEqual(clock.stamp('incoming', 1000), 980)


class BufferedClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_buffered_audio_waits_instead_of_aborting_or_dropping(self):
        clock = AudioClock()
        elapsed = 0
        waits = []

        async def sleep(seconds):
            nonlocal elapsed
            waits.append(seconds)
            elapsed += round(seconds*1000)

        with patch('server.streaming.asyncio.sleep', sleep):
            starts = [await clock.stamp_realtime('incoming', lambda: elapsed) for _ in range(50)]
        self.assertEqual(starts, list(range(0, 1000, 20)))
        self.assertTrue(waits)
        self.assertLessEqual(clock.ends['incoming'], elapsed+200)
