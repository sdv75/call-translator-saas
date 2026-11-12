"""Google authorization-code flow; tokens and provider responses are never logged."""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import jwt
from aiohttp import ClientSession

from .config import Settings


class LoginFailed(Exception):
    pass


class GoogleOIDC:
    def __init__(self, settings: Settings, session: ClientSession):
        self.settings = settings
        self.session = session
        self.keys = []
        self.keys_until = 0.0

    def authorization_url(self, state, nonce, verifier):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': self.settings.google_client_id,
            'redirect_uri': self.settings.public_url + '/auth/google/callback',
            'response_type': 'code', 'scope': 'openid', 'state': state, 'nonce': nonce,
            'code_challenge': challenge, 'code_challenge_method': 'S256',
        })

    async def exchange(self, code: str, nonce: str, verifier: str):
        async with self.session.post('https://oauth2.googleapis.com/token', data={
            'client_id': self.settings.google_client_id,
            'client_secret': self.settings.google_client_secret,
            'code': code, 'code_verifier': verifier, 'grant_type': 'authorization_code',
            'redirect_uri': self.settings.public_url + '/auth/google/callback',
        }, allow_redirects=False) as response:
            if response.status != 200:
                raise LoginFailed()
            data = await response.json()
        token = data.get('id_token')
        if not isinstance(token, str):
            raise LoginFailed()
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
                raise LoginFailed()
            if time.monotonic() >= self.keys_until:
                async with self.session.get('https://www.googleapis.com/oauth2/v3/certs', allow_redirects=False) as response:
                    if response.status != 200:
                        raise LoginFailed()
                    self.keys = (await response.json())['keys']
                    self.keys_until = time.monotonic() + 300
            key = next((key for key in self.keys if key.get('kid') == header['kid']), None)
            if key is None:
                # Expire cache for the next attempt after a Google key rotation.
                self.keys_until = 0
                raise LoginFailed()
            claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=['RS256'],
                                audience=self.settings.google_client_id,
                                issuer=['https://accounts.google.com', 'accounts.google.com'],
                                options={'require': ['exp', 'iat', 'sub', 'iss', 'aud', 'nonce']})
            if not isinstance(claims['nonce'], str) or not secrets.compare_digest(claims['nonce'], nonce):
                raise LoginFailed()
            if isinstance(claims['aud'], list) and len(claims['aud']) > 1 and 'azp' not in claims:
                raise LoginFailed()
            if claims.get('azp', self.settings.google_client_id) != self.settings.google_client_id:
                raise LoginFailed()
            if not isinstance(claims['sub'], str) or not claims['sub'].strip():
                raise LoginFailed()
            return claims['sub']
        except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
            raise LoginFailed() from exc
