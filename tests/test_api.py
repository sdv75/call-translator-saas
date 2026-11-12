import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from server.accounting import Accounting
from server.app import COOKIE, IDENTITY, OIDC, STORE, create_app
from server.config import Settings


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(database=Path(self.temp.name)/'db.sqlite3',
                                 public_url='http://localhost:5086/call-translator-saas',
                                 google_client_id='test-client', google_client_secret='test-secret')
        self.app = create_app(self.settings)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.account = self.app[STORE].register('test-google-sub')
        self.token = self.app[IDENTITY].issue_browser(self.account)
        self.csrf = self.app[IDENTITY].authenticate(self.token, 'browser').csrf

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def request(self, method, path, *, token=None, csrf=None, origin=None, **kwargs):
        headers = kwargs.pop('headers', {})
        headers.update({'Origin': origin or self.settings.origin, 'X-CSRF-Token': csrf or self.csrf})
        return await self.client.request(method, '/call-translator-saas'+path,
                                         cookies={COOKIE: token or self.token}, headers=headers, **kwargs)

    async def test_health_and_auth_required(self):
        response = await self.client.get('/call-translator-saas/health')
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())['audio_enabled'])
        response = await self.client.get('/call-translator-saas/api/account')
        self.assertEqual(response.status, 401)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_local_pages_assets_and_csp(self):
        response = await self.client.get('/call-translator-saas/account')
        self.assertEqual(response.status, 200)
        self.assertIn('script-src \'self\'', response.headers['Content-Security-Policy'])
        self.assertIn('/call-translator-saas/assets/site.js', await response.text())
        response = await self.client.get('/call-translator-saas/assets/site.js')
        self.assertEqual(response.status, 200)
        response = await self.client.get('/call-translator-saas/assets/accounting.py')
        self.assertEqual(response.status, 404)

    async def test_catalog_route_rejects_unconfigured_or_invalid_file(self):
        from dataclasses import replace
        missing = Path(self.temp.name)/'missing-catalog.json'
        client = TestClient(TestServer(create_app(replace(self.settings,
                            database=Path(self.temp.name)/'catalog-test.sqlite3', voice_catalog=missing))))
        await client.start_server()
        try:
            response = await client.get('/call-translator-saas/api/voices')
            self.assertEqual(response.status, 503)
            missing.write_text('{"private":"must-not-be-served"}', encoding='utf-8')
            response = await client.get('/call-translator-saas/api/voices')
            self.assertEqual(response.status, 503)
            self.assertNotIn('must-not-be-served', await response.text())
        finally:
            await client.close()

    async def test_full_catalog_is_separate_and_still_requires_a_signature(self):
        from dataclasses import replace
        legacy=Path(self.temp.name)/'legacy.json'
        legacy.write_text('{"private":"never-serve-this"}',encoding='utf-8')
        full=legacy.with_name('voices.all.signed.json')
        full.write_bytes(self.settings.voice_catalog.read_bytes())
        client=TestClient(TestServer(create_app(replace(self.settings,
            database=Path(self.temp.name)/'scope.sqlite3',voice_catalog=legacy))))
        await client.start_server()
        try:
            self.assertEqual((await client.get('/call-translator-saas/api/voices')).status,503)
            response=await client.get('/call-translator-saas/api/voices?scope=all')
            self.assertEqual(response.status,200)
            self.assertEqual(await response.read(),full.read_bytes())
            full.write_text('{}',encoding='utf-8')
            self.assertEqual((await client.get('/call-translator-saas/api/voices?scope=all')).status,503)
        finally:await client.close()
        response = await self.client.get('/account')
        self.assertEqual(response.status, 404)

    async def test_account_isolated_from_supplied_account_id(self):
        other = self.app[STORE].register('other-google-sub')
        call = self.app[STORE].start(other)
        self.app[STORE].speech(call, 'incoming', 0, 1000)
        response = await self.request('GET', '/api/account?account_id='+other)
        data = await response.json()
        self.assertEqual(data['account_id'], self.account)
        self.assertEqual(data['balance_ms'], 300000)
        response = await self.request('GET', '/api/calls?account_id='+other)
        self.assertEqual((await response.json())['calls'], [])

    async def test_calls_disabled_do_not_reserve(self):
        response = await self.request('POST', '/api/calls')
        self.assertEqual(response.status, 503)
        self.assertEqual(self.app[STORE].balance(self.account), 300000)

    async def test_csrf_pair_redeem_replay_revoke(self):
        response = await self.request('POST', '/api/devices/pair', origin='https://attacker.example')
        self.assertEqual(response.status, 403)
        response = await self.request('POST', '/api/devices/pair', csrf='wrong')
        self.assertEqual(response.status, 403)
        response = await self.request('POST', '/api/devices/pair')
        code = (await response.json())['code']
        response = await self.client.post('/call-translator-saas/api/devices/redeem', json={'code': code})
        self.assertEqual(response.status, 201)
        data = await response.json()
        response = await self.client.post('/call-translator-saas/api/devices/redeem', json={'code': code})
        self.assertEqual(response.status, 401)
        response = await self.client.get('/call-translator-saas/api/account', headers={'Authorization': 'Bearer '+data['access_token']})
        self.assertEqual(response.status, 200)
        self.assertNotIn('csrf_token', await response.json())
        other = self.app[STORE].register('another-user')
        other_token = self.app[IDENTITY].issue_browser(other)
        other_csrf = self.app[IDENTITY].authenticate(other_token, 'browser').csrf
        response = await self.request('DELETE', '/api/devices/'+data['device_id'], token=other_token, csrf=other_csrf)
        self.assertEqual(response.status, 404)
        response = await self.request('DELETE', '/api/devices/'+data['device_id'])
        self.assertEqual(response.status, 200)
        response = await self.client.get('/call-translator-saas/api/account', headers={'Authorization': 'Bearer '+data['access_token']})
        self.assertEqual(response.status, 401)

    async def test_logout_revokes(self):
        response = await self.request('POST', '/auth/logout')
        self.assertEqual(response.status, 200)
        response = await self.request('GET', '/api/account')
        self.assertEqual(response.status, 401)

    async def test_device_can_only_unlink_itself(self):
        identity = self.app[IDENTITY]
        token, device = identity.redeem_pairing(identity.new_pairing(self.account))
        response = await self.client.post('/call-translator-saas/api/devices/unlink', headers={'Authorization': 'Bearer '+token})
        self.assertEqual(response.status, 200)
        self.assertIsNone(identity.authenticate(token, 'device'))
        self.assertIsNotNone(identity.authenticate(self.token, 'browser'))

    async def test_callback_state_browser_binding_and_replay(self):
        response = await self.client.get('/call-translator-saas/auth/google', allow_redirects=False)
        self.assertEqual(response.status, 302)
        state = parse_qs(urlsplit(response.headers['Location']).query)['state'][0]
        browser = response.cookies['ct_login'].value
        # Replace only the Google network boundary. JWT verification is tested separately.
        response = await self.client.get('/call-translator-saas/auth/google/callback',
                                         params={'state': state, 'code': 'test-code'},
                                         cookies={'ct_login': 'wrong'}, allow_redirects=False)
        self.assertEqual(response.status, 401)
        with patch.object(self.app[OIDC], 'exchange', AsyncMock(return_value='new-verified-google-sub')):
            response = await self.client.get('/call-translator-saas/auth/google/callback',
                                             params={'state': state, 'code': 'test-code'},
                                             cookies={'ct_login': browser}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        session_cookie = response.cookies[COOKIE]
        self.assertTrue(session_cookie['httponly'])
        self.assertEqual(session_cookie['samesite'], 'Lax')
        response = await self.client.get('/call-translator-saas/auth/google/callback',
                                         params={'state': state, 'code': 'test-code'},
                                         cookies={'ct_login': browser}, allow_redirects=False)
        self.assertEqual(response.status, 401)

    async def test_startup_and_shutdown_release_reserve(self):
        self.app[STORE].start(self.account)
        await self.client.close()
        store = Accounting(self.settings.database)
        try:
            self.assertEqual(store.balance(self.account), 300000)
        finally:
            store.close()

    async def test_second_process_does_not_recover_live_calls(self):
        call = self.app[STORE].start(self.account)
        other = TestClient(TestServer(create_app(self.settings)))
        try:
            with self.assertRaisesRegex(RuntimeError, 'Another server'):
                await other.start_server()
        finally:
            await other.close()
        self.assertEqual(self.app[STORE].speech(call, 'incoming', 0, 1), 1)


class ConfigTests(unittest.TestCase):
    def test_https_and_secret_redaction(self):
        with self.assertRaises(ValueError):
            Settings(public_url='http://public.example')
        with self.assertRaises(ValueError):
            Settings(google_client_id='client')
        settings = Settings(google_client_id='client', google_client_secret='private-value')
        self.assertNotIn('private-value', repr(settings))
