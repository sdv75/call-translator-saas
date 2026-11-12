import asyncio
import sys
import unittest
from unittest.mock import patch

from speech import Speech


FAKE_WORKER = '''
import json, struct, sys, time
sys.stdout.buffer.write(struct.pack('!I', 0)); sys.stdout.buffer.flush()
for line in sys.stdin:
    item = json.loads(line)
    if item['text'] == 'crash': sys.exit(1)
    if item['text'] == 'wait': time.sleep(60)
    audio = b'RIFF' + item['text'].encode()
    sys.stdout.buffer.write(struct.pack('!I', len(audio)) + audio)
    sys.stdout.buffer.flush()
'''


class SpeechTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.speech = Speech()
        original = asyncio.create_subprocess_exec
        self.starts = 0

        async def launch(*args, **kwargs):
            self.starts += 1
            return await original(sys.executable, '-u', '-c', FAKE_WORKER, **kwargs)

        self.patcher = patch('speech.asyncio.create_subprocess_exec', launch)
        self.patcher.start()

    async def asyncTearDown(self):
        await self.speech.close()
        self.patcher.stop()

    async def test_reuses_worker_and_serializes_both_languages(self):
        await self.speech.start()
        results = await asyncio.gather(self.speech.synthesize('one', 'en'),
            self.speech.synthesize('два', 'ru'))
        self.assertEqual(results, [b'RIFFone', 'RIFFдва'.encode()])
        self.assertEqual(self.starts, 1)

    async def test_crash_restarts_worker(self):
        with self.assertRaises(asyncio.IncompleteReadError):
            await self.speech.synthesize('crash', 'en')
        self.assertEqual(await self.speech.synthesize('next', 'en'), b'RIFFnext')
        self.assertEqual(self.starts, 2)

    async def test_cancellation_discards_pending_audio(self):
        await self.speech.start()
        task = asyncio.create_task(self.speech.synthesize('wait', 'en'))
        await asyncio.sleep(.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(self.speech.process)
        self.assertEqual(await self.speech.synthesize('new', 'en'), b'RIFFnew')


if __name__ == '__main__':
    unittest.main()
