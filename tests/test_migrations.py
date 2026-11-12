import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.accounting import Accounting, SCHEMA


class MigrationTests(unittest.TestCase):
    def test_upgrade_preserves_original_trial_and_balance(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'old.sqlite3'
            connection = sqlite3.connect(path)
            try:
                connection.execute('CREATE TABLE schema_version(version INTEGER PRIMARY KEY)')
                connection.execute('INSERT INTO schema_version VALUES(1)')
                for sql in SCHEMA:
                    connection.execute(sql)
                connection.execute("INSERT INTO accounts VALUES('account', 'google-sub', 123456)")
                connection.execute("INSERT INTO ledger(account_id,kind,amount_ms) VALUES('account','trial',300000)")
                connection.commit()
            finally:
                connection.close()
            store = Accounting(path)
            try:
                self.assertEqual(store.register('google-sub'), 'account')
                self.assertEqual(store.balance('account'), 123456)
                self.assertEqual(store.db.execute("SELECT count(*) FROM ledger WHERE kind='trial'").fetchone()[0], 1)
                self.assertEqual(store.db.execute('SELECT max(version) FROM schema_version').fetchone()[0], 3)
                with self.assertRaisesRegex(ValueError, 'differ'):
                    store.backup(path)
            finally:
                store.close()

    def test_unknown_schema_is_rejected_without_locked_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'future.sqlite3'
            connection = sqlite3.connect(path)
            try:
                connection.execute('CREATE TABLE schema_version(version INTEGER PRIMARY KEY)')
                connection.execute('INSERT INTO schema_version VALUES(999)')
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
                Accounting(path)
            path.unlink()
