"""Add compatible male choices; retain existing trust and pinned model revision."""
import copy
import hashlib
import json
import os
import re
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from local_component.call_translator_local.catalog import signed,validate,verify
from tools.build_voice_catalog import ROOT,REPOSITORY,get


def main():
    trust=json.loads((ROOT/'local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    destination=ROOT/'catalog/voices.signed.json'
    payload=verify(destination.read_bytes(),trust)
    if {'en-male','uk-male'}.issubset({voice['id'] for voice in payload['voices']}):
        print(json.dumps({'catalog_unchanged':True,'voices':len(payload['voices'])}));return
    uk=next(voice for voice in payload['voices'] if voice['id']=='uk-basic')
    config=json.loads(get(next(asset['url'] for asset in uk['files'] if asset['name']=='config.json')))
    if config.get('speaker_id_map',{}).get('mykyta')!=1 or config['speaker_id_map'].get('lada')!=0:
        raise ValueError('Ukrainian speaker mapping changed')
    male=copy.deepcopy(uk)
    male.update(id='uk-male',display_name='Українська — чоловічий',gender='male',speaker_id=1)
    payload['voices'].append(male)
    uk.update(gender='female',display_name='Українська — жіночий')
    next(voice for voice in payload['voices'] if voice['id']=='ru-basic')['gender']='male'
    en=next(voice for voice in payload['voices'] if voice['id']=='en-basic')
    revision=re.search('/resolve/([a-f0-9]{40})/',en['files'][0]['url'])[1]
    folder='en/en_US/joe/medium';model='en_US-joe-medium.onnx'
    pointer=get(f'{REPOSITORY}/raw/{revision}/{folder}/{model}').decode('ascii')
    digest=re.search(r'^oid sha256:([a-f0-9]{64})$',pointer,re.M)
    size=re.search(r'^size (\d+)$',pointer,re.M)
    if not digest or not size:raise ValueError('Invalid model metadata')
    config=get(f'{REPOSITORY}/raw/{revision}/{folder}/{model}.json')
    card=get(f'{REPOSITORY}/raw/{revision}/{folder}/MODEL_CARD')
    if b'License: CC0' not in card:raise ValueError('Voice declaration changed')
    files=[{'name':'model.onnx','url':f'{REPOSITORY}/resolve/{revision}/{folder}/{model}','size':int(size[1]),'sha256':digest[1]}]
    for name,remote,data in [('config.json',model+'.json',config),('LICENSE.txt','MODEL_CARD',card)]:
        files.append({'name':name,'url':f'{REPOSITORY}/resolve/{revision}/{folder}/{remote}','size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    payload['voices'].append({'id':'en-male','version':'1.0.0','language':'en','display_name':'English — US (мужской)',
        'gender':'male','speaker_id':0,'format':'onnx-v1','min_component':'0.1.0','license':'CC0-1.0','release_status':'technical_preview','files':files})
    payload['revision']+=1;validate(payload,trust)
    key=Ed25519PrivateKey.from_private_bytes((ROOT/'.tools/voice-catalog-private.key').read_bytes())
    envelope=signed(payload,'voices-v1',key);verify(envelope,trust)
    temporary=destination.with_suffix('.tmp');temporary.write_bytes(envelope);os.replace(temporary,destination)
    print(json.dumps({'catalog_revision':payload['revision'],'voices':len(payload['voices'])}))


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Voice preparation failed; signing material suppressed')
