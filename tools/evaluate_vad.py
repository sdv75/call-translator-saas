"""Offline VAD evaluation; emits only durations and accuracy, no audio/text.

Annotations JSON: [[start_ms, end_ms], ...]. Use only locally consented fixtures.
No fixture content is uploaded or copied into the server database.
"""

import argparse
import json
import wave
from pathlib import Path

import webrtcvad

from server.speech import FRAME_BYTES, FRAME_MS, SAMPLE_RATE


def evaluate(audio: Path, annotations: Path):
    truth = json.loads(annotations.read_text(encoding='utf-8'))
    for interval in truth:
        if not isinstance(interval, list) or len(interval) != 2 or any(type(v) is not int for v in interval) or not 0 <= interval[0] < interval[1]:
            raise ValueError('Annotations must be nonnegative millisecond intervals')
    counts = {'true_positive_ms': 0, 'false_positive_ms': 0, 'false_negative_ms': 0, 'true_negative_ms': 0}
    detector = webrtcvad.Vad(2)
    frames = 0
    with wave.open(str(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE) or wav.getcomptype() != 'NONE':
            raise ValueError('Expected uncompressed PCM16 mono WAV at 16kHz')
        while frame := wav.readframes(FRAME_BYTES//2):
            if len(frame) < FRAME_BYTES:
                break
            start = frames*FRAME_MS
            # Annotated intervals are evaluated at frame midpoints.
            expected = any(s <= start+FRAME_MS//2 < e for s, e in truth)
            observed = detector.is_speech(frame, SAMPLE_RATE)
            label = ('true_positive_ms' if expected and observed else
                     'false_positive_ms' if observed else
                     'false_negative_ms' if expected else 'true_negative_ms')
            counts[label] += FRAME_MS
            frames += 1
    tp, fp, fn = (counts[key] for key in ('true_positive_ms', 'false_positive_ms', 'false_negative_ms'))
    return {**counts, 'evaluated_ms': frames*FRAME_MS,
            'precision': tp/(tp+fp) if tp+fp else None,
            'recall': tp/(tp+fn) if tp+fn else None,
            'frame_ms': FRAME_MS, 'vad_mode': 2, 'production_validated': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('annotations', type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.audio, args.annotations), indent=2))


if __name__ == '__main__':
    main()
