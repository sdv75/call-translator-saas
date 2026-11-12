"""HTTP API. Audio calls and sales remain disabled until their gates pass."""

import asyncio
import secrets
import time
from pathlib import Path
from collections import defaultdict, deque

from aiohttp import ClientError, ClientSession, ClientTimeout, web

from .accounting import Accounting
from .config import Settings
from .identity import Identity, Principal
from .lock import ServiceLock
from .oidc import GoogleOIDC, LoginFailed
from .economics import Usage
from .providers import Providers
from .streaming import serve_call
from .pages import PAGES, render
from .downloads import verified_installer
from local_component.call_translator_local.catalog import verify as verify_catalog

SETTINGS = web.AppKey('settings', Settings)
STORE = web.AppKey('store', Accounting)
IDENTITY = web.AppKey('identity', Identity)
OIDC = web.AppKey('oidc', GoogleOIDC)
LIMITS = web.AppKey('limits', dict)
PROVIDERS = web.AppKey('providers', Providers)
INSTALLER = web.AppKey('installer', Path)
COOKIE = 'ct_session'
LOGIN_COOKIE = 'ct_login'


def error(code: str, status: int):
    return web.json_response({'error': code}, status=status)


@web.middleware
async def security(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = web.Response(status=exc.status, body=exc.body, headers=exc.headers)
    except (ClientError, asyncio.TimeoutError):
        response = error('provider_unavailable', 503)
    except Exception:
        # Do not log request URLs, bodies, provider exceptions or tokens.
        response = error('internal_error', 500)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.setdefault('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
    return response


async def resources(app):
    settings = app[SETTINGS]
    settings.database.parent.mkdir(parents=True, exist_ok=True)
    lock = ServiceLock(settings.database.with_suffix('.lock'))
    store = None
    try:
        installer = await asyncio.to_thread(verified_installer, settings.download_root)
        if installer is not None:
            app[INSTALLER] = installer
        store = Accounting(settings.database)
        store.recover_after_restart()
        app[STORE] = store
        app[IDENTITY] = Identity(store)
        async with ClientSession(timeout=ClientTimeout(total=15)) as session:
            app[OIDC] = GoogleOIDC(settings, session)
            app[PROVIDERS] = Providers(settings, session, Usage(store))
            yield
    finally:
        if store is not None:
            store.recover_after_restart()
            store.close()
        lock.close()


def principal(request, *, browser_only=False, mutation=False) -> Principal:
    auth = request.headers.get('Authorization', '')
    kind = 'device' if auth else 'browser'
    token = auth.removeprefix('Bearer ') if auth.startswith('Bearer ') else request.cookies.get(COOKIE, '')
    who = request.app[IDENTITY].authenticate(token, kind)
    if not who or (browser_only and who.kind != 'browser'):
        raise web.HTTPUnauthorized(text='{"error":"authentication_required"}', content_type='application/json')
    if mutation and who.kind == 'browser':
        if request.headers.get('Origin') != request.app[SETTINGS].origin or not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), who.csrf):
            raise web.HTTPForbidden(text='{"error":"csrf_failed"}', content_type='application/json')
    return who


def rate_limit(request):
    now = time.monotonic()
    limits = request.app[LIMITS]
    # Trust the socket peer, never an arbitrary X-Forwarded-For value.
    for key in list(limits):
        if not limits[key] or limits[key][-1] < now-60:
            del limits[key]
    key = (request.remote, request.path)
    if key not in limits and len(limits) >= 1000:
        raise web.HTTPTooManyRequests()
    recent = limits[key]
    while recent and recent[0] < now-60:
        recent.popleft()
    if len(recent) >= 20:
        raise web.HTTPTooManyRequests()
    recent.append(now)


async def health(request):
    request.app[STORE].db.execute('SELECT 1').fetchone()
    return web.json_response({'status': 'ok', 'audio_enabled': request.app[SETTINGS].experimental_audio, 'sales_enabled': False,
                              'google_login_configured': bool(request.app[SETTINGS].google_client_id),
                              'installer_available': INSTALLER in request.app})


