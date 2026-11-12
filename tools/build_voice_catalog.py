"""Build and sign a technical preview catalog from pinned public metadata.

Private signing material stays in ignored .tools; only the public trust root
and signed public manifest are written to source directories. Never reuse OAuth
or provider credentials as signing keys.
"""

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.request import urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from local_component.call_translator_local.catalog import signed, validate

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://huggingface.co/rhasspy/piper-voices'


def get(url):
    with urlopen(url, timeout=30) as response:
        data = response.read(4*1024*1024+1)
    if len(data) > 4*1024*1024:
        raise ValueError('Unexpected metadata size')
    return data


def main():
    # A public-dataset declaration is retained as upstream metadata; the voice
    # remains technical_preview until a pilot/commercial release review.
    revision = json.loads(get('https://huggingface.co/api/models/rhasspy/piper-voices'))['sha']
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Invalid upstream revision')
    path = 'uk/uk_UA/ukrainian_tts/medium'
    model = 'uk_UA-ukrainian_tts-medium.onnx'
    pointer = get(f'{REPOSITORY}/raw/{revision}/{path}/{model}').decode('ascii')
    digest = re.search(r'^oid sha256:([a-f0-9]{64})$', pointer, re.M)
    size = re.search(r'^size (\d+)$', pointer, re.M)
    if digest is None or size is None:
        raise ValueError('Expected upstream LFS metadata')
    config = get(f'{REPOSITORY}/raw/{revision}/{path}/{model}.json')
    card = get(f'{REPOSITORY}/raw/{revision}/{path}/MODEL_CARD')
    if b'License: CC0' not in card:
        raise ValueError('Upstream license declaration changed; review required')
    files = [{'name': 'model.onnx', 'url': f'{REPOSITORY}/resolve/{revision}/{path}/{model}',
              'size': int(size[1]), 'sha256': digest[1]}]
    for name, remote, data in (('config.json', model+'.json', config), ('LICENSE.txt', 'MODEL_CARD', card)):
        files.append({'name': name, 'url': f'{REPOSITORY}/resolve/{revision}/{path}/{remote}',
                      'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    payload = {'schema': 1, 'revision': 1, 'voices': [{
        'id': 'uk-basic', 'version': '1.0.0', 'language': 'uk', 'display_name': 'Український — базовий',
        'gender': 'unspecified', 'speaker_id': 0, 'format': 'onnx-v1', 'min_component': '0.1.0',
        'license': 'CC0-1.0', 'release_status': 'technical_preview', 'files': files}]}
    key_path = ROOT/'.tools'/'voice-catalog-private.key'
    trust_path = ROOT/'local_component'/'call_translator_local'/'catalog-trust.json'
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.is_file():
        key = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
    else:
        if trust_path.exists():
            raise ValueError('Signing key missing; refusing silent trust rotation')
        key = Ed25519PrivateKey.generate()
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as target:
            target.write(key.private_bytes_raw())
    trust = {'keys': {'voices-v1': base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii')},
             'asset_origins': ['https://huggingface.co']}
    validate(payload, trust)
    if trust_path.exists() and json.loads(trust_path.read_text(encoding='utf-8')) != trust:
        raise ValueError('Existing public trust root differs')
    destination = ROOT/'catalog'/'voices.signed.json'
    envelope = signed(payload, 'voices-v1', key)
    if destination.is_file() and destination.read_bytes() != envelope:
        raise ValueError('Catalog changed; publish with a new revision rather than overwrite')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(envelope)
    trust_path.write_text(json.dumps(trust, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'signed_catalog': True, 'revision': 1, 'voices': 1,
                      'release_status': 'technical_preview', 'signing_key_printed': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Catalog preparation failed; review source metadata and signing setup locally')
