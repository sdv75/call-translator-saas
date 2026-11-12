"""Retain original available Rust dependency notices alongside PyApp's notice.

This is an inventory aid, not a declaration of completed release compliance.
"""

import argparse
import json
import tomllib
from pathlib import Path


def collect(cargo_lock, registry, pyapp_license, output):
    if output.exists():
        raise ValueError('Use a new notices output file')
    packages = tomllib.loads(cargo_lock.read_text(encoding='utf-8'))['package']
    text = [pyapp_license.read_text(encoding='utf-8-sig')]
    included, unavailable, fallback = [], [], []
    for package in packages:
        if not package.get('source', '').startswith('registry+'):
            continue
        identity = package['name']+'-'+package['version']
        folder = registry/identity
        if not folder.is_dir():
            unavailable.append(identity)
            continue
        metadata = tomllib.loads((folder/'Cargo.toml').read_text(encoding='utf-8'))['package']
        files = [file for file in folder.rglob('*') if file.is_file() and not file.is_symlink()
                 and file.name.lower().startswith(('license', 'copying', 'notice'))]
        text.append('\n\n===== '+identity+'; license: '+metadata.get('license', 'see original source')+' =====\n')
        if not files:
            files = [file for file in folder.iterdir() if file.is_file() and file.name.lower().startswith('readme')]
            fallback.append(identity)
        for file in sorted(files):
            if not file.resolve().is_relative_to(registry.resolve()) or file.stat().st_size > 1024*1024:
                raise ValueError('Unexpected dependency notice asset')
            text.append('\n--- '+file.relative_to(folder).as_posix()+' ---\n'+file.read_text(encoding='utf-8-sig'))
        included.append(identity)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(text), encoding='utf-8')
    report = {'packages_with_retained_notices': len(included), 'readme_fallback': fallback,
              'lock_entries_not_downloaded': unavailable, 'release_compliance_verified': False}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo-lock', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--pyapp-license', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.cargo_lock, args.registry, args.pyapp_license, args.output), indent=2))


if __name__ == '__main__':
    main()
