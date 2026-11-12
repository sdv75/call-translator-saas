"""Offline pipeline checks; no provider credentials or requests required."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app


class PipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_graceful_stop_flushes_and_translates_final_tail(self):
        finishing = asyncio.Event(); finishing.set()
        sent = []
        attempts = []

        class Upstream:
            def __aiter__(self): return self.messages()
            async def messages(self):
                for index, text in enumerate(('Пропоную зустрітися', 'в п’ятницю біля головного входу')):
                    yield SimpleNamespace(type=app.WSMsgType.TEXT, data=json.dumps({
                        'type': 'Results', 'is_final': True, 'speech_final': False,
                        'start': index, 'duration': .5,
                        'channel': {'alternatives': [{'transcript': text, 'confidence': .95}]}}))
            async def close(self): pass

        class Response:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def raise_for_status(self): pass
            async def json(self):
                attempts.append(1)
                content = 'Пропоную зустрітися в п’ятницю біля головного входу' if len(attempts) == 1 else 'Предлагаю встретиться в пятницу у главного входа'
                return {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}

        async def send_json(message): sent.append(message)
        downstream = SimpleNamespace(send_json=send_json, send_bytes=AsyncMock(), close=AsyncMock())
        activity = SimpleNamespace(has_signal=lambda result: True, overlaps=lambda result: False)
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test-only'}):
            await asyncio.wait_for(app.pipeline(SimpleNamespace(post=lambda *args, **kwargs: Response()),
                Upstream(), downstream, 1, 'uk', 'ru', tts='client', activity=activity, finishing=finishing), 2)
        translated = next(message for message in sent if message['type'] == 'translation')
        self.assertEqual(translated['text'], 'Пропоную зустрітися в п’ятницю біля головного входу')
        self.assertTrue(translated['uncertain'])
        self.assertEqual(len(translated['segments']), 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(translated['translation'], 'Предлагаю встретиться в пятницу у главного входа')
        self.assertFalse(any(message['type'] == 'error' for message in sent))

    async def test_pending_and_uncertain_fragments_are_journaled_before_endpoint(self):
        delivered = asyncio.Event()
        sent = []

        class Upstream:
            def __aiter__(self):
                return self.messages()

            async def messages(self):
                for index, text in enumerate(('Keep the beginning', 'and the quiet ending')):
                    yield SimpleNamespace(type=app.WSMsgType.TEXT, data=json.dumps({
                        'type': 'Results', 'is_final': True, 'speech_final': False,
                        'start': index, 'duration': .5,
                        'channel': {'alternatives': [{'transcript': text, 'confidence': .2 if index else .95}]}}))
                yield SimpleNamespace(type=app.WSMsgType.TEXT, data=json.dumps({'type': 'UtteranceEnd'}))
                await delivered.wait()

            async def close(self):
                pass

        class Response:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

            async def json(self):
                return {'choices': [{'message': {'content': 'Полное предложение'}, 'finish_reason': 'stop'}]}

        async def send_json(message):
            sent.append(message)
            if message['type'] == 'translation':
                delivered.set()

        downstream = SimpleNamespace(send_json=send_json, send_bytes=AsyncMock(), close=AsyncMock())
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test-only'}):
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                await asyncio.wait_for(app.pipeline(SimpleNamespace(post=lambda *args, **kwargs: Response()),
                    Upstream(), downstream, 0, 'en', 'ru', tts='client'), 2)
        recognized = [message for message in sent if message['type'] == 'recognized']
        self.assertEqual([message['partial'] for message in recognized], [True, True, False])
        self.assertEqual([message['sequence'] for message in recognized], [1, 1, 1])
        self.assertEqual(recognized[-1]['text'], 'Keep the beginning and the quiet ending')
        translated = next(message for message in sent if message['type'] == 'translation')
        self.assertEqual(translated['text'], recognized[-1]['text'])
        self.assertTrue(translated['uncertain'])

    async def test_client_lifecycle_does_not_start_piper(self):
        with patch.object(app.speech, 'start', AsyncMock()) as start, \
                patch.object(app.speech, 'close', AsyncMock()) as close:
            lifecycle = app.speech_lifecycle(None)
            await anext(lifecycle)
            start.assert_not_awaited()
            with self.assertRaises(StopAsyncIteration):
                await anext(lifecycle)
            close.assert_awaited_once()

    async def test_translation_effort_and_phase_timings(self):
        for model, effort, tts, source, target in [('openai/gpt-oss-20b', 'low', 'server', 'ru', 'en'),
                ('custom-model', None, 'server', 'ru', 'en'), ('openai/gpt-oss-20b', 'low', 'client', 'ru', 'en'),
                ('openai/gpt-oss-20b', 'low', 'client', 'uk', 'en'),
                ('openai/gpt-oss-20b', 'low', 'client', 'en', 'uk'),
                ('openai/gpt-oss-20b', 'low', 'client', 'ru', 'uk'),
                ('openai/gpt-oss-20b', 'low', 'client', 'uk', 'ru')]:
            with self.subTest(model=model, tts=tts):
                delivered = asyncio.Event()
                sent = []
                requests = []

                class Upstream:
                    def __aiter__(self):
                        return self.messages()

                    async def messages(self):
                        for index in range(12):
                            yield SimpleNamespace(type=app.WSMsgType.TEXT, data=json.dumps({
                                'type': 'Results', 'is_final': True, 'speech_final': True,
                                'start': index, 'duration': .5,
                                'channel': {'alternatives': [{'transcript': f'Привет {index}'}]}}))
                        await delivered.wait()

                    async def close(self):
                        pass

                class Response:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                    def raise_for_status(self):
                        pass

                    async def json(self):
                        return {'choices': [{'message': {'content': 'Hello'}}]}

                def post(url, **kwargs):
                    requests.append(kwargs['json'])
                    return Response()

                async def send_json(message):
                    sent.append(message)
                    if message['type'] == 'translation' and message['sequence'] == 12:
                        delivered.set()

                async def send_bytes(data):
                    self.assertEqual(tts, 'server')
                    self.assertEqual(data, b'\x00wav')

                downstream = SimpleNamespace(send_json=send_json, send_bytes=send_bytes, close=AsyncMock())
                with patch.dict(os.environ, {'GROQ_MODEL': model, 'GROQ_API_KEY': 'test-only'}), \
                        patch.object(app, 'synthesize', AsyncMock(return_value=b'wav')) as synthesis:
                    with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                        await asyncio.wait_for(app.pipeline(SimpleNamespace(post=post), Upstream(),
                            downstream, 0, source, target, tts=tts), 2)
                    if tts == 'client':
                        synthesis.assert_not_awaited()
                self.assertEqual(requests[0].get('reasoning_effort'), effort)
                result = next(message for message in sent if message['type'] == 'translation')
                self.assertEqual(result['translation'], 'Hello')
                self.assertEqual(result['language'], target)
                self.assertIn(f'Translate speech from {app.LANGUAGES[source]} to {app.LANGUAGES[target]}',
                    requests[0]['messages'][0]['content'])
                self.assertEqual(result['tts'], tts)
                translations = [message for message in sent if message['type'] == 'translation']
                self.assertEqual([message['sequence'] for message in translations], list(range(1, 13)))
                self.assertEqual([message['text'] for message in translations], [f'Привет {index}' for index in range(12)])
                self.assertEqual(len([message for message in sent if message['type'] == 'recognized']), 12)
                self.assertEqual(translations[1]['received_at'] - translations[0]['received_at'], 1000)
                self.assertEqual(set(result['timings_ms']), {'queue', 'translation', 'tts'})
                self.assertTrue(all(value >= 0 for value in result['timings_ms'].values()))


if __name__ == '__main__':
    unittest.main()