async def download_setup(request):
    principal(request, browser_only=True)
    if INSTALLER not in request.app:
        return error('installer_unavailable', 503)
    return web.FileResponse(request.app[INSTALLER], headers={
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': 'attachment; filename="CallTranslatorSetup.exe"'})


async def login(request):
    rate_limit(request)
    settings = request.app[SETTINGS]
    if not settings.google_client_id:
        return error('google_login_not_configured', 503)
    state, browser, nonce, verifier = request.app[IDENTITY].new_login()
    response = web.Response(status=302, headers={'Location': request.app[OIDC].authorization_url(state, nonce, verifier)})
    response.set_cookie(LOGIN_COOKIE, browser, max_age=600, httponly=True, secure=settings.secure_cookie,
                        samesite='Lax', path=settings.prefix + '/auth/google')
    return response


async def callback(request):
    rate_limit(request)
    settings = request.app[SETTINGS]
    if not settings.google_client_id:
        return error('google_login_not_configured', 503)
    state, code = request.query.get('state', ''), request.query.get('code', '')
    saved = request.app[IDENTITY].consume_login(state, request.cookies.get(LOGIN_COOKIE, ''))
    if saved is None or not code or 'error' in request.query:
        return error('login_failed', 401)
    nonce, verifier = saved
    try:
        sub = await request.app[OIDC].exchange(code, nonce, verifier)
    except LoginFailed:
        return error('login_failed', 401)
    account = request.app[STORE].register(sub)
    identity = request.app[IDENTITY]
    old = request.cookies.get(COOKIE)
    if old:
        identity.revoke_token(old)
    token = identity.issue_browser(account)
    response = web.Response(status=302, headers={'Location': settings.prefix + '/account'})
    response.set_cookie(COOKIE, token, max_age=86400, httponly=True, secure=settings.secure_cookie,
                        samesite='Lax', path=settings.prefix or '/')
    response.del_cookie(LOGIN_COOKIE, path=settings.prefix + '/auth/google')
    return response


async def account(request):
    who = principal(request)
    store = request.app[STORE]
    active = store.db.execute("SELECT id, reserve_ms, speech_ms FROM calls WHERE account_id=? AND state='active'", (who.account,)).fetchone()
    reserve = active[1] if active else 0
    data = {'account_id': who.account, 'balance_ms': store.balance(who.account)+reserve,
            'reserved_ms': reserve, 'active_call': active[0] if active else None}
    if who.kind == 'browser':
        data['csrf_token'] = who.csrf
    return web.json_response(data)


async def logout(request):
    principal(request, browser_only=True, mutation=True)
    request.app[IDENTITY].revoke_token(request.cookies.get(COOKIE, ''))
    response = web.json_response({'status': 'signed_out'})
    response.del_cookie(COOKIE, path=request.app[SETTINGS].prefix or '/')
    return response


async def pair(request):
    rate_limit(request)
    who = principal(request, browser_only=True, mutation=True)
    return web.json_response({'code': request.app[IDENTITY].new_pairing(who.account), 'expires_in': 300})


async def redeem(request):
    rate_limit(request)
    try:
        data = await request.json()
    except (ValueError, UnicodeError):
        return error('invalid_request', 400)
    if not isinstance(data, dict) or not isinstance(data.get('code'), str) or len(data['code']) > 128:
        return error('invalid_request', 400)
    result = request.app[IDENTITY].redeem_pairing(data['code'])
    if result is None:
        return error('invalid_pairing_code', 401)
    return web.json_response({'access_token': result[0], 'device_id': result[1], 'expires_in': 30*86400}, status=201)


async def devices(request):
    who = principal(request, browser_only=True)
    rows = request.app[STORE].db.execute("SELECT device_id, created_at, expires_at FROM credentials WHERE account_id=? AND kind='device' AND expires_at>? ORDER BY created_at DESC", (who.account, int(time.time()))).fetchall()
    return web.json_response({'devices': [dict(zip(('id', 'created_at', 'expires_at'), row)) for row in rows]})


async def revoke(request):
    who = principal(request, browser_only=True, mutation=True)
    if not request.app[IDENTITY].revoke_device(who.account, request.match_info['device']):
        return error('device_not_found', 404)
    return web.json_response({'status': 'revoked'})


async def unlink(request):
    who = principal(request, mutation=True)
    if who.kind != 'device':
        return error('device_credentials_required', 403)
    request.app[IDENTITY].revoke_token(request.headers['Authorization'].removeprefix('Bearer '))
    return web.json_response({'status': 'unlinked'})


async def history(request):
    who = principal(request)
    rows = request.app[STORE].db.execute('SELECT id, state, speech_ms, stop_reason FROM calls WHERE account_id=? ORDER BY rowid DESC LIMIT 100', (who.account,)).fetchall()
    return web.json_response({'calls': [dict(zip(('id', 'state', 'speech_ms', 'stop_reason'), row)) for row in rows]})


async def calls_disabled(request):
    principal(request, mutation=True)
    return error('audio_pipeline_not_ready', 503)


async def audio(request):
    rate_limit(request)
    return await serve_call(request, request.app[SETTINGS], request.app[STORE], request.app[IDENTITY], request.app[PROVIDERS])


async def voice_catalog(request):
    path = request.app[SETTINGS].voice_catalog
    if request.query.get('scope')=='all':path=path.with_name('voices.all.signed.json')
    trust_file = Path(__file__).resolve().parents[1]/'local_component'/'call_translator_local'/'catalog-trust.json'
    if not path.is_file() or not trust_file.is_file() or path.stat().st_size > 1024*1024:
        return error('voice_catalog_not_configured', 503)
    try:
        import json
        raw = path.read_bytes()
        verify_catalog(raw, json.loads(trust_file.read_text(encoding='utf-8')))
    except Exception:
        return error('voice_catalog_unavailable', 503)
    return web.Response(body=raw, content_type='application/json')


async def page(request):
    prefix = request.app[SETTINGS].prefix
    path = request.path[len(prefix):] or '/'
    return web.Response(text=render(path, prefix), content_type='text/html', headers={
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})


async def asset(request):
    name = request.match_info['asset']
    if name not in ('site.js', 'site.css'):
        raise web.HTTPNotFound()
    path = Path(__file__).parent/'static'/name
    return web.Response(body=path.read_bytes(), content_type='text/javascript' if name.endswith('.js') else 'text/css')


def create_app(settings: Settings | None = None):
    app = web.Application(middlewares=[security], client_max_size=4096)
    app[SETTINGS] = settings or Settings.from_env()
    app[LIMITS] = defaultdict(deque)
    app.cleanup_ctx.append(resources)
    prefix = app[SETTINGS].prefix
    for path in PAGES:
        app.router.add_get(prefix+path, page)
    if prefix:
        app.router.add_get(prefix, page)
    app.router.add_get(prefix+'/assets/{asset}', asset)
    for method, path, handler in (
        ('GET', '/health', health), ('GET', '/auth/google', login),
        ('GET', '/auth/google/callback', callback), ('POST', '/auth/logout', logout),
        ('GET', '/api/account', account), ('GET', '/api/calls', history),
        ('POST', '/api/calls', calls_disabled), ('POST', '/api/devices/pair', pair),
        ('POST', '/api/devices/redeem', redeem), ('GET', '/api/devices', devices),
        ('POST', '/api/devices/unlink', unlink),
        ('DELETE', '/api/devices/{device}', revoke),
        ('GET', '/ws', audio),
        ('GET', '/api/voices', voice_catalog),
        ('GET', '/download/setup', download_setup),
    ):
        app.router.add_route(method, prefix+path, handler)
    return app
