import base64
import io
import json
import struct
import unittest
import host


def response(stream):
    header = host.read_exact(stream, 4)
    if header is None:
        return None
    size = struct.unpack('<I', header)[0]
    assert size < 1024 * 1024
    return json.loads(host.read_exact(stream, size))


class FakeEngine:
    def load(self):
        pass

    def render(self, text, language):
        return b'RIFF' + b'\0' * 500000


class HostTest(unittest.TestCase):
    def test_ukrainian_text_keeps_initial_letters_apostrophes_and_numbers(self):
        text = host.prepare_text('Привіт! П’ять зустрічей, 21 день.', 'uk')
        self.assertEqual(text, "привіт! п'ять зустрічей, двадцять один день.")
        self.assertEqual(host.prepare_text('Hello 21', 'en'), 'Hello 21')

    def test_ukrainian_voice_is_advertised_and_synthesized(self):
        reader, writer = io.BytesIO(), io.BytesIO()
        host.write_message(reader, {'id': 1, 'type': 'init'})
        host.write_message(reader, {'id': 2, 'type': 'synthesize', 'language': 'uk', 'text': 'Привіт'})
        reader.seek(0)
        host.serve(reader, writer, FakeEngine())
        writer.seek(0)
        self.assertIn('uk', response(writer)['voices'])
        messages = []
        while (message := response(writer)) is not None:
            messages.append(message)
        self.assertEqual(messages[-1]['type'], 'audio-end')

    def test_framing_and_large_audio_roundtrip(self):
        reader, writer = io.BytesIO(), io.BytesIO()
        host.write_message(reader, {'id': 1, 'type': 'init'})
        host.write_message(reader, {'id': 2, 'type': 'synthesize', 'language': 'ru', 'text': 'Привет'})
        reader.seek(0)
        host.serve(reader, writer, FakeEngine())
        writer.seek(0)
        self.assertEqual(response(writer)['type'], 'ready')
        messages = []
        while (message := response(writer)) is not None:
            messages.append(message)
        end = messages.pop()
        self.assertEqual(end['type'], 'audio-end')
        self.assertEqual(end['chunks'], 3)
        self.assertEqual([item['index'] for item in messages], [0, 1, 2])
        audio = base64.b64decode(''.join(item['data'] for item in messages), validate=True)
        self.assertEqual(audio, FakeEngine().render('', 'ru'))
        self.assertEqual(end['bytes'], len(audio))

    def test_invalid_text_rejected_without_echoing_it(self):
        reader, writer = io.BytesIO(), io.BytesIO()
        host.write_message(reader, {'id': 1, 'type': 'synthesize', 'language': 'xx', 'text': 'PRIVATE_TEXT'})
        reader.seek(0)
        host.serve(reader, writer, FakeEngine())
        self.assertNotIn(b'PRIVATE_TEXT', writer.getvalue())
        writer.seek(0)
        self.assertEqual(host.read_message(writer)['type'], 'error')

    def test_truncated_and_oversized_frames_fail_closed(self):
        for data in [b'\x01', struct.pack('<I', 100000), struct.pack('<I', 5) + b'{}']:
            with self.assertRaises(ValueError):
                host.read_message(io.BytesIO(data))


if __name__ == '__main__':
    unittest.main()
