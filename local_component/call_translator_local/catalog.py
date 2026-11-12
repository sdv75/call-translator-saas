"""Signed voice metadata. Trust roots ship with the component, never requests."""

import base64
import hashlib
import json
import re
from .language_data import LANGUAGE_DATA
from urllib.parse import urlsplit

DOMAIN = b'CALL-TRANSLATOR-VOICE-CATALOG-V1\x00'
ALLOWED_FILES = {'model.onnx', 'config.json', 'LICENSE.txt'}


class ComponentUpdateRequired(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate catalog property')
        result[key] = value
    return result


def decode_json(raw):
    if len(raw) > 1024*1024:
        raise ValueError('Catalog exceeds limit')
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))


def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def semver(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', value):
        raise ValueError('Invalid component version')
    return tuple(map(int, value.split('.')))


def validate(payload, trust):
    if not isinstance(payload, dict) or payload.get('schema') != 1 or type(payload.get('revision')) is not int or payload['revision'] < 1:
        raise ValueError('Unsupported catalog')
    voices = payload.get('voices')
    if not isinstance(voices, list) or len(voices) > 1000:
        raise ValueError('Invalid voice list')
    seen = set()
    for voice in voices:
        if not isinstance(voice, dict):
            raise ValueError('Invalid voice')
        voice_id = voice.get('id')
        if not isinstance(voice_id, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', voice_id) or voice_id in seen:
            raise ValueError('Invalid or duplicate voice ID')
        seen.add(voice_id)
        semver(voice.get('version'))
        semver(voice.get('min_component'))
        if voice.get('format') != 'onnx-v1' or voice.get('language') not in LANGUAGE_DATA:
            raise ValueError('Unsupported voice format or language')
        if voice.get('gender') not in ('female', 'male', 'unspecified'):
            raise ValueError('Invalid voice gender')
        for key in ('display_name', 'license'):
            if not isinstance(voice.get(key), str) or not 1 <= len(voice[key]) <= 200:
                raise ValueError('Voice metadata missing')
        if voice.get('release_status') not in ('technical_preview', 'pilot'):
            raise ValueError('Invalid release status')
        if type(voice.get('speaker_id', 0)) is not int or not 0 <= voice.get('speaker_id', 0) <= 1000:
            raise ValueError('Invalid speaker ID')
        files = voice.get('files')
        if not isinstance(files, list) or len(files) != 3 or {item.get('name') for item in files if isinstance(item, dict)} != ALLOWED_FILES:
            raise ValueError('Voice requires model, config and license')
        for item in files:
            if type(item.get('size')) is not int or not 1 <= item['size'] <= 256*1024*1024:
                raise ValueError('Invalid asset size')
            if not isinstance(item.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
                raise ValueError('Invalid asset digest')
            url = urlsplit(item.get('url', ''))
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or url.query:
                raise ValueError('Voice assets require fixed HTTPS URLs')
            if f'{url.scheme}://{url.netloc}' not in trust.get('asset_origins', []):
                raise ValueError('Untrusted asset origin')
    return payload


def verify(envelope_bytes, trust, *, minimum_revision=0):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    envelope = decode_json(envelope_bytes)
    if not isinstance(envelope, dict) or set(envelope) != {'key_id', 'payload', 'signature'}:
        raise ValueError('Invalid signed catalog envelope')
    public = trust['keys'].get(envelope['key_id'])
    if public is None:
        raise ValueError('Untrusted signing key')
    raw = base64.b64decode(envelope['payload'], validate=True)
    signature = base64.b64decode(envelope['signature'], validate=True)
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True)).verify(signature, DOMAIN+raw)
    payload = validate(decode_json(raw), trust)
    if canonical(payload) != raw or payload['revision'] < minimum_revision:
        raise ValueError('Noncanonical or rolled-back catalog')
    return payload


def signed(payload, key_id, private_key):
    raw = canonical(payload)
    return canonical({'key_id': key_id, 'payload': base64.b64encode(raw).decode('ascii'),
                      'signature': base64.b64encode(private_key.sign(DOMAIN+raw)).decode('ascii')})


def voice_digest(voice):
    return hashlib.sha256(canonical(voice)).hexdigest()
