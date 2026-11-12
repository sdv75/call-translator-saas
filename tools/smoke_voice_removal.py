"""Exercise compiled native removal using isolated hardlinks to build fixtures.

No AppData voices/registry are modified. Only temporary links in build are removed.
"""
import json
import argparse
import os
import subprocess
import tempfile
from pathlib import Path
from local_component.call_translator_local.voices import VoiceStore
from tools.smoke_pyapp import frame,messages


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepared',default='build/local-voices-runtime-05');args=parser.parse_args()
    prepared=Path(args.prepared).resolve()
    trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    original=VoiceStore(Path('build/local-voices'),trust)
    sources=[]
    with tempfile.TemporaryDirectory(dir=Path('build'),prefix='remove-test-') as temporary:
        root=Path(temporary).resolve()
        if not root.is_relative_to(Path('build').resolve()):raise ValueError('Unexpected temporary root')
        state={'revision':original.state()['revision'],'active':{},'selection':{'incoming':'ru-basic','outgoing':'en-male'}}
        for voice_id in ('ru-basic','en-male'):
            _,source=original.resolve(voice_id);sources.append(source)
            folder=root/source.name;folder.mkdir()
            for file in source.iterdir():os.link(file,folder/file.name)
            state['active'][voice_id]=folder.name
        VoiceStore(root,trust).write_state(state)
        env={key:value for key,value in os.environ.items() if key.upper() in ('SYSTEMROOT','WINDIR','TEMP','TMP','LOCALAPPDATA')}
        env.update(PATH='',PYTHONUTF8='1',CT_LOCAL_VOICE_ROOT=str(root),HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9')
        env['PYAPP_INSTALL_DIR_CALL-TRANSLATOR-LOCAL']=str(prepared/'removal-test-runtime')
        requests=[{'id':1,'type':'status'},{'id':2,'type':'begin-call','source':'ru','target':'en'},
                  {'id':3,'type':'remove-voice','voice_id':'en-male'},{'id':4,'type':'end-call'},
                  {'id':5,'type':'remove-voice','voice_id':'en-male'},{'id':6,'type':'status'}]
        result=subprocess.run([str(prepared/'CallTranslatorLocal.exe')],input=b''.join(map(frame,requests)),
                              stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,timeout=240)
        output={item['id']:item for item in messages(result.stdout)}
        report={'compiled_native':result.returncode==0,'capability_advertised':'remove-voice' in output[1].get('capabilities',[]),
                'active_call_protected':output[2].get('type')=='call-ready' and output[3].get('error')=='call_active',
                'voice_removed':output[5].get('type')=='voice-removed',
                'other_voice_preserved':[voice['id'] for voice in output[6]['voices']]==['ru-basic'],
                'selection_cleared':output[6]['selected']=={'incoming':'ru-basic'},
                'original_fixtures_preserved':all((source/'model.onnx').is_file() for source in sources)}
        if not all(report.values()):raise ValueError('Compiled removal regression failed')
    Path('build/native-removal-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
