import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from server.accounting import Accounting
from server.config import Settings
from server.economics import Rates, Usage
from server.providers import ProviderFailed, Providers, STTStream, transcript_result
from server.speech import FRAME_BYTES


class Response:
    status = 200

    def __init__(self, content):
        self.content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.content


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_interim_is_display_only_until_final_and_keeps_audio_cursor(self):
        event={'type':'Results','is_final':False,'start':1.2,'duration':.8,
               'channel':{'alternatives':[{'transcript':'Остання фраза перевірки:','confidence':.9}]}}
        self.assertIsNone(transcript_result(event))
        partial=transcript_result(event,include_interim=True)
        self.assertTrue(partial['partial'])
        self.assertEqual(partial['audio_end_ms'],2000)
        event['is_final']=True
        self.assertFalse(transcript_result(event,include_interim=True)['partial'])

    def test_empty_transcript_does_not_contaminate_confidence(self):
        def event(text, confidence):
            return {'type': 'Results', 'is_final': True, 'channel': {'alternatives': [{'transcript': text, 'confidence': confidence}]}}
        self.assertIsNone(transcript_result(event('', 0)))
        self.assertFalse(transcript_result(event('Hello.', 0.99))['uncertain'])
        self.assertTrue(transcript_result(event('Maybe.', 0.2))['uncertain'])

    async def test_retry_usage_and_silence_send(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Accounting(Path(temp)/'db.sqlite3')
            try:
                call = store.start(store.register('sub'))
                usage = Usage(store)

                class Session:
                    attempts = 0

                    def post(self, *args, **kwargs):
                        self.attempts += 1
                        return Response({'usage': {'prompt_tokens': 50, 'completion_tokens': 10},
                            'choices': [{'message': {'content': '' if self.attempts == 1 else 'Hello'}, 'finish_reason': 'stop'}]})

                providers = Providers(Settings(), Session(), usage)
                self.assertEqual(await providers.translate(call, 'Привет', 'ru', 'en'), 'Hello')
                report = usage.report(Rates(Decimal(0), Decimal(0), Decimal(0)))
                self.assertEqual(report['input_tokens'], 100)
                self.assertEqual(report['retry_attempts'], 1)

                class Socket:
                    sent = []

                    async def send_bytes(self, data):
                        self.sent.append(data)

                socket = Socket()
                stream = STTStream(socket, usage, call, 'incoming')
                await stream.send(bytes(FRAME_BYTES))
                self.assertEqual(socket.sent, [bytes(FRAME_BYTES)])
                self.assertEqual(usage.report(Rates(Decimal(0), Decimal(0), Decimal(0)))['stt_incoming_ms'], 20)
            finally:
                store.close()
