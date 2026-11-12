"""Check the prepared embedded runtime on this host, not a clean-Windows test."""

import argparse
import base64
import hashlib
import io
import json
import os
import struct
import subprocess
import tempfile
import zipfile
import wave
from pathlib import Path, PurePosixPath


def smoke(prepared: Path, voice_root: Path | None = None, voice_id: str | None = None):
    manifest = json.loads((prepared/'build-manifest.json').read_text(encoding='utf-8-sig'))
    runtime = prepared/'runtime.zip'
    if hashlib.sha256(runtime.read_bytes()).hexdigest() != manifest['prepared_runtime_sha256']:
        raise ValueError('Prepared runtime integrity check failed')
    with tempfile.TemporaryDirectory(prefix='ct-local-smoke-') as temp:
        root = Path(temp)
        with zipfile.ZipFile(runtime) as archive:
            for name in archive.namelist():
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                    raise ValueError('Unsafe runtime archive')
            archive.extractall(root)
        # No system Python, uv, user site packages or PATH fallback.
        environment = {key: value for key, value in os.environ.items() if key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP')}
        environment['PATH'] = ''
        if voice_root is not None:
            environment['CT_LOCAL_VOICE_ROOT'] = str(voice_root.resolve())
        command = [str(root/'python.exe'), '-I', '-m', 'call_translator_local']
        result = subprocess.run(command+['--self-test'], env=environment, cwd=root,
                                capture_output=True, check=True, timeout=30)
        diagnostic = json.loads(result.stdout)
        if manifest.get('local_dependency_files', 0) and not diagnostic.get('local_dependencies_ready'):
            raise ValueError('Embedded synthesis dependencies are unavailable')
        body = json.dumps({'id': 1, 'type': 'status'}).encode('utf-8')
        result = subprocess.run(command, input=struct.pack('<I', len(body))+body,
                                env=environment, cwd=root, capture_output=True, check=True, timeout=30)
        length = struct.unpack('<I', result.stdout[:4])[0]
        if len(result.stdout) != length+4:
            raise ValueError('Unexpected bytes on native stdout')
        status = json.loads(result.stdout[4:])
        if status.get('id') != 1 or status.get('protocol') != 1:
            raise ValueError('Native protocol smoke failed')
        preview_ok = False
        if voice_id is not None:
            body = json.dumps({'id': 2, 'type': 'preview-voice', 'voice_id': voice_id}).encode('utf-8')
            result = subprocess.run(command, input=struct.pack('<I', len(body))+body,
                                    env=environment, cwd=root, capture_output=True, check=True, timeout=180)
            messages, cursor = [], 0
            while cursor < len(result.stdout):
                size = struct.unpack('<I', result.stdout[cursor:cursor+4])[0]
                cursor += 4
                messages.append(json.loads(result.stdout[cursor:cursor+size]))
                cursor += size
            if not messages or messages[-1].get('type') != 'audio-end':
                raise ValueError('Embedded local synthesis failed')
            audio = base64.b64decode(''.join(item['data'] for item in messages[:-1]), validate=True)
            preview_ok = len(audio) == messages[-1]['bytes'] and audio[:4] == b'RIFF' and audio[8:12] == b'WAVE'
            if preview_ok:
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    preview_ok = wav.getnchannels() == 1 and wav.getsampwidth() == 2 and any(wav.readframes(wav.getnframes()))
            if not preview_ok:
                raise ValueError('Embedded audio framing failed')
        return {'embedded_runtime': diagnostic['status'], 'native_framing': 'ok',
                'local_dependencies_ready': diagnostic.get('local_dependencies_ready', False),
                'local_synthesis_verified': preview_ok,
                'empty_path': True, 'clean_windows_verified': False, 'pyapp_executable_verified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('prepared', type=Path)
    parser.add_argument('--voice-root', type=Path)
    parser.add_argument('--voice-id')
    args = parser.parse_args()
    print(json.dumps(smoke(args.prepared, args.voice_root, args.voice_id), indent=2))


if __name__ == '__main__':
    main()
