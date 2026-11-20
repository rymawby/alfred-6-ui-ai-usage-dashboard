"""Claude Code usage engine: incremental transcript indexer + query layer.

Reads Claude Code transcripts (~/.claude/projects/**/*.jsonl), de-duplicates
assistant messages by id (a message is logged once per content block), and
keeps a SQLite cache so repeat runs only parse new bytes.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta

BUNDLE_ID = "dev.claude-usage.alfred"

DATA_DIR = os.environ.get("CLAUDE_USAGE_DATA_DIR") or os.environ.get("alfred_workflow_data") or os.path.expanduser(
    "~/Library/Application Support/Alfred/Workflow Data/" + BUNDLE_ID
)
DB_PATH = os.path.join(DATA_DIR, "usage.sqlite")
LOCK_PATH = os.path.join(DATA_DIR, "index.lock")

SCHEMA = """
CREATE TABLE IF NOT EXISTS msgs (
  id TEXT PRIMARY KEY, ts REAL, day TEXT, hour INTEGER, dow INTEGER,
  model TEXT, project TEXT, sid TEXT,
  inp INTEGER, out INTEGER, cr INTEGER, cw5 INTEGER, cw1 INTEGER, ws INTEGER
);
CREATE INDEX IF NOT EXISTS msgs_day ON msgs(day);
CREATE INDEX IF NOT EXISTS msgs_ts ON msgs(ts);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, offset INTEGER);
"""


def config_dirs():
    """Transcript roots. CLAUDE_CONFIG_DIR (comma separated) replaces the defaults, as in Claude Code."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    dirs = [d.strip() for d in env.split(",") if d.strip()] if env else \
        [os.path.expanduser("~/.claude"), os.path.expanduser("~/.config/claude")]
    seen, out = set(), []
    for d in dirs:
        p = os.path.join(os.path.expanduser(d), "projects")
        if p not in seen and os.path.isdir(p):
            seen.add(p)
            out.append(p)
    return out


def project_name(cwd):
    if not cwd:
        return "unknown"
    parts = [p for p in cwd.split("/") if p]
    # worktrees living inside the repo: <repo>/.claude/worktrees/<name>
    for i in range(1, len(parts) - 2):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees":
            return parts[i - 1]
    # worktrees in a shared directory: ~/.t3/worktrees/<repo>/<name>
    for i in range(len(parts) - 2):
        if parts[i].startswith(".") and parts[i + 1] == "worktrees":
            return parts[i + 2]
    return parts[-1]


SCHEMA_VERSION = 3  # bump to force a full reindex


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        db.executescript("DROP TABLE IF EXISTS msgs; DROP TABLE IF EXISTS files;")
        db.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
    db.executescript(SCHEMA)
    return db


_CWD_RE = re.compile(rb'"cwd":"([^"]*)"')


