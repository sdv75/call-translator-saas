"""Native Messaging framing and offline diagnostic entry point.

Synthesis is available only after a signed voice has passed installation checks.
"""

import json
import struct
import sys

from . import __version__

MAX_REQUEST = 1024 * 1024


def exact_read(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size-len(data))
        if not chunk:
            if not data:
                return None
            raise ValueError('Truncated native message')
        data.extend(chunk)
    return bytes(data)


def read_message(stream):
    header = exact_read(stream, 4)
    if header is None:
        return None
    size = struct.unpack('<I', header)[0]
    if not 0 < size <= MAX_REQUEST:
        raise ValueError('Invalid native message size')
    body = exact_read(stream, size)
    if body is None:
        raise ValueError('Truncated native message')
    value = json.loads(body.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Native request must be an object')
    return value


def write_message(stream, value):
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(body) > MAX_REQUEST:
        raise ValueError('Native response exceeds Chrome limit')
    stream.write(struct.pack('<I', len(body)))
    stream.write(body)
    stream.flush()


def handle(request):
    from .application import Application
    return next(Application().handle(request))


def serve(stdin, stdout, application=None):
    if application is None:
        from .application import Application
        application = Application()
    try:
        return serve_messages(stdin, stdout, application)
    finally:
        application.close()


def serve_messages(stdin, stdout, application):
    while True:
        try:
            request = read_message(stdin)
            if request is None:
                return 0
            for response in application.handle(request):
                write_message(stdout, response)
        except (ValueError, UnicodeError, struct.error):
            write_message(stdout, {'error': 'invalid_native_message'})
            return 1


def main():
    if '--self-test' in sys.argv[1:]:
        try:
            import piper
            import onnxruntime
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            local_dependencies = True
        except ImportError:
            local_dependencies = False
        print(json.dumps({'status': 'ok', 'version': __version__, 'protocol': 1,
                          'synthesis_ready': False, 'local_dependencies_ready': local_dependencies}))
        return 0
    if sys.platform == 'win32':
        import msvcrt
        import os
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    return serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == '__main__':
    raise SystemExit(main())
