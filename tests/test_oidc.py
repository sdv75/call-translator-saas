import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from server.config import Settings
from server.oidc import GoogleOIDC, LoginFailed


class Response:
    status = 200

    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.data


class OIDCTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk['kid'] = 'test-key'

    async def verify(self, overrides=None, *, wrong_key=False):
        claims = {'iss': 'https://accounts.google.com', 'sub': 'verified-sub', 'aud': 'client',
                  'iat': int(time.time()), 'exp': int(time.time())+300, 'nonce': 'expected'}
        claims.update(overrides or {})
        token = jwt.encode(claims, self.other_key if wrong_key else self.key,
                           algorithm='RS256', headers={'kid': 'test-key'})
        jwk = self.jwk

        class Session:
            def post(self, *args, **kwargs):
                return Response({'id_token': token})

            def get(self, *args, **kwargs):
                return Response({'keys': [jwk]})

        provider = GoogleOIDC(Settings(google_client_id='client', google_client_secret='secret'), Session())
        return await provider.exchange('code', 'expected', 'verifier')

    async def test_valid_signed_token(self):
        self.assertEqual(await self.verify(), 'verified-sub')

    async def test_invalid_tokens_do_not_authenticate(self):
        for changes in ({'nonce': 'wrong'}, {'aud': 'other-client'}, {'iss': 'https://attacker.example'},
                        {'exp': 1}, {'iat': int(time.time())+3600}, {'azp': 'other-client'},
                        {'aud': ['client', 'other-client']}, {'sub': ''}):
            with self.subTest(changes=changes), self.assertRaises(LoginFailed):
                await self.verify(changes)
        with self.assertRaises(LoginFailed):
            await self.verify(wrong_key=True)
