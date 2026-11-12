"""Append a signed English technical candidate without changing the trust root."""

import hashlib
import json
import os
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from local_component.call_translator_local.catalog import signed, validate, verify
from tools.build_voice_catalog import ROOT, REPOSITORY, get


def main():
    trust=json.loads((ROOT/'local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    destination=ROOT/'catalog/voices.signed.json'
    payload=verify(destination.read_bytes(),trust)
    if any(voice['id']=='en-basic' for voice in payload['voices']):
        print(json.dumps({'catalog_unchanged':True,'voices':len(payload['voices'])}));return
    revision=json.loads(get('https://huggingface.co/api/models/rhasspy/piper-voices'))['sha']
    if not re.fullmatch('[0-9a-f]{40}',revision): raise ValueError('Invalid upstream revision')
    path='en/en_US/ljspeech/high'; model='en_US-ljspeech-high.onnx'
    pointer=get(f'{REPOSITORY}/raw/{revision}/{path}/{model}').decode('ascii')
    digest=re.search(r'^oid sha256:([a-f0-9]{64})$',pointer,re.M)
    size=re.search(r'^size (\d+)$',pointer,re.M)
    if not digest or not size: raise ValueError('Unexpected model metadata')
    config=get(f'{REPOSITORY}/raw/{revision}/{path}/{model}.json')
    card=get(f'{REPOSITORY}/raw/{revision}/{path}/MODEL_CARD')
    if b'License: public domain' not in card: raise ValueError('Upstream license declaration changed')
    files=[{'name':'model.onnx','url':f'{REPOSITORY}/resolve/{revision}/{path}/{model}',
            'size':int(size[1]),'sha256':digest[1]}]
    for name,remote,data in [('config.json',model+'.json',config),('LICENSE.txt','MODEL_CARD',card)]:
        files.append({'name':name,'url':f'{REPOSITORY}/resolve/{revision}/{path}/{remote}',
                      'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    payload['voices'].append({'id':'en-basic','version':'1.0.0','language':'en','display_name':'English — US',
        'gender':'female','speaker_id':0,'format':'onnx-v1','min_component':'0.1.0',
        'license':'Public-Domain','release_status':'technical_preview','files':files})
    payload['revision']+=1
    validate(payload,trust)
    key=Ed25519PrivateKey.from_private_bytes((ROOT/'.tools/voice-catalog-private.key').read_bytes())
    envelope=signed(payload,'voices-v1',key)
    verify(envelope,trust)
    temporary=destination.with_suffix('.tmp')
    temporary.write_bytes(envelope);os.replace(temporary,destination)
    print(json.dumps({'catalog_revision':payload['revision'],'voices':len(payload['voices']),'release_status':'technical_preview'}))


if __name__=='__main__':
    try: main()
    except Exception: raise SystemExit('English candidate preparation failed; no signing material printed')