def file_project(path):
    """Project name from the first cwd in a transcript (sessions start at the project root)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(262144)
    except OSError:
        return None
    m = _CWD_RE.search(head)
    return project_name(m.group(1).decode("utf-8", "replace")) if m else None


def _walk(root):
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".jsonl"):
                yield os.path.join(dirpath, f)


def _parse_ts(s):
    # "2026-11-15T22:37:38.279Z" -> epoch
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=__import__("datetime").timezone.utc).timestamp()
    except Exception:
        return None


def index(db=None):
    """Incrementally index new transcript bytes. Returns (new_msgs, seconds) or None if locked."""
    os.makedirs(DATA_DIR, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    t0 = time.time()
    own = db is None
    db = db or connect()
    known = {p: (s, o) for p, s, o in db.execute("SELECT path,size,offset FROM files")}
    rows, filerows = [], []
    for root in config_dirs():
        for path in _walk(root):
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            old = known.get(path)
            start = 0
            if old:
                if old[0] == size:
                    continue
                if size >= old[1]:
                    start = old[1]
            try:
                with open(path, "rb") as fh:
                    fh.seek(start)
                    data = fh.read()
            except OSError:
                continue
            end = data.rfind(b"\n")
            if end < 0:
                continue
            chunk = data[:end + 1]
            fproj = file_project(path)
            for line in chunk.split(b"\n"):
                if b'"usage"' not in line or b'"assistant"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") != "assistant":
                    continue
                m = o.get("message") or {}
                u = m.get("usage")
                model = m.get("model") or ""
                if not u or model.startswith("<") or not model:
                    continue
                ts = _parse_ts(o.get("timestamp", ""))
                if ts is None:
                    continue
                mid = m.get("id") or o.get("uuid")
                key = mid + (":" + o["requestId"] if o.get("requestId") else "")
                cc = u.get("cache_creation") or {}
                cw1 = cc.get("ephemeral_1h_input_tokens", 0) or 0
                cw5 = cc.get("ephemeral_5m_input_tokens", 0) or 0
                tot_cw = u.get("cache_creation_input_tokens", 0) or 0
                if tot_cw > cw1 + cw5:
                    cw5 += tot_cw - cw1 - cw5
                st = u.get("server_tool_use") or {}
                local = datetime.fromtimestamp(ts)
                rows.append((
                    key, ts, local.strftime("%Y-%m-%d"), local.hour, local.weekday(),
                    model, fproj or project_name(o.get("cwd")), o.get("sessionId") or "",
                    u.get("input_tokens", 0) or 0, u.get("output_tokens", 0) or 0,
                    u.get("cache_read_input_tokens", 0) or 0, cw5, cw1,
                    (st.get("web_search_requests", 0) or 0),
                ))
            filerows.append((path, size, start + end + 1))
    with db:
        # later duplicate with >= output tokens wins (final streamed block)
        db.executemany(
            "INSERT INTO msgs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET out=excluded.out, inp=excluded.inp, cr=excluded.cr, "
            "cw5=excluded.cw5, cw1=excluded.cw1, ws=excluded.ws WHERE excluded.out>=msgs.out",
            rows)
        db.executemany(
            "INSERT INTO files VALUES (?,?,?) ON CONFLICT(path) DO UPDATE SET size=excluded.size, offset=excluded.offset",
            filerows)
    if own:
        db.close()
    lock.close()
    return len(rows), time.time() - t0


if __name__ == "__main__":
    r = index()
    print("indexed", r)
    db = connect()
    print(db.execute("SELECT COUNT(*), MIN(day), MAX(day), COUNT(DISTINCT sid) FROM msgs").fetchone())
    for row in db.execute("SELECT model, COUNT(*), SUM(inp), SUM(out), SUM(cr), SUM(cw5), SUM(cw1) FROM msgs GROUP BY model ORDER BY 2 DESC"):
        print(row)


# ---------------------------------------------------------------------------
# Pricing (USD per million tokens): input, output, cache read, cache write 5m, cache write 1h
# Source: Anthropic list prices. Cache writes are 1.25x / 2x input; cache reads
# are 0.1x input except where Anthropic publishes a lower rate.
# ---------------------------------------------------------------------------
PRICES = {
    "fable-5-2": (8.0, 40.0, 0.20, 10.0, 16.0),
    "fable-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "fable-5":   (10.0, 50.0, 1.00, 12.5, 20.0),
    "opus-5-5":  (4.0, 20.0, 0.20, 5.0, 8.0),
    "opus-5":    (5.0, 25.0, 0.50, 6.25, 10.0),
    "opus-4":    (5.0, 25.0, 0.50, 6.25, 10.0),
    "sonnet-5-5": (2.0, 10.0, 0.10, 2.5, 4.0),
    "sonnet-5":  (2.0, 10.0, 0.20, 2.5, 4.0),
    "sonnet-4":  (3.0, 15.0, 0.30, 3.75, 6.0),
    "haiku-5-5": (0.10, 0.50, 0.01, 0.125, 0.20),
    "haiku-4":   (1.0, 5.0, 0.10, 1.25, 2.0),
}
HAIKU55_LONG = (0.50, 2.50, 0.05, 0.625, 1.0)  # prompts over 100K tokens


def model_key(model):
    m = model.replace("claude-", "")
    parts = m.split("-")
    fam = parts[0]
    nums = [p for p in parts[1:] if p.isdigit() and len(p) < 4]
    ver = "-".join(nums[:2])
    return fam, ver


def model_label(model):
    fam, ver = model_key(model)
    return (fam.capitalize() + (" " + ver.replace("-", ".") if ver else "")).strip()


def rates(model, prompt_tokens):
    fam, ver = model_key(model)
    if fam == "haiku" and ver == "5-5" and prompt_tokens > 100_000:
        return HAIKU55_LONG
    if (fam + "-" + ver) in PRICES:
        return PRICES[fam + "-" + ver]
    major = fam + "-" + ver.split("-")[0] if ver else fam
    if major in PRICES:
        return PRICES[major]
    # unknown future model: fall back to the family's newest known rates
    for k in ("opus-5-5", "sonnet-5-5", "haiku-5-5", "fable-5-2"):
        if k.startswith(fam):
            return PRICES[k]
    return PRICES["sonnet-5-5"]


def cost_parts(model, inp, out, cr, cw5, cw1):
    """USD split into (input, output, cache read, cache write)."""
    r = rates(model, inp + cr + cw5 + cw1)
    return (inp * r[0] / 1e6, out * r[1] / 1e6, cr * r[2] / 1e6, (cw5 * r[3] + cw1 * r[4]) / 1e6)


def cost_of(model, inp, out, cr, cw5, cw1):
    return sum(cost_parts(model, inp, out, cr, cw5, cw1))


def saved_by_cache(model, inp, cr):
    r = rates(model, inp + cr)
    return cr * (r[0] - r[2]) / 1e6


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
class Row:
    __slots__ = ("ts", "day", "hour", "dow", "model", "project", "sid",
                 "inp", "out", "cr", "cw", "cost", "saved", "parts")


def load_rows(db, start_day=None, end_day=None):
    q = "SELECT ts,day,hour,dow,model,project,sid,inp,out,cr,cw5,cw1 FROM msgs"
    args = []
    cond = []
    if start_day:
        cond.append("day>=?")
        args.append(start_day)
    if end_day:
        cond.append("day<=?")
        args.append(end_day)
    if cond:
        q += " WHERE " + " AND ".join(cond)
    rows = []
    for ts, day, hour, dow, model, project, sid, inp, out, cr, cw5, cw1 in db.execute(q, args):
        r = Row()
        r.ts, r.day, r.hour, r.dow, r.model, r.project, r.sid = ts, day, hour, dow, model, project, sid
        r.inp, r.out, r.cr, r.cw = inp, out, cr, cw5 + cw1
        r.parts = cost_parts(model, inp, out, cr, cw5, cw1)
        r.cost = sum(r.parts)
        r.saved = saved_by_cache(model, inp, cr)
        rows.append(r)
    return rows


def totals(rows):
    t = {"cost": 0.0, "tokens": 0, "out": 0, "inp": 0, "cr": 0, "cw": 0,
         "msgs": len(rows), "sessions": len({r.sid for r in rows}),
         "days": len({r.day for r in rows}), "saved": 0.0}
    for r in rows:
        t["cost"] += r.cost
        t["out"] += r.out
        t["inp"] += r.inp
        t["cr"] += r.cr
        t["cw"] += r.cw
        t["saved"] += r.saved
    t["tokens"] = t["inp"] + t["out"] + t["cr"] + t["cw"]
    prompt = t["inp"] + t["cr"] + t["cw"]
    t["hit"] = (t["cr"] / prompt) if prompt else 0.0
    return t


def range_bounds(key, today=None):
    today = today or datetime.now().date()
    d = lambda x: x.strftime("%Y-%m-%d")
    if key == "today":
        return d(today), d(today), d(today - timedelta(days=1)), d(today - timedelta(days=1)), "yesterday"
    if key == "30d":
        return d(today - timedelta(days=29)), d(today), d(today - timedelta(days=59)), d(today - timedelta(days=30)), "prev 30d"
    if key == "all":
        return None, d(today), None, None, ""
    return d(today - timedelta(days=6)), d(today), d(today - timedelta(days=13)), d(today - timedelta(days=7)), "prev 7d"


def current_block(db, now=None):
    """Claude's rolling 5-hour usage block: starts at the top of the hour of the
    first message after a 5h gap, runs for 5h. Returns dict or None."""
    now = now or time.time()
    HOUR = 3600.0
    since = now - 48 * HOUR
    rows = []
    for ts, model, inp, out, cr, cw5, cw1 in db.execute(
            "SELECT ts,model,inp,out,cr,cw5,cw1 FROM msgs WHERE ts>=? ORDER BY ts", (since,)):
        rows.append((ts, cost_of(model, inp, out, cr, cw5, cw1), inp + out + cr + cw5 + cw1))
    if not rows:
        return None
    start = None
    last = None
    cur = []
    for ts, c, tk in rows:
        if start is None or ts >= start + 5 * HOUR or (last is not None and ts - last >= 5 * HOUR):
            start = ts - (ts % HOUR)  # floor to the hour (UTC hour == local hour except odd tz)
            cur = []
        cur.append((ts, c, tk))
        last = ts
    active = now < start + 5 * HOUR and (now - last) < 5 * HOUR
    return {
        "start": start, "end": start + 5 * HOUR, "last": last, "active": active,
        "cost": sum(c for _, c, _ in cur), "tokens": sum(t for _, _, t in cur),
        "msgs": len(cur), "elapsed": min(max(now - start, 0), 5 * HOUR),
    }
