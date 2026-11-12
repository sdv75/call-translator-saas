"""One-off, idempotent administrative credit; never a public HTTP endpoint."""
import sqlite3
from contextlib import closing


def grant_single_account(database, minutes, reference):
    if type(minutes) is not int or not 0 < minutes <= 10000 or not isinstance(reference,str) or not 1 <= len(reference) <= 120:
        raise ValueError('Invalid credit')
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        accounts=connection.execute('SELECT id FROM accounts').fetchall()
        if len(accounts)!=1:
            raise ValueError('Exactly one account required; refusing ambiguous credit')
        account=accounts[0][0]
        connection.execute('CREATE TABLE IF NOT EXISTS administrative_credits (reference TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), amount_ms INTEGER NOT NULL CHECK(amount_ms>0), created_at INTEGER NOT NULL DEFAULT (unixepoch()))')
        previous=connection.execute('SELECT account_id,amount_ms FROM administrative_credits WHERE reference=?',(reference,)).fetchone()
        amount=minutes*60000
        if previous and previous!=(account,amount):
            raise ValueError('Credit reference conflict')
        if not previous:
            connection.execute('INSERT INTO administrative_credits(reference,account_id,amount_ms) VALUES (?,?,?)',(reference,account,amount))
            connection.execute('UPDATE accounts SET balance_ms=balance_ms+? WHERE id=?',(amount,account))
        balance=connection.execute('SELECT balance_ms FROM accounts WHERE id=?',(account,)).fetchone()[0]
    return {'credited_now':not bool(previous),'credit_minutes':minutes,'balance_ms':balance}
