"""Download and synthesize candidates in separate build stores/processes."""
import concurrent.futures
import json
import time
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from local_component.call_translator_local.catalog import signed,verify
from local_component.call_translator_local.engine import Engine
from local_component.call_translator_local.voices import VoiceStore
from local_component.call_translator_local.language_data import voice_test_text


def check(voice_id):
    root=Path('build/library-validation')/voice_id
    trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    engine=Engine();start=time.monotonic()
    try:
        store=VoiceStore(root,trust)
        voice=store.install(Path('build/library-candidates.signed.json').read_bytes(),voice_id,engine.smoke)
        _,folder=store.resolve(voice_id)
        (root/'sample.wav').write_bytes(engine.render(voice,folder,voice_test_text(voice['language'])))
        return {'id':voice_id,'language':voice['language'],'ok':True,'seconds':round(time.monotonic()-start,2)}
    except Exception as exc:
        return {'id':voice_id,'ok':False,'error_type':type(exc).__name__}
    finally:engine.close()


def main():
    trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    payload=verify(Path('build/library-candidates.signed.json').read_bytes(),trust)
    candidates=[voice['id'] for voice in payload['voices'] if voice['min_component']=='0.1.2']
    reports=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
        for result in pool.map(check,candidates):
            reports.append(result);print(json.dumps(result),flush=True)
    passed={report['id'] for report in reports if report['ok']}
    payload['voices']=[voice for voice in payload['voices'] if voice['id'] not in candidates or voice['id'] in passed]
    payload['revision']=6
    key=Ed25519PrivateKey.from_private_bytes(Path('.tools/voice-catalog-private.key').read_bytes())
    envelope=signed(payload,'voices-v1',key);verify(envelope,trust)
    Path('catalog/voices.all.signed.json').write_bytes(envelope)
    Path('build/library-validation-report.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps({'published_to_checkout':True,'voices':len(payload['voices']),'languages':len({v['language'] for v in payload['voices']}),'failed':len(reports)-len(passed)}))


if __name__=='__main__':main()
