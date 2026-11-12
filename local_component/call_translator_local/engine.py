"""Technical local synthesis adapter; public responses use generic names."""

import io
import json
import re
import wave
from .language_data import voice_test_text


def prepare_text(text, language):
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Invalid synthesis text')
    if language == 'uk':
        from num2words import num2words
        text = text.lower().translate(str.maketrans({'’': "'", 'ʼ': "'", '‘': "'", '…': '...', '\u00a0': ' '}))
        text = re.sub(r'\d+(?:[.,]\d+)?', lambda item: num2words(item[0].replace(',', '.'), lang='uk'), text)
    return text


class Engine:
    def __init__(self):
        self.cache = {}

    def available(self):
        try:
            import piper
            import onnxruntime
            import num2words
            return True
        except Exception:
            return False

    def load(self, voice, folder):
        key = str(folder.resolve())
        if key not in self.cache:
            import onnxruntime
            from piper import PiperVoice
            from piper.config import PiperConfig
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = options.inter_op_num_threads = 1
            options.log_severity_level = 3
            config = PiperConfig.from_dict(json.loads((folder/'config.json').read_text(encoding='utf-8')))
            model = PiperVoice(session=onnxruntime.InferenceSession(str(folder/'model.onnx'),
                sess_options=options, providers=['CPUExecutionProvider']), config=config)
            self.cache[key] = model
        return self.cache[key]

    def render(self, voice, folder, text):
        from piper import SynthesisConfig
        model = self.load(voice, folder)
        output = io.BytesIO()
        with wave.open(output, 'wb') as target:
            model.synthesize_wav(prepare_text(text, voice['language']), target,
                syn_config=SynthesisConfig(speaker_id=voice.get('speaker_id', 0), normalize_audio=False))
        data = output.getvalue()
        if not 44 < len(data) <= 16*1024*1024:
            raise ValueError('Invalid local audio length')
        with wave.open(io.BytesIO(data), 'rb') as result:
            if result.getnchannels() != 1 or result.getsampwidth() != 2 or result.getnframes() == 0:
                raise ValueError('Invalid local audio format')
            if not any(result.readframes(result.getnframes())):
                raise ValueError('Local synthesis produced only silence')
        return data

    def smoke(self, voice, folder):
        self.render(voice, folder, voice_test_text(voice['language']))

    def close(self):
        self.cache.clear()
