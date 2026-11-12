# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["piper-tts==1.8.0", "onnxruntime==1.31.1", "numpy>=1.26,<2", "pyinstaller==6.22.3", "num2words==0.5.14"]
# ///
"""Build a self-contained Windows Native Messaging installation package."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build on Windows.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    build = ROOT / 'build' / 'native-piper' / stamp
    package = ROOT / 'dist' / 'native-piper' / ('package-' + stamp)
    package.mkdir(parents=True)
    build.mkdir(parents=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--name', 'PiperHost', '--onedir', '--console',
        '--distpath', str(package), '--workpath', str(build / 'work'), '--specpath', str(build),
        '--collect-all', 'piper', '--collect-all', 'onnxruntime', '--collect-all', 'num2words',
        str(HERE / 'host.py')], check=True)
    voices = ['ru_RU-ruslan-medium', 'en_US-joe-medium', 'uk_UA-ukrainian_tts-medium']
    models = package / 'PiperHost' / 'models'
    models.mkdir()
    for voice in voices:
        for suffix in ('.onnx', '.onnx.json'):
            source = ROOT / 'models' / 'native-browser-comparison' / (voice + suffix)
            if not source.is_file():
                raise SystemExit('Run tools/benchmark-native-tts.py to download voices first.')
            shutil.copy2(source, models / source.name)
        card = ROOT / 'models/native-browser-comparison' / (voice + '-MODEL_CARD')
        if card.is_file():
            shutil.copy2(card, models / card.name)
    shutil.copy2(HERE / 'install.ps1', package / 'install.ps1')
    (package / 'Install.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"\r\npause\r\n', encoding='ascii')
    (package / 'extension-path.txt').write_text(str(ROOT / 'extension'), encoding='utf-8')
    shutil.copy2(HERE / 'README.ru.md', package / 'README.ru.md')
    subprocess.run([str(package / 'PiperHost' / 'PiperHost.exe'), '--self-test'], check=True)
    archive = shutil.make_archive(str(package), 'zip', package)
    manifest = {'package': str(package), 'archive': archive}
    (ROOT / 'dist' / 'native-piper' / 'latest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == '__main__':
    main()
