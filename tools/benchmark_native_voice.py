"""Compare compiled native hosts with synthetic speech in isolated build stores."""
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from local_component.call_translator_local.__main__ import read_message,write_message
from local_component.call_translator_local.voices import VoiceStore


def request(process,command):
    began=time.perf_counter();write_message(process.stdin,command);process.stdin.flush()
    while True:
        message=read_message(process.stdout)
        if not message or 'error' in message:raise ValueError('Native benchmark command failed')
        if message.get('type')!='audio-chunk':return message,(time.perf_counter()-began)*1000


def main():
    trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text())
    original=VoiceStore(Path('build/local-voices'),trust);processes=[]
    with tempfile.TemporaryDirectory(dir='build',prefix='native-latency-') as temporary:
        temporary=Path(temporary).resolve()
        try:
            for label,prepared in [('before','build/local-voices-runtime-06'),('after','build/local-voices-runtime-07')]:
                root=temporary/label/'voices';root.mkdir(parents=True)
                state={'revision':original.state()['revision'],'active':{},'selection':{'incoming':'ru-basic','outgoing':'en-male'}}
                for voice_id in ('ru-basic','en-male'):
                    _,source=original.resolve(voice_id);folder=root/source.name;folder.mkdir()
                    for file in source.iterdir():os.link(file,folder/file.name)
                    state['active'][voice_id]=folder.name
                VoiceStore(root,trust).write_state(state)
                env=dict(os.environ);env.update(CT_LOCAL_VOICE_ROOT=str(root),HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9')
                env['PYAPP_INSTALL_DIR_CALL-TRANSLATOR-LOCAL']=str(temporary/label/'runtime')
                process=subprocess.Popen([str(Path(prepared,'CallTranslatorLocal.exe').resolve())],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                processes.append((label,process))
                reply,_=request(process,{'id':1,'type':'begin-call','source':'ru','target':'en'})
                if reply.get('type')!='call-ready':raise ValueError('Call not warmed')
            results={label:{'incoming':[],'outgoing':[]} for label,_ in processes}
            sequence=2
            for repeat in range(7):
                for direction,text in [('incoming','Это проверка скорости перевода. Последняя фраза должна сохраниться.'),('outgoing','This is a translation speed test. The final phrase must be preserved.')]:
                    for label,process in processes:
                        reply,elapsed=request(process,{'id':sequence,'type':'synthesize','direction':direction,'text':text});sequence+=1
                        if reply.get('type')!='audio-end' or not reply.get('bytes'):raise ValueError('Audio missing')
                        results[label][direction].append(round(elapsed,1))
            # Real new compiled host also writes an isolated custom transcript.
            root=temporary/'custom'/'Call_Translator_Stennograms';root.mkdir(parents=True)
            (temporary/'after'/'transcript-folder.json').write_text(json.dumps({'custom':str(root)}))
            after=processes[1][1]
            html='<!doctype html><html><style>body{font:16px sans-serif}</style><p>Проверка</p></html>'
            reply,_=request(after,{'id':sequence,'type':'transcript-write','day':'2026-11-12','filename':'CallTranslator_synthetic.html','html':html})
            if (root/'2026-11-12/CallTranslator_synthetic.html').read_text(encoding='utf-8')!=html:raise ValueError('Compiled file write failed')
            summary={direction:{label:round(statistics.median(results[label][direction]),1) for label in results} for direction in ('incoming','outgoing')}
            report={'compiled_native':True,'synthetic_only':True,'repeats_per_direction':7,'elapsed_median_ms':summary,'samples_ms':results,
                    'compiled_transcript_write_verified':True,'end_to_end_meet_verified':False}
            Path('build/native-latency-benchmark.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
        finally:
            for _,process in processes:
                process.stdin.close()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
