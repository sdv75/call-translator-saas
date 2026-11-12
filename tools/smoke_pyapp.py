"""Test a real PyApp executable with a fresh private extraction directory.

No registry, browser profile, real account, audio device, or provider is used.
PyApp may populate its normal per-user distribution cache outside the private
extraction directory; this tool does not delete or replace that shared cache.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import struct
import subprocess
import tempfile
import wave
from pathlib import Path


def frame(message):
    body = json.dumps(message).encode('utf-8')
    return struct.pack('<I', len(body)) + body


def messages(data):
    result = []
    while data:
        if len(data) < 4:
            raise ValueError('Unexpected bytes on native stdout')
        length = struct.unpack('<I', data[:4])[0]
        if not 0 < length <= 1024 * 1024 or len(data) < length + 4:
            raise ValueError('Invalid native frame')
        result.append(json.loads(data[4:length + 4]))
        data = data[length + 4:]
    return result


def smoke(prepared, voice_root=None, voice_id=None):
    manifest = json.loads((prepared/'build-manifest.json').read_text(encoding='utf-8-sig'))
    executable = (prepared/'CallTranslatorLocal.exe').resolve()
    if not manifest.get('build_verified') or hashlib.sha256(executable.read_bytes()).hexdigest() != manifest.get('pyapp_executable_sha256'):
        raise ValueError('A verified PyApp executable is required')
    with tempfile.TemporaryDirectory(prefix='ct-pyapp-smoke-') as temp:
        root = Path(temp)
        environment = {key: value for key, value in os.environ.items() if key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'LOCALAPPDATA')}
        environment.update(PATH='', PYTHONUTF8='1', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
        environment['PYAPP_INSTALL_DIR_CALL-TRANSLATOR-LOCAL'] = str(root/'runtime')
        environment['CT_LOCAL_VOICE_ROOT'] = str(root/'empty-voices')

        def run(body):
            return subprocess.run([str(executable)], input=body, env=environment, cwd=root,
                                  capture_output=True, check=True, timeout=180)

        # First boot is framed stdio, BEFORE any self-test has warmed the cache.
        response = messages(run(frame({'id': 1, 'type': 'status'})).stdout)
        if len(response) != 1 or response[0].get('id') != 1 or response[0].get('protocol') != 1 or response[0].get('ready') is not False:
            raise ValueError('First-boot native status failed')
        diagnostic = subprocess.run([str(executable), '--self-test'], env=environment, cwd=root,
                                    capture_output=True, check=True, timeout=180)
        if json.loads(diagnostic.stdout).get('status') != 'ok':
            raise ValueError('Executable self-test failed')
        synthesis = False
        if voice_id:
            if voice_root is None:
                raise ValueError('Explicit test voice root required')
            environment['CT_LOCAL_VOICE_ROOT'] = str(voice_root.resolve())
            response = messages(run(frame({'id': 2, 'type': 'preview-voice', 'voice_id': voice_id})).stdout)
            chunks = response[:-1]
            end = response[-1] if response else {}
            if (end.get('id') != 2 or end.get('type') != 'audio-end' or end.get('chunks') != len(chunks)
                    or any(item.get('id') != 2 or item.get('type') != 'audio-chunk' or item.get('index') != index for index, item in enumerate(chunks))):
                raise ValueError('Executable audio framing failed')
            audio = base64.b64decode(''.join(item['data'] for item in chunks), validate=True)
            if len(audio) != end.get('bytes'):
                raise ValueError('Executable audio size mismatch')
            with wave.open(io.BytesIO(audio), 'rb') as wav:
                synthesis = wav.getnchannels() == 1 and wav.getsampwidth() == 2 and any(wav.readframes(wav.getnframes()))
            if not synthesis:
                raise ValueError('Executable synthesis failed')
        return {'pyapp_executable_verified': True, 'first_boot_native_framing': True,
                'executable_sha256': manifest['pyapp_executable_sha256'],
                'fresh_extraction_directory': True, 'shared_distribution_cache_isolated': False,
                'empty_path': True, 'network_proxies_blocked': True, 'local_synthesis_verified': synthesis,
                'clean_windows_verified': False, 'chrome_native_registration_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prepared', type=Path)
    parser.add_argument('--voice-root', type=Path)
    parser.add_argument('--voice-id')
    args = parser.parse_args()
    report = smoke(args.prepared, args.voice_root, args.voice_id)
    (args.prepared/'pyapp-smoke.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
