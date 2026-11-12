"""Versioned voice activation only after signature, hashes and real synthesis."""

import json
import hashlib
import os
import shutil
import stat
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .catalog import ComponentUpdateRequired, canonical, semver, verify, voice_digest
from .download import digest_file, download
from .locking import Lease


def default_root():
    if os.environ.get('CT_LOCAL_VOICE_ROOT'):
        return Path(os.environ['CT_LOCAL_VOICE_ROOT'])
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.local/share')))/'CallTranslatorSaaS'/'voices'


class VoiceStore:
    def __init__(self, root: Path, trust: dict):
        self.root = Path(root)
        self.trust = trust

    def state(self):
        path = self.root/'active.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'revision': 0, 'active': {}, 'selection': {}}

    def write_state(self, state):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root/'active.json.tmp'
        with temporary.open('wb') as target:
            target.write(canonical(state))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, self.root/'active.json')

    @contextmanager
    def mutation(self):
        with self.call_lease(), Lease(self.root/'update.lock'):
            yield

    def call_lease(self):
        return Lease(self.root/'call.lock')

    def install(self, envelope: bytes, voice_id: str, smoke, *, fetch=download):
        with self.mutation():
            return self._install(envelope, voice_id, smoke, fetch)

    def _install(self, envelope, voice_id, smoke, fetch):
        state = self.state()
        catalog = verify(envelope, self.trust, minimum_revision=state['revision'])
        catalog_hash = hashlib.sha256(canonical(catalog)).hexdigest()
        if catalog['revision'] == state['revision'] and state.get('catalog_hash') not in (None, catalog_hash):
            raise ValueError('Catalog revision must identify immutable content')
        voice = next((item for item in catalog['voices'] if item['id'] == voice_id), None)
        if voice is None:
            raise ValueError('Voice not in signed catalog')
        if semver(voice['min_component']) > semver(__version__):
            raise ComponentUpdateRequired('Local component update required')
        folder_name = f"{voice['id']}-{voice['version']}-{voice_digest(voice)[:16]}"
        folder = self.root/folder_name
        folder.mkdir(parents=True, exist_ok=True)
        for asset in voice['files']:
            fetch(asset, folder/asset['name'])
            path = folder/asset['name']
            if path.stat().st_size != asset['size'] or digest_file(path) != asset['sha256']:
                raise ValueError('Downloaded voice integrity check failed')
        # The original signed envelope is retained, allowing verification again
        # on later process starts. A power loss before activation leaves the old
        # active voice untouched; downloaded partial files are reused next time.
        (folder/'catalog.signed.json').write_bytes(envelope)
        smoke(voice, folder)
        state['revision'] = catalog['revision']
        state['catalog_hash'] = catalog_hash
        state['active'][voice_id] = folder_name
        self.write_state(state)
        return voice

    def installed(self):
        result = []
        for voice_id in self.state()['active']:
            try:
                voice, _ = self.resolve(voice_id)
                result.append(voice)
            except Exception:
                # Corruption disables only this voice, never another active one.
                continue
        return result

    def resolve(self, voice_id):
        folder_name = self.state()['active'].get(voice_id)
        if not isinstance(folder_name, str) or Path(folder_name).name != folder_name or '/' in folder_name or '\\' in folder_name:
            raise ValueError('Voice not installed')
        folder = self.root/folder_name
        payload = verify((folder/'catalog.signed.json').read_bytes(), self.trust)
        voice = next((item for item in payload['voices'] if item['id'] == voice_id), None)
        if voice is None or folder_name != f"{voice_id}-{voice['version']}-{voice_digest(voice)[:16]}":
            raise ValueError('Installed voice metadata mismatch')
        if semver(voice['min_component']) > semver(__version__):
            raise ComponentUpdateRequired('Local component update required')
        for asset in voice['files']:
            path = folder/asset['name']
            if not path.is_file() or path.stat().st_size != asset['size'] or digest_file(path) != asset['sha256']:
                raise ValueError('Installed voice integrity check failed')
        return voice, folder

    def select(self, direction, voice_id):
        if direction not in ('incoming', 'outgoing'):
            raise ValueError('Unknown direction')
        with self.mutation():
            self.resolve(voice_id)
            state = self.state()
            state['selection'][direction] = voice_id
            self.write_state(state)

    def selected(self, direction):
        voice_id = self.state()['selection'].get(direction)
        return self.resolve(voice_id) if voice_id else None

    def remove(self, voice_id):
        with self.mutation():
            state=self.state()
            name=state['active'].get(voice_id)
            if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name:
                raise ValueError('Voice not installed')
            folder=self.root/name
            root=self.root.resolve()
            if folder.is_symlink() or folder.resolve()==root or not folder.resolve().is_relative_to(root):
                raise ValueError('Unsafe voice folder')
            payload=verify((folder/'catalog.signed.json').read_bytes(),self.trust)
            voice=next((item for item in payload['voices'] if item['id']==voice_id),None)
            if voice is None or name!=f"{voice_id}-{voice['version']}-{voice_digest(voice)[:16]}":
                raise ValueError('Voice metadata mismatch')
            allowed={asset['name'] for asset in voice['files']}|{'catalog.signed.json'}
            for path in (folder,*folder.iterdir()):
                if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0):
                    raise ValueError('Refusing voice links')
                if path!=folder and (path.name not in allowed or not path.is_file()):
                    raise ValueError('Unexpected voice files')
            # Persist deactivation first: interrupted file cleanup can leave data,
            # but cannot leave a selected voice pointing at deleted model files.
            del state['active'][voice_id]
            state['selection']={key:value for key,value in state['selection'].items() if value!=voice_id}
            self.write_state(state)
            shutil.rmtree(folder)
