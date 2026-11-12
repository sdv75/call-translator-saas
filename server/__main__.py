from aiohttp import web

from .app import create_app
from .config import Settings


def main():
    settings = Settings.from_env()
    # OAuth callback query strings contain authorization codes. Disable the
    # default access logger; reverse proxy logging must be configured likewise.
    web.run_app(create_app(settings), host=settings.host, port=settings.port, access_log=None)


if __name__ == '__main__':
    main()
