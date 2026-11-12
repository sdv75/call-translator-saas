"""Prepare pinned, attributed candidates; publish only after real synthesis tests."""
import copy
import hashlib
import json
import re
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from local_component.call_translator_local.catalog import signed,verify
from tools.build_voice_catalog import ROOT,REPOSITORY,get

# One real speaker per offered language/gender; no guessed replacement genders.
PROFILES={
'bg':{'male':'bg_BG-dimitar-medium'},'bn':{'unspecified':'bn_BD-google-medium'},
'ca':{'female':'ca_ES-upc_ona-medium','male':'ca_ES-upc_pau-x_low'},
'cs':{'male':'cs_CZ-jirka-medium','female':'cs_CZ-kasandra-medium'},
'da':{'unspecified':'da_DK-talesyntese-medium'},
'de':{'male':'de_DE-thorsten-medium','female':'de_DE-kerstin-low'},
'el':{'female':'el_GR-rapunzelina-medium'},'es':{'male':'es_ES-davefx-medium','female':'es_AR-daniela-high'},
'fa':{'male':'fa_IR-amir-medium'},'fi':{'male':'fi_FI-harri-medium'},
'fr':{'female':'fr_FR-siwis-medium','male':'fr_FR-gilles-low'},
'hu':{'female':'hu_HU-anna-medium','male':'hu_HU-imre-medium'},'it':{'female':'it_IT-serena-medium'},
'kk':{'female':'kk_KZ-raya-x_low','male':'kk_KZ-iseke-x_low'},'lt':{'female':'lt_LT-reginute1-medium'},
'lv':{'male':'lv_LV-aivars-medium'},'mr':{'unspecified':'mr_IN-google-medium'},'ne':{'unspecified':'ne_NP-chitwan-medium'},
'nl':{'female':'nl_BE-nathalie-medium','male':'nl_NL-alex-medium'},'no':{'unspecified':'no_NO-talesyntese-medium'},
'pl':{'male':'pl_PL-darkman-medium','female':'pl_PL-gosia-medium'},'pt':{'male':'pt_BR-faber-medium'},
'ro':{'male':'ro_RO-mihai-medium'},'sk':{'female':'sk_SK-lili-medium'},'sl':{'male':'sl_SI-artur-medium'},
'sv':{'unspecified':'sv_SE-nst-medium'},'te':{'female':'te_IN-padmavathi-medium','male':'te_IN-venkatesh-medium'},
'vi':{'unspecified':'vi_VN-vais1000-medium'},'zh':{'unspecified':'zh_CN-chaowen-medium'}}


def main():
    index=json.loads(Path('build/library-voice-metadata.json').read_text(encoding='utf-8'))
    review=json.loads(Path('build/library-card-review.json').read_text(encoding='utf-8'))
    trust=json.loads((ROOT/'local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    payload=copy.deepcopy(verify((ROOT/'catalog/voices.signed.json').read_bytes(),trust))
    payload['revision']=5
    from local_component.call_translator_local.language_data import LANGUAGE_DATA
    for language,profiles in PROFILES.items():
        for gender,key in profiles.items():
            source=index[key];card=review['voices'][key]
            declaration=card['license'].lower()
            if card.get('requires_new_engine') or 'nc' in declaration or not any(term in declaration for term in ('cc0','cc-by','cc by','attribution','public domain','creativecommons.org/licenses/by/','creativecommons.org/licenses/by-sa/')):
                raise ValueError('Candidate requires further license/engine review: '+key)
            model=next(name for name in source['files'] if name.endswith('.onnx'))
            folder=model.rsplit('/',1)[0]
            pointer=get(f'{REPOSITORY}/raw/{review["revision"]}/{model}').decode('ascii')
            digest=re.search(r'^oid sha256:([a-f0-9]{64})$',pointer,re.M)
            size=re.search(r'^size (\d+)$',pointer,re.M)
            if not digest or not size:raise ValueError('Model pointer missing')
            config=get(f'{REPOSITORY}/resolve/{review["revision"]}/{model}.json')
            model_card=card['card'].encode('utf-8')
            files=[{'name':'model.onnx','url':f'{REPOSITORY}/resolve/{review["revision"]}/{model}','size':int(size[1]),'sha256':digest[1]}]
            for name,remote,data in [('config.json',model+'.json',config),('LICENSE.txt',folder+'/MODEL_CARD',model_card)]:
                files.append({'name':name,'url':f'{REPOSITORY}/resolve/{review["revision"]}/{remote}','size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            payload['voices'].append({'id':language+'-'+gender,'version':'1.0.0','language':language,
                'display_name':LANGUAGE_DATA[language]['label']+' — '+source['name'],'gender':gender,'speaker_id':0,
                'format':'onnx-v1','min_component':'0.1.2','license':card['license'].split('License:',1)[-1].strip(),
                'release_status':'technical_preview','files':files})
    key=Ed25519PrivateKey.from_private_bytes((ROOT/'.tools/voice-catalog-private.key').read_bytes())
    envelope=signed(payload,'voices-v1',key);verify(envelope,trust)
    Path('build/library-candidates.signed.json').write_bytes(envelope)
    print(json.dumps({'candidates':len(payload['voices'])-5,'legacy_voices_retained':5}))


if __name__=='__main__':main()
