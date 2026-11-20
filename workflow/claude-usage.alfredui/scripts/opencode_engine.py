"""Read OpenCode's local SQLite usage records into the dashboard cache."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import engine


def index(db):
    """Replace the cache from a consistent, read-only OpenCode database snapshot."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    source = Path(os.environ.get("OPENCODE_DB") or os.path.join(data_home, "opencode", "opencode.db")).expanduser()
    if not source.is_file():
        with db:
            db.execute("DELETE FROM msgs")
        return
    rows = []
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
        for mid, sid, created, raw, directory in src.execute(
            "SELECT m.id, m.session_id, m.time_created, m.data, s.directory "
            "FROM message m JOIN session s ON s.id = m.session_id"
        ):
            try:
                message = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if message.get("role") != "assistant" or not isinstance(message.get("tokens"), dict):
                continue
            tokens = message["tokens"]
            cache = tokens.get("cache") or {}
            inp = tokens.get("input") or 0
            out = tokens.get("output") or 0
            read = cache.get("read") or 0
            write = cache.get("write") or 0
            if not any((inp, out, read, write)):
                continue
            ts = created / 1000
            local = datetime.fromtimestamp(ts)
            model = message.get("modelID") or "unknown"
            provider = message.get("providerID")
            if provider:
                model = provider + "/" + model
            rows.append((mid, ts, local.strftime("%Y-%m-%d"), local.hour, local.weekday(),
                         model, engine.project_name(directory), sid, inp, out, read, write, 0, 0))
    with db:
        db.execute("DELETE FROM msgs")
        db.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
