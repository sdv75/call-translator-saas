"""Collect final STT segments without replaying the same audio interval."""
from collections import deque
from array import array
import math
import sys


class SpeechDetector:
    """Remove low-frequency rumble before classifying 20 ms PCM frames."""
    def __init__(self):
        import webrtcvad
        self.vad = webrtcvad.Vad(3)
        omega = 2 * math.pi * 150 / 16000
        cosine = math.cos(omega)
        alpha = math.sin(omega) / math.sqrt(2)
        denominator = 1 + alpha
        self.b0 = (1 + cosine) / (2 * denominator)
        self.b1 = -(1 + cosine) / denominator
        self.a1 = -2 * cosine / denominator
        self.a2 = (1 - alpha) / denominator
        self.sections = [[0., 0.], [0., 0.]]

    def is_speech(self, frame, rate):
        samples = array('h')
        samples.frombytes(frame)
        if sys.byteorder != 'little':
            samples.byteswap()
        filtered = array('h')
        for value in samples:
            for state in self.sections:
                output = self.b0 * value + state[0]
                state[0] = self.b1 * value - self.a1 * output + state[1]
                state[1] = self.b0 * value - self.a2 * output
                value = output
            filtered.append(max(-32768, min(32767, round(value))))
        energy = sum(value * value for value in filtered) / len(filtered)
        if sys.byteorder != 'little':
            filtered.byteswap()
        voiced = self.vad.is_speech(filtered.tobytes(), rate)
        return voiced and energy > 64 ** 2


class AudioActivity:
    """Gate noise and track speech on the same sample clock as streaming STT."""
    def __init__(self, detector=None, gate=False):
        if detector is None:
            detector = SpeechDetector()
        self.detector = detector
        self.gate = gate
        self.samples = 0
        self.intervals = deque()
        self.signals = deque()
        self.partial = bytearray()
        self.preroll = deque()
        self.tail = 0

    def add(self, pcm):
        self.partial.extend(pcm)
        output = bytearray()
        while len(self.partial) >= 640:
            frame = bytes(self.partial[:640])
            del self.partial[:640]
            start = self.samples / 16000
            self.samples += 320
            end = self.samples / 16000
            speech = self.detector.is_speech(frame, 16000)
            raw = array('h'); raw.frombytes(frame)
            if sys.byteorder != 'little': raw.byteswap()
            if sum(value * value for value in raw) / len(raw) > 16 ** 2:
                self.signals.append((start, end))
            if speech:
                self.intervals.append((start, end))
                self.tail = 15  # Preserve 300 ms of word endings.
                for buffered in self.preroll:
                    buffered[1] = True
            keep = speech or self.tail > 0
            self.tail = max(0, self.tail - 1)
            if not self.gate:
                output.extend(frame)
            else:
                self.preroll.append([frame, keep])
            # A 100 ms lookbehind protects consonants at speech onset.
            if len(self.preroll) > 5:
                buffered, keep = self.preroll.popleft()
                output.extend(buffered if keep else bytes(640))
            while self.intervals and self.intervals[0][1] < end - 120:
                self.intervals.popleft()
            while self.signals and self.signals[0][1] < end - 120:
                self.signals.popleft()
        return bytes(output)

    def drain(self):
        frames = b''.join(frame if keep else bytes(640) for frame, keep in self.preroll)
        self.preroll.clear()
        if self.partial:
            frames += bytes(self.partial).ljust(640, b'\0'); self.partial.clear()
        return frames

    def has_signal(self, result):
        start, duration = result.get('start'), result.get('duration')
        if not all(isinstance(n, (int, float)) and math.isfinite(n) and n >= 0 for n in (start, duration)):
            return True
        return any(right > start and left < start + duration for left, right in self.signals)

    def overlaps(self, result):
        start, duration = result.get('start'), result.get('duration')
        if not all(isinstance(n, (int, float)) and math.isfinite(n) and n >= 0
                   for n in (start, duration)):
            return True
        end = start + duration
        voiced = sum(max(0, min(right, end) - max(left, start))
                     for left, right in self.intervals)
        return voiced + 1e-6 >= min(.1, duration / 2) and voiced > 0


class Utterances:
    def __init__(self):
        self.pending = []
        self.start = None
        self.uncertain = False
        self.last_start = None
        self.last_uncertain = False
        self.recent = deque()
        self.seen = set()

    def flush(self):
        text = ' '.join(self.pending)
        self.last_start, self.last_uncertain = self.start, self.uncertain
        self.pending.clear()
        self.start, self.uncertain = None, False
        return text or None

    def feed(self, result, audible=True):
        if result.get('type') == 'UtteranceEnd':
            return self.flush()
        alternatives = result.get('channel', {}).get('alternatives', [])
        alternative = alternatives[0] if alternatives else {}
        text = alternative.get('transcript', '').strip()
        if result.get('is_final') and text:
            start, duration = result.get('start'), result.get('duration')
            key = (start, duration) if all(isinstance(n, (int, float)) and
                math.isfinite(n) and n >= 0 for n in (start, duration)) else None
            duplicate = key is not None and key in self.seen
            if not duplicate and audible:
                if key is not None:
                    self.seen.add(key)
                    self.recent.append(key)
                    if len(self.recent) > 512:
                        self.seen.remove(self.recent.popleft())
                confidence = alternative.get('confidence')
                # Low confidence is a warning, not permission to delete speech.
                self.uncertain |= isinstance(confidence, (int, float)) and (
                    not math.isfinite(confidence) or confidence < .5)
                self.pending.append(text)
                if key is not None:
                    self.start = start if self.start is None else min(self.start, start)
        if result.get('speech_final') or sum(map(len, self.pending)) >= 1000:
            return self.flush()
        return None
