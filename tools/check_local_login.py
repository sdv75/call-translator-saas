"""Only aggregate local login evidence; no identifiers, tokens or personal data."""

import json
import sqlite3
import time

from server.config import Settings


def main():
    path = Settings.from_env().database.resolve()
    result = {'accounts_present': False, 'browser_session_present': False}
    if path.is_file():
        database = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
        try:
            result['accounts_present'] = bool(database.execute('SELECT count(*) FROM accounts').fetchone()[0])
            result['browser_session_present'] = bool(database.execute("SELECT count(*) FROM credentials WHERE kind='browser' AND expires_at>?", (int(time.time()),)).fetchone()[0])
        finally:
            database.close()
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Local login evidence unavailable; no credential data printed')
