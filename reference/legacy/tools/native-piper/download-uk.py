"""Download and verify the Ukrainian voice against the publisher's manifest."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/'
VOICE = 'uk_UA-ukrainian_tts-medium'


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url,
        headers={'User-Agent': 'CallTranslator/0.4.1'}), timeout=120)


def main():
    with fetch(BASE + 'voices.json') as response:
        metadata = json.load(response)[VOICE]
    target_dir = ROOT / 'models/native-browser-comparison'
    target_dir.mkdir(parents=True, exist_ok=True)
    for relative, info in metadata['files'].items():
        if not relative.endswith(('.onnx', '.onnx.json')):
            continue
        target = target_dir / Path(relative).name
        if target.is_file() and hashlib.md5(target.read_bytes()).hexdigest() == info['md5_digest']:
            print(target.name + ': verified cached file', flush=True)
            continue
        temporary = target.with_suffix(target.suffix + '.part')
        digest = hashlib.md5()
        with fetch(BASE + relative) as response, temporary.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk); digest.update(chunk)
        if temporary.stat().st_size != info['size_bytes'] or digest.hexdigest() != info['md5_digest']:
            raise RuntimeError('Voice download checksum mismatch')
        temporary.replace(target)
        print(target.name + ': downloaded and verified', flush=True)
    with fetch(BASE + 'uk/uk_UA/ukrainian_tts/medium/MODEL_CARD') as response:
        (target_dir / (VOICE + '-MODEL_CARD')).write_bytes(response.read())


if __name__ == '__main__':
    main()
