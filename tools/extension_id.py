"""Pin a new unpacked extension's public identity; never store a private key."""

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def extension_id(manifest: dict):
    public_key = base64.b64decode(manifest['key'], validate=True)
    serialization.load_der_public_key(public_key)
    return ''.join(chr(ord('a')+int(digit, 16)) for digit in hashlib.sha256(public_key).hexdigest()[:32])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init', action='store_true')
    parser.add_argument('--manifest', type=Path, default=Path('extension/manifest.json'))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if 'key' not in manifest:
        if not args.init:
            raise ValueError('Run once with --init to pin this new extension identity')
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        manifest['key'] = base64.b64encode(key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode('ascii')
        # Manifest key is PUBLIC identity metadata, not an authentication secret.
        args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(extension_id(manifest))


if __name__ == '__main__':
    main()
