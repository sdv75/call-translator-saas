"""Bounded resumable HTTPS downloads; redirect targets remain allowlisted."""

import hashlib
import os
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def https_origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('HTTPS required')
    return f'{parsed.scheme}://{parsed.netloc}'


class SafeRedirects(HTTPRedirectHandler):
    def __init__(self, asset_origin):
        self.asset_origin = asset_origin

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        origin = https_origin(newurl)
        host = urlsplit(newurl).hostname
        hf_asset = self.asset_origin == 'https://huggingface.co' and (host == 'huggingface.co' or host.endswith('.huggingface.co') or host.endswith('.hf.co'))
        if origin != self.asset_origin and not hf_asset:
            raise ValueError('Untrusted asset redirect')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024*1024):
            digest.update(chunk)
    return digest.hexdigest()


def download(asset, destination, *, opener=None):
    if destination.is_file() and destination.stat().st_size == asset['size'] and digest_file(destination) == asset['sha256']:
        return
    partial = destination.with_name(destination.name+'.part')
    offset = partial.stat().st_size if partial.exists() else 0
    if offset >= asset['size']:
        if offset == asset['size'] and digest_file(partial) == asset['sha256']:
            os.replace(partial, destination)
            return
        partial.unlink()
        offset = 0
    origin = https_origin(asset['url'])
    request = Request(asset['url'], headers={'User-Agent': 'CallTranslator/0.1', 'Accept-Encoding': 'identity'})
    if offset:
        request.add_header('Range', f'bytes={offset}-')
    transport = opener or build_opener(SafeRedirects(origin)).open
    with transport(request, timeout=60) as response:
        if response.status == 206:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            if not match or int(match[1]) != offset or int(match[3]) != asset['size'] or int(match[2]) != asset['size']-1:
                raise ValueError('Invalid resumable response')
        elif response.status == 200:
            offset = 0
        else:
            raise ValueError('Unexpected asset response')
        with partial.open('ab' if offset else 'wb') as target:
            total = offset
            while chunk := response.read(min(1024*1024, asset['size']-total+1)):
                total += len(chunk)
                if total > asset['size']:
                    raise ValueError('Asset exceeds signed size')
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    if partial.stat().st_size != asset['size']:
        raise ValueError('Incomplete asset; download can resume')
    if digest_file(partial) != asset['sha256']:
        partial.unlink()
        raise ValueError('Asset digest mismatch')
    os.replace(partial, destination)
