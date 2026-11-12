"""Transactional accounting; input intervals must come from trusted server VAD.

This module is deliberately not exposed to clients. Times are integer milliseconds
on a shared call-relative audio timeline, never client-supplied billing claims.
"""

import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


class CallRejected(Exception):
    """A call cannot start without altering an existing call or balance."""


class Accounting:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve() if str(path) != ':memory:' else None
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except BaseException:
            self.db.close()
            raise

    def _migrate(self):
        with self.transaction():
            self.db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
            versions = self.db.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
            if versions not in ([], [(1,)], [(1,), (2,)], [(1,), (2,), (3,)]):
                raise RuntimeError("Unsupported database schema")
            if not versions:
                for sql in SCHEMA:
                    self.db.execute(sql)
                self.db.execute("INSERT INTO schema_version VALUES (1)")
            if (2,) not in versions:
                for sql in AUTH_SCHEMA:
                    self.db.execute(sql)
                self.db.execute("INSERT INTO schema_version VALUES (2)")
            if (3,) not in versions:
                for sql in USAGE_SCHEMA:
                    self.db.execute(sql)
                self.db.execute("INSERT INTO schema_version VALUES (3)")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def register(self, verified_google_sub: str) -> str:
        """Internal only: caller must verify Google identity before calling."""
        if not isinstance(verified_google_sub, str) or not verified_google_sub.strip():
            raise ValueError("Google sub is required")
        with self.transaction():
            row = self.db.execute("SELECT id FROM accounts WHERE google_sub=?", (verified_google_sub,)).fetchone()
            if row:
                return row[0]
            account = uuid.uuid4().hex
            self.db.execute("INSERT INTO accounts VALUES (?, ?, 300000)", (account, verified_google_sub))
            self.db.execute("INSERT INTO ledger(account_id, call_id, kind, amount_ms) VALUES (?, NULL, 'trial', 300000)", (account,))
            return account

    def balance(self, account: str) -> int:
        row = self.db.execute("SELECT balance_ms FROM accounts WHERE id=?", (account,)).fetchone()
        if row is None:
            raise KeyError("Unknown account")
        return row[0]

    def start(self, account: str) -> str:
        with self.transaction():
            if self.db.execute("SELECT 1 FROM calls WHERE account_id=? AND state='active'", (account,)).fetchone():
                raise CallRejected("account_busy")
            if self.db.execute("SELECT count(*) FROM calls WHERE state='active'").fetchone()[0] >= 5:
                raise CallRejected("capacity")
            balance = self.balance(account)
            if balance == 0:
                raise CallRejected("balance_exhausted")
            call = uuid.uuid4().hex
            reserve = min(5000, balance)
            self.db.execute("INSERT INTO calls VALUES (?, ?, 'active', ?, 0, NULL)", (call, account, reserve))
            self._move(account, call, 'reserve', -reserve)
            return call

    def _move(self, account, call, kind, amount):
        self.db.execute("UPDATE accounts SET balance_ms=balance_ms+? WHERE id=?", (amount, account))
        self.db.execute("INSERT INTO ledger(account_id, call_id, kind, amount_ms) VALUES (?, ?, ?, ?)", (account, call, kind, amount))

    def speech(self, call: str, direction: str, start_ms: int, end_ms: int) -> int:
        """Return newly charged duration, unioning both streams and retries.

        Intervals may arrive out of order. Once exhausted, a call is stopped and
        cannot be resumed. No per-fragment rounding or text/audio persistence.
        """
        if direction not in ('incoming', 'outgoing'):
            raise ValueError("Unknown direction")
        if type(start_ms) is not int or type(end_ms) is not int or not 0 <= start_ms < end_ms:
            raise ValueError("Invalid speech interval")
        with self.transaction():
            row = self.db.execute("SELECT account_id, state, reserve_ms FROM calls WHERE id=?", (call,)).fetchone()
            if row is None:
                raise KeyError("Unknown call")
            account, state, reserve = row
            if state != 'active':
                raise CallRejected("call_stopped")
            previous = self.db.execute("SELECT start_ms, end_ms FROM intervals WHERE call_id=? ORDER BY start_ms", (call,)).fetchall()
            merged = []
            for start, end in sorted(previous + [(start_ms, end_ms)]):
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(end, merged[-1][1])
                else:
                    merged.append([start, end])
            delta = sum(e-s for s, e in merged) - sum(e-s for s, e in previous)
            available = self.balance(account)
            charged = min(delta, reserve + available)
            needed = max(0, charged - reserve)
            if needed:
                self._move(account, call, 'reserve', -needed)
            reserve += needed - charged
            self.db.execute("DELETE FROM intervals WHERE call_id=?", (call,))
            self.db.executemany("INSERT INTO intervals VALUES (?, ?, ?)", [(call, s, e) for s, e in merged])
            self.db.execute("UPDATE calls SET reserve_ms=?, speech_ms=speech_ms+? WHERE id=?", (reserve, charged, call))
            # Consumption transfers reserved credit into spent credit, so it has
            # zero effect on the available account balance.
            if charged:
                self.db.execute("INSERT INTO ledger(account_id, call_id, kind, amount_ms) VALUES (?, ?, 'consume', ?)", (account, call, -charged))
            remaining = self.balance(account)
            refill = min(5000-reserve, remaining)
            if refill:
                self._move(account, call, 'reserve', -refill)
                reserve += refill
                self.db.execute("UPDATE calls SET reserve_ms=? WHERE id=?", (reserve, call))
            if reserve == 0 and self.balance(account) == 0:
                self._stop(call, 'balance_exhausted')
            return charged

    def _stop(self, call: str, reason: str):
        row = self.db.execute("SELECT account_id, state, reserve_ms FROM calls WHERE id=?", (call,)).fetchone()
        if row is None:
            raise KeyError("Unknown call")
        account, state, reserve = row
        if state == 'active':
            if reserve:
                self._move(account, call, 'release', reserve)
            self.db.execute("UPDATE calls SET state='stopped', reserve_ms=0, stop_reason=? WHERE id=?", (reason, call))

    def stop(self, call: str, reason: str = 'user_stop'):
        if reason not in ('user_stop', 'network_error', 'provider_error', 'server_restart', 'silence_timeout', 'protocol_error', 'credential_revoked'):
            raise ValueError("Unknown stop reason")
        with self.transaction():
            self._stop(call, reason)

    def recover_after_restart(self):
        """Run once on startup before accepting calls; single-process pilot."""
        with self.transaction():
            for (call,) in self.db.execute("SELECT id FROM calls WHERE state='active'").fetchall():
                self._stop(call, 'server_restart')

    def backup(self, destination: str | Path):
        """SQLite online backup includes committed WAL contents."""
        if self.path is not None and Path(destination).resolve() == self.path:
            raise ValueError('Backup destination must differ from the live database')
        with closing(sqlite3.connect(destination)) as target:
            self.db.backup(target)


