"""Aggregate only: decide whether the owned development server is idle."""
import json
import sqlite3
from server.config import Settings

path=Settings.from_env().database.resolve()
with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as database:
    active=database.execute("SELECT count(*) FROM calls WHERE state='active'").fetchone()[0]
print(json.dumps({'local_active_calls':active}))
