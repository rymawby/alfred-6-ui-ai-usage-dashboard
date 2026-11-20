"""Index Codex rollout token counters into the dashboard's local SQLite cache."""
from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime

import engine


def index(db):
    """Re-read changed rollouts so cumulative counters and context survive appends."""
    root = os.path.join(os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex")), "sessions")
    os.makedirs(engine.DATA_DIR, exist_ok=True)
    with open(os.path.join(engine.DATA_DIR, "codex-index.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        known = {p: (s, o) for p, s, o in db.execute("SELECT path,size,offset FROM files")}
        for path in engine._walk(root):
            try:
                stat = os.stat(path)
                if known.get(path) == (stat.st_size, stat.st_mtime_ns):
                    continue
                with open(path, "rb") as fh:
                    lines = fh.readlines()
            except OSError:
                continue
            model, project, sid = "unknown", "unknown", path
            previous = [0, 0, 0, 0]
            rows = []
            for number, line in enumerate(lines):
                if not line.endswith(b"\n"):
                    break
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                payload = record.get("payload") or {}
                if record.get("type") == "session_meta":
                    project = engine.project_name(payload.get("cwd"))
                    sid = payload.get("id") or path
                elif record.get("type") == "turn_context":
                    model = payload.get("model") or model
                    project = engine.project_name(payload.get("cwd")) if payload.get("cwd") else project
                elif record.get("type") == "event_msg" and payload.get("type") == "token_count":
                    usage = (payload.get("info") or {}).get("total_token_usage")
                    if not usage:
                        continue
                    values = [usage.get(k, 0) or 0 for k in ("input_tokens", "cached_input_tokens", "output_tokens", "cache_write_input_tokens")]
                    if any(v < p for v, p in zip(values, previous)):
                        previous = [0, 0, 0, 0]
                    delta = [v - p for v, p in zip(values, previous)]
                    previous = values
                    if not any(delta):
                        continue
                    ts = engine._parse_ts(record.get("timestamp", ""))
                    if ts is None:
                        continue
                    local = datetime.fromtimestamp(ts)
                    # Cached and cache-write tokens are included in Codex's input total.
                    uncached = max(0, delta[0] - delta[1] - delta[3])
                    rows.append((path + ":" + str(number), ts, local.strftime("%Y-%m-%d"), local.hour,
                                 local.weekday(), model, project, sid, uncached, delta[2], delta[1], delta[3], 0, 0))
            with db:
                db.execute("DELETE FROM msgs WHERE substr(id, 1, ?) = ?", (len(path) + 1, path + ":"))
                db.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?)", (path, stat.st_size, stat.st_mtime_ns))
