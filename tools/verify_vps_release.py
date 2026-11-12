"""Read a verified upload into a new, bounded SaaS release; intended over SSH stdin."""

import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath


def verify(archive_path, expected, release_id, base=Path('/home/projects/call-translator-saas')):
    if not re.fullmatch('[a-f0-9]{64}', expected) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', release_id):
        raise ValueError('Invalid release metadata')
    archive_path=Path(archive_path).resolve()
    if not archive_path.is_relative_to((base/'incoming').resolve()):
        raise ValueError('Upload must be inside dedicated incoming directory')
    with archive_path.open('rb') as source:
        if hashlib.file_digest(source,'sha256').hexdigest()!=expected:
            raise ValueError('Uploaded archive integrity mismatch')
    release=base/'releases'/release_id
    if release.exists(): raise ValueError('Release already exists')
    with tarfile.open(archive_path) as archive:
        members=archive.getmembers()
        names=set()
        for member in members:
            path=PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or '..' in path.parts or '\\' in member.name
                    or ':' in member.name or member.name in names or member.size>100*1024*1024):
                raise ValueError('Unsafe archive member')
            names.add(member.name)
        manifest=json.load(archive.extractfile('release-manifest.json'))
        if manifest.get('schema')!=1 or names!={'release-manifest.json',*manifest['files']}:
            raise ValueError('Release inventory mismatch')
        for name,checksum in manifest['files'].items():
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest()!=checksum:
                raise ValueError('Release member integrity mismatch')
        release.mkdir(parents=True,mode=0o755)
        for member in members:
            destination=release/member.name
            destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open('xb') as target:
                target.write(archive.extractfile(member).read())
            destination.chmod(0o755 if member.name.endswith('.sh') else 0o644)
    return {'release_verified':True,'files':len(members)}


if __name__=='__main__':
    try: print(json.dumps(verify(*sys.argv[1:])))
    except Exception: raise SystemExit('Release verification failed; no sensitive details printed')
