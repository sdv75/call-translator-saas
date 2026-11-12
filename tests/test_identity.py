import tempfile
import unittest
from pathlib import Path

from server.accounting import Accounting
from server.identity import Identity


class IdentityTests(unittest.TestCase):
    def test_expiration_and_hashed_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Accounting(Path(temp)/'db.sqlite3')
            try:
                now = [1000]
                identity = Identity(store, clock=lambda: now[0])
                account = store.register('verified-sub')
                token = identity.issue_browser(account)
                state, browser, _, _ = identity.new_login()
                code = identity.new_pairing(account)
                text = '\n'.join(store.db.iterdump())
                self.assertNotIn(token, text)
                self.assertNotIn(state, text)
                self.assertNotIn(browser, text)
                self.assertNotIn(code, text)
                now[0] += 86401
                self.assertIsNone(identity.authenticate(token, 'browser'))
                self.assertIsNone(identity.consume_login(state, browser))
                self.assertIsNone(identity.redeem_pairing(code))
            finally:
                store.close()
