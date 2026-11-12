"""Server-side PCM detector and billing bridge (not yet connected to HTTP).

Only the audio ingress may assign start_ms on the shared call timeline. Client
claims of speech or billable duration must never reach this module.
"""

import webrtcvad

from .accounting import Accounting, CallRejected

FRAME_MS = 20
SAMPLE_RATE = 16000
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2


class SpeechMeter:
    def __init__(self, store: Accounting, call: str, *, detector_factory=None):
        self.store = store
        self.call = call
        factory = detector_factory or (lambda: webrtcvad.Vad(2))
        self.detectors = {direction: factory() for direction in ('incoming', 'outgoing')}
        self.ends = {'incoming': 0, 'outgoing': 0}
        self.last_speech_ms = 0

    def push(self, direction: str, pcm: bytes, start_ms: int):
        if direction not in self.detectors or not isinstance(pcm, bytes) or len(pcm) != FRAME_BYTES:
            raise ValueError('Expected one 20ms mono PCM16 frame at 16kHz')
        if type(start_ms) is not int or start_ms < self.ends[direction]:
            raise ValueError('Audio timeline must be monotonic per direction')
        end_ms = start_ms + FRAME_MS
        row = self.store.db.execute('SELECT state FROM calls WHERE id=?', (self.call,)).fetchone()
        if row is None or row[0] != 'active':
            raise CallRejected('call_stopped')
        speech = self.detectors[direction].is_speech(pcm, SAMPLE_RATE)
        charged = self.store.speech(self.call, direction, start_ms, end_ms) if speech else 0
        self.ends[direction] = end_ms
        if speech:
            self.last_speech_ms = max(self.last_speech_ms, end_ms)
        # Caller must independently forward the ORIGINAL frame to STT, including
        # silence. This result is billing metadata, never a replacement payload.
        return {'speech': speech, 'charged_ms': charged}

    def check_silence_timeout(self, now_ms: int):
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError('Invalid server clock')
        # AudioClock admits a bounded lead for buffered/jittered PCM frames.
        # A future frame end means no silence yet, not a protocol violation.
        # The ingress clock independently enforces the realtime allowance.
        if now_ms-self.last_speech_ms >= 600000:
            self.store.stop(self.call, 'silence_timeout')
            return True
        return False
