"""Validate both installed voices and the native call lease without network."""
import json
import argparse
import time
from pathlib import Path
from local_component.call_translator_local.application import Application
from local_component.call_translator_local.engine import Engine
from local_component.call_translator_local.voices import VoiceStore


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default='uk',choices=['uk','en','ru'])
    parser.add_argument('--target',default='en',choices=['uk','en','ru'])
    args=parser.parse_args()
    trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    store=VoiceStore(Path('build/local-voices'),trust)
    store.select('incoming',args.source+'-basic');store.select('outgoing',args.target+'-basic')
    app=Application(store,Engine())
    report={}
    try:
        start=time.perf_counter()
        ready=list(app.handle({'id':1,'type':'begin-call','source':args.source,'target':args.target}))
        report['pair_ready']=ready[0].get('type')=='call-ready'
        report['warmup_seconds']=round(time.perf_counter()-start,3)
        phrases={'uk':'Привіт.','en':'Hello.','ru':'Привет.'}
        for index,(direction,text) in enumerate([('incoming',phrases[args.source]),('outgoing',phrases[args.target])],2):
            start=time.perf_counter()
            result=list(app.handle({'id':index,'type':'synthesize','direction':direction,'text':text}))
            report[direction]=result[-1].get('type')=='audio-end'
            report[direction+'_seconds']=round(time.perf_counter()-start,3)
    finally:app.close()
    Path(f'build/local-voice-pair-{args.source}-{args.target}-smoke.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    assert report['pair_ready'] and report['incoming'] and report['outgoing'],report
    print(json.dumps(report))


if __name__=='__main__':main()
