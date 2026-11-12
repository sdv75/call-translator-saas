import unittest
import struct
from types import SimpleNamespace
from transcripts import AudioActivity, Utterances


def result(text, start=0, confidence=.95, final=True, end=True):
    return {'is_final': final, 'speech_final': end, 'start': start, 'duration': 1,
        'channel': {'alternatives': [{'transcript': text, 'confidence': confidence}]}}


class UtterancesTest(unittest.TestCase):
    def test_silent_audio_rejects_even_confident_hallucination(self):
        activity = AudioActivity(detector=SimpleNamespace(is_speech=lambda frame, rate: False), gate=True)
        activity.add(b'\x00\x00' * 16000)
        utterances = Utterances()
        hallucination = result('Hello dear', confidence=.99)
        self.assertFalse(activity.overlaps(hallucination))
        self.assertIsNone(utterances.feed(hallucination, audible=activity.overlaps(hallucination)))

    def test_audio_activity_uses_segment_time_not_previous_speech(self):
        activity = AudioActivity(detector=SimpleNamespace(is_speech=lambda frame, rate: any(frame)))
        activity.add(struct.pack('<h', 1000) * 16000)
        activity.add(b'\x00\x00' * 16000)
        self.assertTrue(activity.overlaps(result('Real speech', start=0)))
        self.assertFalse(activity.overlaps(result('Hello dear', start=1)))

    def test_loud_non_speech_is_zeroed_without_changing_sample_clock(self):
        activity = AudioActivity(detector=SimpleNamespace(is_speech=lambda frame, rate: False), gate=True)
        noise = struct.pack('<h', 8000) * 16000
        filtered = activity.add(noise)
        self.assertEqual(filtered, bytes(640 * 45))
        self.assertEqual(activity.samples, 16000)
        self.assertFalse(activity.overlaps(result('Invented words')))

    def test_speech_preroll_preserves_word_onset(self):
        decisions = iter([False] * 5 + [True] + [False] * 5)
        activity = AudioActivity(detector=SimpleNamespace(is_speech=lambda frame, rate: next(decisions)), gate=True)
        pcm = struct.pack('<h', 1000) * (320 * 11)
        self.assertEqual(activity.add(pcm), pcm[:640 * 6])

    def test_soft_speech_is_not_replaced_with_zeros_when_vad_misses_it(self):
        activity = AudioActivity(detector=SimpleNamespace(is_speech=lambda frame, rate: False))
        quiet = struct.pack('<h', 40) * 16000
        self.assertEqual(activity.add(quiet), quiet)
        self.assertFalse(activity.overlaps(result('Quiet words')))
        self.assertTrue(activity.has_signal(result('Quiet words')))
        self.assertFalse(activity.has_signal(result('Silence', start=2)))

    def test_drain_preserves_buffered_audio_tail(self):
        activity = AudioActivity(detector=SimpleNamespace(is_speech=lambda frame, rate: True), gate=True)
        audio = struct.pack('<h', 1000) * 320 * 3
        self.assertEqual(activity.add(audio), b'')
        self.assertEqual(activity.drain(), audio)
        self.assertEqual(activity.drain(), b'')

    def test_split_pcm_frames_are_buffered(self):
        activity = AudioActivity(detector=SimpleNamespace(is_speech=lambda frame, rate: True))
        self.assertEqual(activity.add(bytes(200)), b'')
        self.assertEqual(activity.samples, 0)
        activity.add(bytes(440))
        self.assertEqual(activity.samples, 320)

    def test_duplicate_interval_is_not_spoken_again(self):
        utterances = Utterances()
        self.assertEqual(utterances.feed(result('Hello dear')), 'Hello dear')
        for _ in range(3):
            self.assertIsNone(utterances.feed(result('Hello dear')))

    def test_real_repeated_phrase_is_preserved(self):
        utterances = Utterances()
        for start in (0, 2, 4):
            self.assertEqual(utterances.feed(result('Hello dear', start=start)), 'Hello dear')

    def test_low_confidence_preserves_audible_words_and_flags_uncertainty(self):
        utterances = Utterances()
        self.assertIsNone(utterances.feed(result('Hello', confidence=.2, end=False)))
        self.assertEqual(utterances.feed(result('dear', start=1)), 'Hello dear')
        self.assertTrue(utterances.last_uncertain)
        self.assertEqual(utterances.feed(result('Real speech', start=2)), 'Real speech')
        self.assertFalse(utterances.last_uncertain)

    def test_silent_segment_does_not_delete_good_segments(self):
        utterances = Utterances()
        utterances.feed(result('Keep the beginning', end=False))
        utterances.feed(result('noise hallucination', start=1, end=False), audible=False)
        self.assertEqual(utterances.feed(result('and the ending', start=2)), 'Keep the beginning and the ending')

    def test_utterance_end_flushes_without_speech_final_once(self):
        utterances = Utterances()
        utterances.feed(result('The complete sentence', start=5, end=False))
        self.assertEqual(utterances.feed({'type': 'UtteranceEnd'}), 'The complete sentence')
        self.assertEqual(utterances.last_start, 5)
        self.assertIsNone(utterances.feed({'type': 'UtteranceEnd'}))

    def test_continuous_speech_flushes_before_native_limit(self):
        utterances = Utterances()
        first = 'word ' * 110
        utterances.feed(result(first, end=False))
        self.assertEqual(utterances.feed(result(first, start=1, end=False)), first.strip() + ' ' + first.strip())
        self.assertEqual(utterances.feed(result('last part', start=2)), 'last part')

    def test_interim_and_empty_results_never_invent_speech(self):
        utterances = Utterances()
        self.assertIsNone(utterances.feed(result('Hello dear', final=False, end=False)))
        self.assertIsNone(utterances.feed(result('')))

    def test_final_chunks_join_once(self):
        utterances = Utterances()
        self.assertIsNone(utterances.feed(result('Hello', end=False)))
        self.assertIsNone(utterances.feed(result('Hello', end=False)))
        self.assertEqual(utterances.feed(result('dear', start=1)), 'Hello dear')


if __name__ == '__main__':
    unittest.main()
