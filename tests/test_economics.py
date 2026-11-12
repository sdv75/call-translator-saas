import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from server.accounting import Accounting
from server.economics import Rates, Usage, scenario


class EconomicsTests(unittest.TestCase):
    def test_silence_still_costs_and_retry_is_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Accounting(Path(temp)/'db.sqlite3')
            try:
                call = store.start(store.register('sub'))
                usage = Usage(store)
                self.assertTrue(usage.stt_sent('send-1', call, 'incoming', 60000))
                self.assertFalse(usage.stt_sent('send-1', call, 'incoming', 60000))
                with self.assertRaises(ValueError):
                    usage.stt_sent('send-1', call, 'incoming', 60001)
                usage.stt_sent('send-2', call, 'outgoing', 60000)
                usage.translation('attempt-1', call, {'prompt_tokens': 100, 'completion_tokens': 50,
                                                       'completion_tokens_details': {'reasoning_tokens': 25}})
                usage.translation('attempt-2', call, {'prompt_tokens': 100, 'completion_tokens': 50}, retry=True)
                rates = Rates(D('0.01'), D('1'), D('2'))  # Artificial test rates.
                report = usage.report(rates)
                self.assertEqual(D(report['estimated_api_cost_usd']), D('0.0204'))
                self.assertIsNone(report['estimated_api_cost_per_speech_minute_usd'])
                self.assertEqual(report['retry_attempts'], 1)
                store.speech(call, 'incoming', 0, 30000)
                self.assertEqual(D(usage.report(rates)['estimated_api_cost_per_speech_minute_usd']), D('0.0408'))
            finally:
                store.close()

    def test_scenario_includes_both_streams_and_free_users(self):
        report = scenario(connected_minutes=D(100), speech_fraction=D('0.25'),
                          rates=Rates(D('0.01'), D(1), D(2)), input_tokens=1000, output_tokens=500,
                          fixed_cost=D(1), free_registration_count=2, free_connected_minutes_each=D(10),
                          price=D(9), fee_fraction=D('0.1'), fee_fixed=D('0.2'), refund_fraction=D('0.1'))
        self.assertEqual(D(report['stt_minutes']), D(240))
        self.assertEqual(D(report['speech_minutes']), D(25))
        self.assertEqual(D(report['margin_after_fixed_usd']), D('3.688'))
        self.assertEqual(report['source'], 'scenario_not_measurement')
