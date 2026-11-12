"""Bounded public HTTPS/OAuth-redirect/WebSocket checks; no customer account."""

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from aiohttp import ClientSession, ClientTimeout
from local_component.call_translator_local.catalog import canonical, verify

BASE='https://ppsbot.pp.ua/call-translator-saas'


async def probe():
    report={'public_https':True,'real_customer_account_used':False,'live_google_login_verified':False,
            'full_meet_call_verified':False}
    async with ClientSession(timeout=ClientTimeout(total=20)) as session:
        for path in ('/','/account','/install','/assets/site.js','/assets/site.css'):
            async with session.get(BASE+path) as response:
                if response.status!=200: raise ValueError('Public page or asset failed')
                await response.read()
        async with session.get(BASE+'/health') as response:
            health=await response.json()
            if response.status!=200 or health.get('status')!='ok' or not health.get('audio_enabled') or health.get('sales_enabled'):
                raise ValueError('SaaS health gates failed')
            report.update(health=health)
        async with session.get(BASE+'/api/voices') as response:
            catalog=await response.json()
            trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
            verified=verify(canonical(catalog),trust)
            report['signed_catalog_verified']=True
            report['catalog_revision']=verified['revision']
            report['catalog_languages']=sorted({voice['language'] for voice in verified['voices']})
            report['voice_count']=len(verified['voices'])
            report['voice_genders']={language:sorted({voice['gender'] for voice in verified['voices'] if voice['language']==language})
                                     for language in report['catalog_languages']}
        async with session.get(BASE+'/api/voices?scope=all') as response:
            if response.status!=200: raise ValueError('Full catalog unavailable')
            full=verify(canonical(await response.json()),trust)
            expected=verify(Path('catalog/voices.all.signed.json').read_bytes(),trust)
            if full!=expected: raise ValueError('Published full catalog differs')
            report['full_catalog_revision']=full['revision']
            report['full_voice_count']=len(full['voices'])
            report['full_language_count']=len({voice['language'] for voice in full['voices']})
        for path in ('/api/account','/download/setup'):
            async with session.get(BASE+path) as response:
                if response.status!=401: raise ValueError('Anonymous protection failed')
        report['anonymous_account_and_download_blocked']=True
        async with session.get(BASE+'/auth/google',allow_redirects=False) as response:
            location=response.headers.get('Location','')
            url=urlsplit(location)
            if response.status!=302 or url.hostname!='accounts.google.com': raise ValueError('Google redirect failed')
            if parse_qs(url.query).get('redirect_uri')!=[BASE+'/auth/google/callback']: raise ValueError('Google callback URI differs')
            cookie=response.cookies.get('ct_login')
            if not cookie or not cookie['secure'] or not cookie['httponly']: raise ValueError('Login cookie protection failed')
            report['google_redirect_and_secure_cookie_verified']=True
        async with session.ws_connect(BASE.replace('https:','wss:')+'/ws',origin='chrome-extension://afdgmhaicjhehhhhlahpeinieglofgml') as socket:
            await socket.send_json({'token':'INVALID-TECHNICAL-PROBE','source':'uk','target':'en'})
            stopped=await socket.receive_json(timeout=8)
            if stopped.get('type')!='stopped' or stopped.get('reason')!='authentication_required': raise ValueError('WebSocket authentication failed')
            report['https_websocket_upgrade_and_auth_verified']=True
        async with session.get('https://ppsbot.pp.ua/call-translator/health') as response:
            if response.status!=200 or (await response.json()).get('status')!='ok': raise ValueError('Legacy health failed')
            report['legacy_health_ok']=True
    return report


if __name__=='__main__':
    try: result=asyncio.run(probe())
    except Exception as exc:
        failure={'status':'failed','error_type':type(exc).__name__}
        if isinstance(getattr(exc,'status',None),int):failure['http_status']=exc.status
        if getattr(exc,'message',None) in ('Invalid upgrade header','Invalid connection header','Invalid challenge response'):
            failure['protocol_error']=exc.message
        print(json.dumps(failure));raise SystemExit(1)
    Path('build/vps-http-smoke.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
