"""Materialize locked local wheels/source packages, never copy an environment."""

import hashlib
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'.tools'/'local-dependencies'
OMIT_FILES = {
    'onnxruntime/datasets/logreg_iris.onnx', 'onnxruntime/datasets/mul_1.onnx',
    'onnxruntime/datasets/sigmoid.onnx', 'piper/hebrew/nakdimon.onnx', 'piper/tashkeel/model.onnx',
}


def inventory(requirements):
    files = {}
    for path in OUTPUT.rglob('*'):
        name = path.relative_to(OUTPUT).as_posix()
        if path.is_file() and name != 'dependencies-manifest.json' and name not in OMIT_FILES:
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'schema': 1, 'python_version': '3.11.9',
                'requirements_sha256': hashlib.sha256(requirements.read_bytes()).hexdigest(), 'files': files,
                'excluded_optional_files': sorted(OMIT_FILES),
                'exclusion_reason': 'Example models and Arabic/Hebrew normalization are outside en/ru/uk support'}
    (OUTPUT/'dependencies-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory-only', action='store_true')
    args = parser.parse_args()
    requirements = ROOT/'build'/'local-requirements.txt'
    if args.inventory_only:
        count = inventory(requirements)
        print(json.dumps({'inventory_refreshed': True, 'files': count}))
        return
    if OUTPUT.exists():
        raise ValueError('Dependency output already exists; retain or explicitly choose a clean build')
    requirements.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['uv', 'export', '--frozen', '--only-group', 'local', '--no-emit-project',
                    '--format', 'requirements-txt', '--output-file', str(requirements)],
                   cwd=ROOT, check=True, capture_output=True)
    subprocess.run(['uv', 'pip', 'install', '--require-hashes', '--no-deps', '--python-version', '3.11',
                    '--target', str(OUTPUT), '--requirements', str(requirements)],
                   cwd=ROOT, check=True, capture_output=True)
    count = inventory(requirements)
    print(json.dumps({'local_dependencies_prepared': True, 'files': count, 'source': 'uv-lock-not-existing-environment'}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Local dependency preparation failed; no credentials or subprocess output printed')
