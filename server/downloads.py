"""Only the operator's verified Windows installer can be served."""

import hashlib
import json
import re


def verified_installer(folder):
    if folder is None:
        return None
    executable = folder/'CallTranslatorSetup.exe'
    manifest = json.loads((folder/'installer-manifest.json').read_text(encoding='utf-8-sig'))
    expected = manifest.get('installer_sha256', '')
    if manifest.get('installer_compiled') is not True or not re.fullmatch('[a-f0-9]{64}', expected):
        raise ValueError('Unverified installer metadata')
    with executable.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
            raise ValueError('Installer SHA-256 mismatch')
    return executable