SCHEMA = (
    "CREATE TABLE accounts (id TEXT PRIMARY KEY, google_sub TEXT NOT NULL UNIQUE, balance_ms INTEGER NOT NULL CHECK(balance_ms>=0))",
    "CREATE TABLE calls (id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), state TEXT NOT NULL CHECK(state IN ('active','stopped')), reserve_ms INTEGER NOT NULL CHECK(reserve_ms>=0 AND reserve_ms<=5000), speech_ms INTEGER NOT NULL CHECK(speech_ms>=0), stop_reason TEXT)",
    "CREATE UNIQUE INDEX one_active_call ON calls(account_id) WHERE state='active'",
    "CREATE TABLE ledger (id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), call_id TEXT REFERENCES calls(id), kind TEXT NOT NULL CHECK(kind IN ('trial','reserve','release','consume')), amount_ms INTEGER NOT NULL)",
    "CREATE TABLE intervals (call_id TEXT NOT NULL REFERENCES calls(id), start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL CHECK(end_ms>start_ms), PRIMARY KEY(call_id,start_ms))",
)

AUTH_SCHEMA = (
    "CREATE TABLE login_states (state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, nonce TEXT NOT NULL, verifier TEXT NOT NULL, expires_at INTEGER NOT NULL)",
    "CREATE TABLE credentials (token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), kind TEXT NOT NULL CHECK(kind IN ('browser','device')), device_id TEXT UNIQUE, csrf TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)",
    "CREATE TABLE pairing_codes (code_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), expires_at INTEGER NOT NULL)",
)

USAGE_SCHEMA = (
    "CREATE TABLE stt_usage (event_id TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES calls(id), direction TEXT NOT NULL CHECK(direction IN ('incoming','outgoing')), audio_ms INTEGER NOT NULL CHECK(audio_ms>=0), created_at INTEGER NOT NULL)",
    "CREATE TABLE translation_usage (event_id TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES calls(id), input_tokens INTEGER NOT NULL CHECK(input_tokens>=0), output_tokens INTEGER NOT NULL CHECK(output_tokens>=0), reasoning_tokens INTEGER NOT NULL CHECK(reasoning_tokens>=0), retry INTEGER NOT NULL CHECK(retry IN (0,1)), created_at INTEGER NOT NULL)",
)
