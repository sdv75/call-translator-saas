import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from server.accounting import Accounting, CallRejected


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'accounts.sqlite3'
        self.store = Accounting(self.path)
        self.account = self.store.register('verified-test-sub')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_trial_is_once_across_reopen(self):
        call = self.store.start(self.account)
        self.store.speech(call, 'incoming', 0, 1234)
        self.store.stop(call)
        self.store.close()
        self.store = Accounting(self.path)
        self.assertEqual(self.store.register('verified-test-sub'), self.account)
        self.assertEqual(self.store.balance(self.account), 298766)

    def test_silence_and_repeated_stop_do_not_charge(self):
        call = self.store.start(self.account)
        self.assertEqual(self.store.balance(self.account), 295000)
        self.store.stop(call)
        self.store.stop(call)
        self.assertEqual(self.store.balance(self.account), 300000)

    def test_overlap_retries_and_out_of_order(self):
        call = self.store.start(self.account)
        self.assertEqual(self.store.speech(call, 'incoming', 1000, 2500), 1500)
        self.assertEqual(self.store.speech(call, 'outgoing', 2000, 3000), 500)
        self.assertEqual(self.store.speech(call, 'incoming', 1000, 2500), 0)
        self.assertEqual(self.store.speech(call, 'outgoing', 500, 1100), 500)
        self.store.stop(call)
        self.assertEqual(self.store.balance(self.account), 297500)

    def test_second_call_rejected_without_changes(self):
        call = self.store.start(self.account)
        with self.assertRaisesRegex(CallRejected, 'account_busy'):
            self.store.start(self.account)
        self.assertEqual(self.store.balance(self.account), 295000)
        self.assertEqual(self.store.speech(call, 'incoming', 0, 1), 1)

    def test_concurrent_connections_only_one_call(self):
        barrier = Barrier(2)

        def start():
            store = Accounting(self.path)
            try:
                barrier.wait(timeout=10)
                try:
                    store.start(self.account)
                    return 'started'
                except CallRejected:
                    return 'rejected'
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(start) for _ in range(2)]
            self.assertCountEqual([f.result(timeout=15) for f in futures], ['started', 'rejected'])
        self.assertEqual(self.store.balance(self.account), 295000)

    def test_capacity_and_release(self):
        calls = [self.store.start(self.store.register(f'sub-{i}')) for i in range(5)]
        with self.assertRaisesRegex(CallRejected, 'capacity'):
            self.store.start(self.account)
        self.assertEqual(self.store.balance(self.account), 300000)
        self.store.stop(calls[0], 'network_error')
        self.store.start(self.account)

    def test_exhaustion_never_negative_and_requires_new_start(self):
        call = self.store.start(self.account)
        self.assertEqual(self.store.speech(call, 'incoming', 0, 299999), 299999)
        self.assertEqual(self.store.speech(call, 'outgoing', 299999, 300005), 1)
        self.assertEqual(self.store.balance(self.account), 0)
        with self.assertRaisesRegex(CallRejected, 'call_stopped'):
            self.store.speech(call, 'incoming', 400000, 400001)
        with self.assertRaisesRegex(CallRejected, 'balance_exhausted'):
            self.store.start(self.account)

    def test_restart_returns_only_unused_reserve(self):
        call = self.store.start(self.account)
        self.store.speech(call, 'incoming', 0, 123)
        self.store.recover_after_restart()
        self.store.recover_after_restart()
        self.assertEqual(self.store.balance(self.account), 299877)
        self.store.start(self.account)

    def test_invalid_interval_cannot_change_balance(self):
        call = self.store.start(self.account)
        for start, end in [(-1, 5), (5, 5), (6, 5), (False, 5), (0, 1.5)]:
            with self.assertRaises(ValueError):
                self.store.speech(call, 'incoming', start, end)
        self.store.stop(call)
        self.assertEqual(self.store.balance(self.account), 300000)

    def test_backup_restores_wal_and_reserves(self):
        call = self.store.start(self.account)
        self.store.speech(call, 'incoming', 0, 7001)
        backup = Path(self.temp.name) / 'backup.sqlite3'
        self.store.backup(backup)
        restored = Accounting(backup)
        try:
            restored.recover_after_restart()
            self.assertEqual(restored.balance(self.account), 292999)
        finally:
            restored.close()


if __name__ == '__main__':
    unittest.main()
