"""Create an offline-ready PyApp distribution from a pinned Windows runtime ZIP.

Run Python only through uv. No code, settings, voices or artifacts are read from
the personal project. Input hash must be obtained from a trusted build manifest.
"""

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from local_component.call_translator_local import __version__

PYAPP_VERSION = '0.30.0'
PYTHON_VERSION = '3.11.9'
ROOT = Path(__file__).resolve().parents[1]


def prepare(runtime: Path, expected_sha256: str, output: Path, dependencies: Path | None = None):
    actual = hashlib.sha256(runtime.read_bytes()).hexdigest()
    if actual != expected_sha256.lower():
        raise ValueError('Runtime SHA-256 mismatch')
    if output.exists():
        raise ValueError('Output already exists; use a new build directory')
    dependency_files = {}
    if dependencies is not None:
        dependency_manifest = json.loads((dependencies/'dependencies-manifest.json').read_text(encoding='utf-8'))
        if dependency_manifest.get('schema') != 1 or dependency_manifest.get('python_version') != PYTHON_VERSION:
            raise ValueError('Incompatible dependency inventory')
        dependency_files = dependency_manifest['files']
        for name, checksum in dependency_files.items():
            parts = PurePosixPath(name)
            if parts.is_absolute() or '..' in parts.parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe dependency archive member')
            file = dependencies/name
            if not file.resolve().is_relative_to(dependencies.resolve()) or not file.is_file():
                raise ValueError('Unsafe dependency path')
            if file.name in ('.env', 'connection.json') or file.suffix in ('.key', '.pem', '.onnx'):
                raise ValueError('Non-dependency asset in runtime inventory')
            if hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
                raise ValueError('Dependency digest mismatch')
    with zipfile.ZipFile(runtime) as source:
        names = source.namelist()
        if not {'python.exe', 'python311.dll', 'python311.zip', 'python311._pth', 'LICENSE.txt'} <= set(names):
            raise ValueError('Expected official Windows Python 3.11 embeddable ZIP')
        if sum(info.file_size for info in source.infolist()) > 100*1024*1024:
            raise ValueError('Unexpected runtime size')
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe runtime member')
        output.mkdir(parents=True)
        distribution = output/'runtime.zip'
        with zipfile.ZipFile(distribution, 'w', zipfile.ZIP_DEFLATED) as target:
            for name in names:
                data = source.read(name)
                if name == 'python311._pth':
                    # Native host imports from the embedded distribution without
                    # pip, uv, a virtualenv, or user-installed Python.
                    data = b'python311.zip\n.\nLib/site-packages\n'
                target.writestr(name, data)
            package = ROOT/'local_component'/'call_translator_local'
            for file in sorted(package.glob('*.py')):
                target.write(file, 'Lib/site-packages/call_translator_local/'+file.name)
            for name in ('catalog-trust.json','languages.json'):
                file=package/name
                if file.is_file():target.write(file,'Lib/site-packages/call_translator_local/'+name)
            for name in sorted(dependency_files):
                target.write(dependencies/name, 'Lib/site-packages/'+name)
    settings = {
        'PYAPP_PROJECT_NAME': 'call-translator-local', 'PYAPP_PROJECT_VERSION': __version__,
        'PYAPP_PYTHON_VERSION': '3.11', 'PYAPP_DISTRIBUTION_PATH': str(distribution.resolve()),
        'PYAPP_DISTRIBUTION_FORMAT': 'zip', 'PYAPP_DISTRIBUTION_PYTHON_PATH': 'python.exe',
        'PYAPP_DISTRIBUTION_SITE_PACKAGES_PATH': 'Lib/site-packages',
        'PYAPP_DISTRIBUTION_EMBED': '1', 'PYAPP_FULL_ISOLATION': '1',
        'PYAPP_SKIP_INSTALL': '1', 'PYAPP_EXEC_MODULE': 'call_translator_local',
        'PYAPP_IS_GUI': '0',
    }
    manifest = {'pyapp_version': PYAPP_VERSION, 'python_version': PYTHON_VERSION,
                'source_runtime_sha256': actual,
                'prepared_runtime_sha256': hashlib.sha256(distribution.read_bytes()).hexdigest(),
                'environment': settings, 'build_verified': False, 'clean_windows_verified': False}
    manifest['local_dependency_files'] = len(dependency_files)
    (output/'build-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path)
    args = parser.parse_args()
    manifest = prepare(args.runtime, args.sha256, args.output, args.dependencies)
    print(json.dumps({'prepared': True, 'pyapp_version': manifest['pyapp_version'],
                      'cargo_available': bool(shutil.which('cargo')),
                      'inno_setup_available': bool(shutil.which('ISCC')),
                      'build_verified': False, 'clean_windows_verified': False}))


if __name__ == '__main__':
    main()
