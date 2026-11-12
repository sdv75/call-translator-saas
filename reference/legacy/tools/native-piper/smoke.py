"""Exercise the actual frozen host over Chrome's framed protocol, no registry needed."""
import base64
import io
import json
from pathlib import Path
import struct
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[2]


def frame(message):
    data = json.dumps(message).encode()
    return struct.pack('<I', len(data)) + data


def main():
    package = Path(json.loads((ROOT / 'dist/native-piper/latest.json').read_text())['package'])
    host = package / 'PiperHost'
    manifest = host / 'org.call_translator.piper.json'
    origin = 'chrome-extension://' + 'a' * 32 + '/'
    with manifest.open('x', encoding='utf-8') as file:
        json.dump({'allowed_origins': [origin]}, file)
    try:
        requests = [{'id': 1, 'type': 'init'},
            {'id': 2, 'type': 'synthesize', 'language': 'ru', 'text': 'Привет! Это проверка локального перевода.'},
            {'id': 3, 'type': 'synthesize', 'language': 'en', 'text': 'Hello! This is a local translation test.'},
            {'id': 4, 'type': 'synthesize', 'language': 'uk', 'text': 'Привіт! Це перевірка українського перекладу.'}]
        result = subprocess.run([str(host / 'PiperHost.exe'), origin],
            input=b''.join(frame(message) for message in requests), capture_output=True, timeout=150)
        assert result.returncode == 0, 'Host process failed'
        stream = io.BytesIO(result.stdout)
        replies = []
        while header := stream.read(4):
            assert len(header) == 4
            size = struct.unpack('<I', header)[0]
            assert size < 1024 * 1024
            replies.append(json.loads(stream.read(size)))
        assert replies[0]['type'] == 'ready'
        assert 'uk' in replies[0]['voices']
        for request_id in (2, 3, 4):
            messages = [message for message in replies if message['id'] == request_id]
            assert messages[-1]['type'] == 'audio-end'
            chunks = messages[:-1]
            assert [chunk['index'] for chunk in chunks] == list(range(len(chunks)))
            audio = base64.b64decode(''.join(chunk['data'] for chunk in chunks), validate=True)
            assert len(audio) == messages[-1]['bytes']
            with wave.open(io.BytesIO(audio)) as wav:
                assert wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getnframes() > 0
            output = ROOT / 'tts-output/native-language-smoke'
            output.mkdir(parents=True, exist_ok=True)
            (output / ({2: 'ru', 3: 'en', 4: 'uk'}[request_id] + '.wav')).write_bytes(audio)
            print(f'Frozen host request {request_id}: valid WAV, {len(audio)} bytes, {messages[-1]["synthesisMs"]} ms')
        print('Frozen Native Messaging host, all three languages and chunked audio: PASS')
    finally:
        if manifest.resolve().parent != host.resolve():
            raise RuntimeError('Unexpected test manifest path')
        manifest.unlink()


if __name__ == '__main__':
    main()
