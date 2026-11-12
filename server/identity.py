"""Hashed, expiring, revocable credentials and one-use login/pairing state."""

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass

from .accounting import Accounting


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class Principal:
    account: str
    kind: str
    csrf: str
    device: str | None


class Identity:
    def __init__(self, store: Accounting, clock=time.time):
        self.store = store
        self.clock = clock

    def new_login(self):
        state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        with self.store.transaction():
            self.store.db.execute('DELETE FROM login_states WHERE expires_at<=?', (int(self.clock()),))
            self.store.db.execute('INSERT INTO login_states VALUES (?, ?, ?, ?, ?)',
                                  (digest(state), digest(browser), nonce, verifier, int(self.clock())+600))
        return state, browser, nonce, verifier

    def consume_login(self, state: str, browser: str):
        with self.store.transaction():
            row = self.store.db.execute('SELECT browser_hash, nonce, verifier, expires_at FROM login_states WHERE state_hash=?', (digest(state),)).fetchone()
            if not row or row[3] <= self.clock() or not secrets.compare_digest(row[0], digest(browser)):
                return None
            self.store.db.execute('DELETE FROM login_states WHERE state_hash=?', (digest(state),))
            return row[1], row[2]

    def issue_browser(self, account: str):
        with self.store.transaction():
            return self._issue(account, 'browser')[0]

    def _issue(self, account: str, kind: str):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        device = uuid.uuid4().hex if kind == 'device' else None
        now = int(self.clock())
        self.store.db.execute('INSERT INTO credentials VALUES (?, ?, ?, ?, ?, ?, ?)',
                              (digest(token), account, kind, device, csrf, now, now + (86400 if kind == 'browser' else 30*86400)))
        return token, device

    def authenticate(self, token: str, kind: str):
        row = self.store.db.execute('SELECT account_id, kind, csrf, device_id FROM credentials WHERE token_hash=? AND kind=? AND expires_at>?',
                                    (digest(token), kind, int(self.clock()))).fetchone()
        return Principal(*row) if row else None

    def new_pairing(self, account: str):
        code = secrets.token_urlsafe(32)
        with self.store.transaction():
            self.store.db.execute('DELETE FROM pairing_codes WHERE account_id=? OR expires_at<=?', (account, int(self.clock())))
            self.store.db.execute('INSERT INTO pairing_codes VALUES (?, ?, ?)', (digest(code), account, int(self.clock())+300))
        return code

    def redeem_pairing(self, code: str):
        with self.store.transaction():
            row = self.store.db.execute('SELECT account_id FROM pairing_codes WHERE code_hash=? AND expires_at>?', (digest(code), int(self.clock()))).fetchone()
            if not row:
                return None
            self.store.db.execute('DELETE FROM pairing_codes WHERE code_hash=?', (digest(code),))
            return self._issue(row[0], 'device')

    def revoke_token(self, token: str):
        with self.store.transaction():
            self.store.db.execute('DELETE FROM credentials WHERE token_hash=?', (digest(token),))

    def revoke_device(self, account: str, device: str):
        with self.store.transaction():
            return self.store.db.execute('DELETE FROM credentials WHERE account_id=? AND device_id=?', (account, device)).rowcount > 0
