"""Local Chrome headless smoke; uses an isolated profile and temporary database."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from aiohttp import web

from server.app import create_app
from server.config import Settings


async def main():
    candidates = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'))/'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)'))/'Google/Chrome/Application/chrome.exe']
    chrome = next((path for path in candidates if path.is_file()), None)
    if chrome is None:
        raise RuntimeError('Chrome not found; browser QA not performed')
    preview = Path('build/site-preview.png').resolve()
    preview.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ct-site-smoke-') as temp:
        root = Path(temp)
        app = create_app(Settings(database=root/'db.sqlite3', public_url='http://localhost:5086/call-translator-saas'))
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            process = await asyncio.create_subprocess_exec(str(chrome), '--headless=new', '--disable-gpu',
                '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
                '--user-data-dir='+str(root/'profile'), '--window-size=1440,1000',
                '--virtual-time-budget=3000', '--dump-dom', '--screenshot='+str(preview),
                f'http://127.0.0.1:{port}/call-translator-saas/account',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=45)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            dom = stdout.decode('utf-8', errors='replace')
            if process.returncode or 'Google-вход ещё не настроен.' not in dom or not preview.is_file():
                raise RuntimeError('Chrome smoke failed; inspect local preview artifact')
            print(json.dumps({'browser': 'Chrome headless', 'account_unconfigured_state': 'ok',
                              'screenshot': str(preview), 'live_google_login': False}, ensure_ascii=False))
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
