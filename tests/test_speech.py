import tempfile
import unittest
from pathlib import Path

from server.accounting import Accounting
from server.speech import FRAME_BYTES, SpeechMeter


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Accounting(Path(self.temp.name)/'db.sqlite3')
        self.account = self.store.register('sub')
        self.call = self.store.start(self.account)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_real_detector_silence_is_free_and_timeout_releases(self):
        meter = SpeechMeter(self.store, self.call)
        for start in range(0, 2000, 20):
            for direction in ('incoming', 'outgoing'):
                self.assertEqual(meter.push(direction, bytes(FRAME_BYTES), start), {'speech': False, 'charged_ms': 0})
        self.assertFalse(meter.check_silence_timeout(599999))
        self.assertTrue(meter.check_silence_timeout(600000))
        self.assertEqual(self.store.balance(self.account), 300000)

    def test_meter_unions_direction_frames_without_billing_silence(self):
        class Detector:
            def is_speech(self, pcm, rate):
                return pcm[0] != 0
        meter = SpeechMeter(self.store, self.call, detector_factory=Detector)
        spoken = b'\x01'+bytes(FRAME_BYTES-1)
        self.assertEqual(meter.push('incoming', spoken, 0)['charged_ms'], 20)
        self.assertEqual(meter.push('outgoing', spoken, 0)['charged_ms'], 0)
        self.assertEqual(meter.push('incoming', bytes(FRAME_BYTES), 20)['charged_ms'], 0)
        self.assertEqual(meter.push('outgoing', spoken, 30)['charged_ms'], 20)
        with self.assertRaises(ValueError):
            meter.push('outgoing', spoken, 20)
        self.store.stop(self.call)
        self.assertEqual(self.store.balance(self.account), 299960)

    def test_rejects_wrong_pcm_without_charging(self):
        meter = SpeechMeter(self.store, self.call)
        for pcm in (b'', bytes(10), bytes(FRAME_BYTES*2)):
            with self.assertRaises(ValueError):
                meter.push('incoming', pcm, 0)
        self.store.stop(self.call)
        self.assertEqual(self.store.balance(self.account), 300000)

    def test_silence_watchdog_accepts_bounded_audio_clock_lead(self):
        class Detector:
            def is_speech(self, pcm, rate):
                return True
        meter = SpeechMeter(self.store, self.call, detector_factory=Detector)
        # AudioClock accepts frames ending up to 200 ms ahead of arrival.
        meter.push('incoming', bytes(FRAME_BYTES), 1000)
        self.assertFalse(meter.check_silence_timeout(900))
        self.assertFalse(meter.check_silence_timeout(601019))
        self.assertTrue(meter.check_silence_timeout(601020))
        with self.assertRaises(ValueError):
            meter.check_silence_timeout(-1)
