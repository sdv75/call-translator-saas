"""Create a source/installer allowlist archive; never include .env or local data."""

import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stage(installer_stage, output):
    if output.exists():
        raise ValueError('Use a new deployment archive')
    manifest = json.loads((installer_stage/'installer-manifest.json').read_text(encoding='utf-8-sig'))
    installer = installer_stage/'installer-output/CallTranslatorSetup.exe'
    if manifest.get('installer_compiled') is not True or hashlib.sha256(installer.read_bytes()).hexdigest() != manifest.get('installer_sha256'):
        raise ValueError('Verified compiled installer required')
    files = {name: ROOT/name for name in ('pyproject.toml', 'uv.lock', '.python-version',
        'local_component/call_translator_local/__init__.py', 'local_component/call_translator_local/catalog.py',
        'local_component/call_translator_local/language_data.py','local_component/call_translator_local/languages.json',
        'local_component/call_translator_local/catalog-trust.json', 'catalog/voices.signed.json','catalog/voices.all.signed.json',
        'deploy/call-translator-saas.service', 'deploy/nginx.ssl.conf_call-translator-saas', 'deploy/install-release.sh')}
    for file in (ROOT/'server').rglob('*'):
        if file.is_file() and file.suffix in ('.py', '.css', '.js'):
            files[file.relative_to(ROOT).as_posix()] = file
    files.update({'downloads/CallTranslatorSetup.exe': installer,
                  'downloads/installer-manifest.json': installer_stage/'installer-manifest.json'})
    output.parent.mkdir(parents=True, exist_ok=True)
    checksums = {}
    with tarfile.open(output, 'w:gz') as archive:
        for name, file in sorted(files.items()):
            if not file.resolve().is_relative_to(ROOT) or file.is_symlink():
                raise ValueError('Deployment inputs must belong to this project')
            data = file.read_bytes()
            checksums[name] = hashlib.sha256(data).hexdigest()
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = 0o755 if name.endswith('.sh') else 0o644
            archive.addfile(item, io.BytesIO(data))
        data = (json.dumps({'schema': 1, 'files': checksums}, indent=2)+'\n').encode()
        item = tarfile.TarInfo('release-manifest.json'); item.size = len(data); item.mode = 0o644
        archive.addfile(item, io.BytesIO(data))
    return {'archive_created': True, 'files': len(files), 'secrets_included': False,
            'archive_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'deployed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer-stage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = stage(args.installer_stage, args.output)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
