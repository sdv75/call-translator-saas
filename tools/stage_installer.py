"""Stage only this project's validated PyApp binary, extension and licenses."""

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from tools.extension_id import extension_id as manifest_extension_id

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_FILES = ('manifest.json', 'service-config.js', 'language-library.js','voice-setup.js', 'protocol.js', 'native-client.js', 'background.js', 'popup.html', 'popup.css', 'popup.js',
                   'audio-protocol.js','journal.js','transcript-files.js','call-controller.js','pcm.js','pcm-worklet.js','meet.js','translate.js','bridge.js',
                   'offscreen.html','offscreen.js','conversation.html','conversation.js','conversation-window.js','transcript.html','transcript.js','transcript.css','transcript-format.js','licenses/legacy-MIT.txt')


def stage(prepared: Path, extension_id: str, pyapp_license: Path, output: Path):
    if not re.fullmatch('[a-p]{32}', extension_id):
        raise ValueError('Exact Chrome extension ID required; wildcards are forbidden')
    if manifest_extension_id(json.loads((ROOT/'extension/manifest.json').read_text(encoding='utf-8'))) != extension_id:
        raise ValueError('Extension ID does not match its pinned public manifest key')
    manifest = json.loads((prepared/'build-manifest.json').read_text(encoding='utf-8-sig'))
    executable = prepared/'CallTranslatorLocal.exe'
    if not manifest.get('build_verified') or not executable.is_file():
        raise ValueError('A successfully built and tested PyApp executable is required')
    if hashlib.sha256(executable.read_bytes()).hexdigest() != manifest.get('pyapp_executable_sha256'):
        raise ValueError('PyApp executable integrity check failed')
    smoke = json.loads((prepared/'pyapp-smoke.json').read_text(encoding='utf-8'))
    if (smoke.get('pyapp_executable_verified') is not True or smoke.get('first_boot_native_framing') is not True
            or smoke.get('executable_sha256') != manifest['pyapp_executable_sha256']):
        raise ValueError('Matching first-boot Native Messaging verification required')
    if output.exists():
        raise ValueError('Use a new staging directory')
    license_text = pyapp_license.read_text(encoding='utf-8')
    if not license_text.strip():
        raise ValueError('PyApp license must be retained')
    runtime = prepared/'runtime.zip'
    if hashlib.sha256(runtime.read_bytes()).hexdigest() != manifest['prepared_runtime_sha256']:
        raise ValueError('Prepared runtime integrity check failed')
    with zipfile.ZipFile(runtime) as archive:
        python_license = archive.read('LICENSE.txt')
    output.mkdir(parents=True)
    (output/'extension').mkdir()
    (output/'licenses').mkdir()
    shutil.copyfile(executable, output/'CallTranslatorLocal.exe')
    for name in EXTENSION_FILES:
        (output/'extension'/name).parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'extension'/name, output/'extension'/name)
    (output/'licenses'/'Python-LICENSE.txt').write_bytes(python_license)
    (output/'licenses'/'PyApp-LICENSE.txt').write_text(license_text, encoding='utf-8')
    # Keep dependency license/copyright notices readable outside the embedded exe.
    with zipfile.ZipFile(runtime) as archive:
        for name in archive.namelist():
            relative = PurePosixPath(name)
            if not name.startswith('Lib/site-packages/') or not any(
                    word in relative.name.lower() for word in ('license', 'copying', 'notice')):
                continue
            if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe license path in runtime')
            if archive.getinfo(name).is_dir():
                continue
            destination = output/'licenses'/'python'/Path(*relative.parts[2:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
    host = {'name': 'org.call_translator.saas.local', 'description': 'Call Translator local component',
            'path': 'CallTranslatorLocal.exe', 'type': 'stdio',
            'allowed_origins': [f'chrome-extension://{extension_id}/']}
    (output/'native-host.json').write_text(json.dumps(host, indent=2)+'\n', encoding='utf-8')
    shutil.copyfile(ROOT/'installer/INSTALL.html', output/'INSTALL.html')
    return {'staged': True, 'installer_compiled': False, 'clean_windows_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--extension-id', required=True)
    parser.add_argument('--pyapp-license', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.prepared, args.extension_id, args.pyapp_license, args.output)))


if __name__ == '__main__':
    main()
