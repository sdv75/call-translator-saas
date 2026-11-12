"""Configuration belongs to this service; no legacy connection files."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

PROJECT_ENV = Path(__file__).resolve().parents[1] / '.env'
DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / 'catalog' / 'voices.signed.json'


@dataclass(frozen=True)
class Settings:
    database: Path = Path('data/accounts.sqlite3')
    public_url: str = 'http://localhost:5086'
    host: str = '127.0.0.1'
    port: int = 5086
    google_client_id: str = ''
    google_client_secret: str = field(default='', repr=False)
    deepgram_key: str = field(default='', repr=False)
    groq_key: str = field(default='', repr=False)
    experimental_audio: bool = False
    voice_catalog: Path = DEFAULT_CATALOG
    download_root: Path | None = None

    def __post_init__(self):
        url = urlsplit(self.public_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                or url.password or url.query or url.fragment or self.public_url.endswith('/')):
            raise ValueError('Invalid CT_PUBLIC_URL; omit trailing slash')
        if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Public service requires HTTPS')
        if not 1 <= self.port <= 65535:
            raise ValueError('Invalid CT_PORT')
        if bool(self.google_client_id) != bool(self.google_client_secret):
            raise ValueError('Configure both Google OAuth credentials')
        if self.experimental_audio and not (self.deepgram_key and self.groq_key):
            raise ValueError('Experimental audio requires new SaaS provider keys')

    @property
    def prefix(self):
        return urlsplit(self.public_url).path

    @property
    def origin(self):
        url = urlsplit(self.public_url)
        return f'{url.scheme}://{url.netloc}'

    @property
    def secure_cookie(self):
        return self.public_url.startswith('https://')

    @classmethod
    def from_env(cls, env_file: Path | None = None):
        # Do not search parent directories, mutate os.environ, or interpolate
        # ${...} inside credentials. Process settings win over file aliases too.
        path = PROJECT_ENV if env_file is None else Path(env_file)
        values = dotenv_values(path, encoding='utf-8-sig', interpolate=False) if path.is_file() else {}

        def setting(name, default='', *aliases):
            for source in (os.environ, values):
                for key in (name, *aliases):
                    if key in source and source[key] is not None:
                        return source[key]
            return default

        try:
            port = int(setting('CT_PORT', '5086'))
        except ValueError:
            raise ValueError('CT_PORT must be an integer') from None
        return cls(
            database=Path(setting('CT_DATABASE', 'data/accounts.sqlite3')),
            public_url=setting('CT_PUBLIC_URL', 'http://localhost:5086'),
            host=setting('CT_HOST', '127.0.0.1'),
            port=port,
            google_client_id=setting('CT_GOOGLE_CLIENT_ID', '', 'GOOGLE_CLIENT_ID'),
            google_client_secret=setting('CT_GOOGLE_CLIENT_SECRET', '', 'GOOGLE_CLIENT_SECRET'),
            deepgram_key=setting('CT_DEEPGRAM_KEY', '', 'DEEPGRAM_API_KEY'),
            groq_key=setting('CT_GROQ_KEY', '', 'GROQ_API_KEY'),
            experimental_audio=setting('CT_EXPERIMENTAL_AUDIO', '0') == '1',
            voice_catalog=Path(setting('CT_VOICE_CATALOG', str(DEFAULT_CATALOG))),
            download_root=Path(setting('CT_DOWNLOAD_ROOT')) if setting('CT_DOWNLOAD_ROOT') else None,
        )
