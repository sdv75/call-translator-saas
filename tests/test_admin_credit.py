import tempfile
import unittest
from pathlib import Path
from server.accounting import Accounting
from tools.grant_minutes import grant_single_account


class CreditTests(unittest.TestCase):
    def test_one_credit_is_idempotent_and_preserves_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db.sqlite3'
            store=Accounting(path)
            account=store.register('test')
            store.db.execute('UPDATE accounts SET balance_ms=0')
            first=grant_single_account(path,100,'test-request')
            self.assertTrue(first['credited_now'])
            self.assertEqual(store.balance(account),6000000)
            self.assertFalse(grant_single_account(path,100,'test-request')['credited_now'])
            self.assertEqual(store.balance(account),6000000)
            self.assertEqual(store.db.execute("SELECT count(*) FROM ledger WHERE kind='trial'").fetchone()[0],1)
            with self.assertRaises(ValueError):grant_single_account(path,99,'test-request')
            store.register('another')
            with self.assertRaises(ValueError):grant_single_account(path,100,'another-request')
            self.assertEqual(store.balance(account),6000000)
            store.close()
