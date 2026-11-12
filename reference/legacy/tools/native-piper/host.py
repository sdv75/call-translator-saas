"""Chrome Native Messaging host. Stdout contains framed JSON only."""
import base64
import contextlib
import io
import json
import os
import re
from pathlib import Path
import struct
import sys
import time
import wave

HOST_VERSION = 1
VOICES = {'ru': 'ru_RU-ruslan-medium', 'en': 'en_US-joe-medium', 'uk': 'uk_UA-ukrainian_tts-medium'}


def prepare_text(text, language):
    if language != 'uk':
        return text
    # This voice consumes Ukrainian characters directly, not eSpeak phonemes.
    # Its vocabulary contains lowercase letters and no numeric digits.
    from num2words import num2words
    text = text.lower().translate(str.maketrans({'’': "'", 'ʼ': "'", '‘': "'", '…': '...', '\u00a0': ' '}))
    return re.sub(r'\d+(?:[.,]\d+)?', lambda match: num2words(match[0].replace(',', '.'), lang='uk'), text)


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        data = stream.read(size - len(chunks))
        if not data:
            if not chunks:
                return None
            raise ValueError('truncated_frame')
        chunks.extend(data)
    return bytes(chunks)


def read_message(stream):
    header = read_exact(stream, 4)
    if header is None:
        return None
    size = struct.unpack('<I', header)[0]
    if not 0 < size <= 65536:
        raise ValueError('invalid_frame_size')
    data = read_exact(stream, size)
    if data is None:
        raise ValueError('truncated_frame')
    return json.loads(data)


def write_message(stream, message):
    data = json.dumps(message, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    if len(data) >= 1024 * 1024:
        raise ValueError('response_too_large')
    stream.write(struct.pack('<I', len(data)) + data)
    stream.flush()


class Engine:
    def __init__(self, root):
        self.root = root
        self.voices = {}

    def load(self):
        if self.voices:
            return
        import onnxruntime
        from piper import PiperVoice
        from piper.config import PiperConfig
        voices = {}
        for language, name in VOICES.items():
            model = self.root / 'models' / (name + '.onnx')
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = options.inter_op_num_threads = 1
            options.log_severity_level = 3
            voices[language] = PiperVoice(
                config=PiperConfig.from_dict(json.loads(Path(str(model) + '.json').read_text(encoding='utf-8'))),
                session=onnxruntime.InferenceSession(str(model), sess_options=options,
                    providers=['CPUExecutionProvider']))
        self.voices = voices

    def render(self, text, language):
        from piper import SynthesisConfig
        output = io.BytesIO()
        # Supply a valid header even if inference raises before writing audio.
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.voices[language].config.sample_rate)
            self.voices[language].synthesize_wav(prepare_text(text, language), wav,
                syn_config=SynthesisConfig(normalize_audio=False))
        audio = output.getvalue()
        if not 44 < len(audio) <= 32 * 1024 * 1024:
            raise ValueError('invalid_audio_size')
        return audio


def serve(reader, writer, engine):
    while True:
        message = read_message(reader)
        if message is None:
            return
        if not isinstance(message, dict):
            raise ValueError('invalid_request')
        request_id = message.get('id')
        if type(request_id) is not int or request_id < 1:
            raise ValueError('invalid_request_id')
        try:
            if message.get('type') == 'init':
                started = time.perf_counter()
                engine.load()
                write_message(writer, {'id': request_id, 'type': 'ready', 'version': HOST_VERSION,
                    'voices': list(VOICES), 'loadMs': round((time.perf_counter() - started) * 1000)})
            elif message.get('type') == 'synthesize':
                text, language = message.get('text'), message.get('language')
                if not isinstance(text, str) or not text.strip() or len(text) > 2000 or language not in VOICES:
                    raise ValueError('invalid_synthesis_request')
                engine.load()
                started = time.perf_counter()
                audio = engine.render(text, language)
                elapsed = round((time.perf_counter() - started) * 1000)
                # All chunks except the last are divisible by 3, so base64 concatenates safely.
                chunk_size = 192 * 1024
                chunks = 0
                for offset in range(0, len(audio), chunk_size):
                    write_message(writer, {'id': request_id, 'type': 'audio-chunk', 'index': chunks,
                        'data': base64.b64encode(audio[offset:offset + chunk_size]).decode('ascii')})
                    chunks += 1
                write_message(writer, {'id': request_id, 'type': 'audio-end', 'chunks': chunks,
                    'bytes': len(audio), 'synthesisMs': elapsed})
            else:
                raise ValueError('unknown_request')
        except Exception:
            # Never expose text, provider responses, local paths or credentials.
            write_message(writer, {'id': request_id, 'type': 'error', 'error': 'native_synthesis_failed'})


def main():
    if os.name == 'nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    if '--self-test' in sys.argv:
        engine = Engine(root)
        engine.load()
        for language, text in [('ru', '\u041f\u0440\u0438\u0432\u0435\u0442.'), ('en', 'Hello.'), ('uk', 'Привіт! Це перевірка українського голосу.')]:
            audio = engine.render(text, language)
            with wave.open(io.BytesIO(audio)) as wav:
                assert wav.getnframes() > 0
        print('Native Piper self-test: PASS')
        return
    # Registry manifest limits callers; verify the browser-provided origin as well.
    installation = json.loads((root / 'org.call_translator.piper.json').read_text(encoding='utf-8-sig'))
    if len(sys.argv) < 2 or sys.argv[1] not in installation['allowed_origins']:
        raise ValueError('unauthorized_origin')
    protocol_output = sys.stdout.buffer
    with contextlib.redirect_stdout(io.StringIO()):
        serve(sys.stdin.buffer, protocol_output, Engine(root))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt):
        sys.exit(1)
