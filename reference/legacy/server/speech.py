"""Persistent, serialized Piper worker with bounded requests and restart on failure."""
import asyncio
import contextlib
import io
import json
import os
import struct
import sys
import wave
from pathlib import Path


class Speech:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()

    async def _frame(self):
        size = struct.unpack('!I', await self.process.stdout.readexactly(4))[0]
        if size > 32 * 1024 * 1024:
            raise RuntimeError('Invalid synthesis response')
        return await self.process.stdout.readexactly(size)

    async def _close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
            await process.wait()

    async def _start(self):
        if self.process is not None and self.process.returncode is None:
            return
        await self._close()
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, '-u', str(Path(__file__).resolve()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        if await asyncio.wait_for(self._frame(), 30) != b'':
            raise RuntimeError('Invalid synthesis handshake')

    async def start(self):
        async with self.lock:
            try:
                await self._start()
            except BaseException:
                await self._close()
                raise

    async def close(self):
        async with self.lock:
            await self._close()

    async def synthesize(self, text, language):
        if language not in ('ru', 'en'):
            raise ValueError('Unsupported synthesis language')
        async with self.lock:
            try:
                await self._start()
                async def request():
                    self.process.stdin.write((json.dumps({'text': text, 'language': language}) + '\n').encode())
                    await self.process.stdin.drain()
                    audio = await self._frame()
                    if not audio.startswith(b'RIFF'):
                        raise RuntimeError('Invalid synthesis audio')
                    return audio
                return await asyncio.wait_for(request(), 20)
            except BaseException:
                # Cancellation must discard the pending frame before another request.
                await self._close()
                raise


def worker():
    import onnxruntime
    from piper import PiperVoice
    from piper.config import PiperConfig

    voices = {}
    for language in ('ru', 'en'):
        model = Path(os.environ['TRANSLATOR_MODELS_DIR']) / (language + '.onnx')
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        voices[language] = PiperVoice(
            config=PiperConfig.from_dict(json.loads(Path(str(model) + '.json').read_text())),
            session=onnxruntime.InferenceSession(str(model), sess_options=options,
                providers=['CPUExecutionProvider']))

    def render(text, language):
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            voices[language].synthesize_wav(text, wav)
        return output.getvalue()

    # Warm the inference sessions before accepting the call.
    render('Привет.', 'ru')
    render('Hello.', 'en')
    sys.stdout.buffer.write(struct.pack('!I', 0))
    sys.stdout.buffer.flush()
    for line in sys.stdin.buffer:
        request = json.loads(line)
        audio = render(request['text'], request['language'])
        sys.stdout.buffer.write(struct.pack('!I', len(audio)) + audio)
        sys.stdout.buffer.flush()


if __name__ == '__main__':
    worker()
