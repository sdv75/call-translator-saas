import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from server.app import COOKIE, IDENTITY, STORE, create_app
from server.config import Settings
from server.downloads import verified_installer


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = b'MZ-verified-install-fixture'
        (self.root/'CallTranslatorSetup.exe').write_bytes(self.binary)
        self.manifest = {'installer_compiled': True, 'installer_sha256': hashlib.sha256(self.binary).hexdigest()}
        (self.root/'installer-manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8-sig')
        self.app = create_app(Settings(database=self.root/'db.sqlite3', public_url='http://localhost:5086/saas', download_root=self.root))
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        account = self.app[STORE].register('download-test-only')
        self.browser = self.app[IDENTITY].issue_browser(account)
        self.device, _ = self.app[IDENTITY].redeem_pairing(self.app[IDENTITY].new_pairing(account))

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_only_browser_account_can_download_and_response_is_private(self):
        self.assertTrue((await (await self.client.get('/saas/health')).json())['installer_available'])
        self.assertEqual((await self.client.get('/saas/download/setup')).status, 401)
        self.assertEqual((await self.client.get('/saas/download/setup', headers={'Authorization': 'Bearer '+self.device})).status, 401)
        response = await self.client.get('/saas/download/setup', cookies={COOKIE: self.browser})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), self.binary)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['Content-Disposition'], 'attachment; filename="CallTranslatorSetup.exe"')
        self.assertEqual((await self.client.get('/saas/download/installer-manifest.json', cookies={COOKIE: self.browser})).status, 404)

    async def test_corruption_is_rejected_before_publication(self):
        (self.root/'CallTranslatorSetup.exe').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            verified_installer(self.root)
