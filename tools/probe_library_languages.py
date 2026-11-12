"""Fixed synthetic per-language provider check; prepend FIXTURES over SSH stdin."""
import asyncio
import base64
import json
import tempfile
import time
from pathlib import Path
from aiohttp import ClientSession,ClientTimeout
from server.accounting import Accounting
from server.config import Settings
from server.economics import Usage
from server.providers import Providers
from local_component.call_translator_local.language_data import voice_test_text


async def main():
    reports=[]
    with tempfile.TemporaryDirectory(prefix='ct-language-probe-') as temporary:
        store=Accounting(Path(temporary)/'probe.sqlite3')
        call=store.start(store.register('internal-synthetic-library-probe'))
        try:
            async with ClientSession(timeout=ClientTimeout(total=20)) as session:
                providers=Providers(Settings.from_env(),session,Usage(store))
                for language,encoded in FIXTURES.items():
                    began=time.monotonic()
                    report={'language':language,'stt':False,'translation_to_en':False,'translation_from_en':False}
                    stream=None
                    try:
                        stream=await providers.open_stt(call,'outgoing',language)
                        async def read():
                            async for result in stream.results():
                                if not result.get('partial'):report['stt']=True
                        reader=asyncio.create_task(read())
                        try:
                            pcm=base64.b64decode(encoded)
                            pcm+=bytes((-len(pcm))%640)+bytes(640*30)
                            for offset in range(0,len(pcm),640):
                                await stream.send(pcm[offset:offset+640]);await asyncio.sleep(.02)
                            await stream.finish();await asyncio.wait_for(reader,timeout=10)
                        finally:
                            reader.cancel();await asyncio.gather(reader,return_exceptions=True)
                        peer='ru' if language=='en' else 'en'
                        report['translation_to_en']=bool(await providers.translate(call,voice_test_text(language),language,peer))
                        report['translation_from_en']=bool(await providers.translate(call,voice_test_text(peer),peer,language))
                    except Exception as exc:report['error_type']=type(exc).__name__
                    finally:
                        if stream is not None:await stream.close()
                    report['ok']=all(report[key] for key in ('stt','translation_to_en','translation_from_en'))
                    reports.append(report);print(json.dumps(report),flush=True)
                    await asyncio.sleep(max(0,4.5-(time.monotonic()-began)))
            print(json.dumps({'summary':True,'languages_checked':len(reports),'passed':sum(report['ok'] for report in reports),
                              'synthetic_only':True,'customer_database_touched':False,'customer_billing_ms':0}),flush=True)
        finally:
            store.stop(call);store.close()


if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}));raise SystemExit(1)
