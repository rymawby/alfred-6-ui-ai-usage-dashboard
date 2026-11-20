"""Exercise OpenCode indexing through the dashboard entry point."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "workflow/claude-usage.alfredui/scripts/dashboard"


def test_opencode_reads_and_refreshes_assistant_usage():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "opencode.db"
        with sqlite3.connect(source) as db:
            db.executescript("CREATE TABLE session (id TEXT, directory TEXT); CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT);")
            db.execute("INSERT INTO session VALUES (?,?)", ("s1", "/work/example"))
            msg = {"role": "assistant", "modelID": "model-1", "providerID": "vendor", "tokens": {"input": 100, "output": 20, "cache": {"read": 40, "write": 10}}}
            db.execute("INSERT INTO message VALUES (?,?,?,?)", ("m1", "s1", 1760000000000, json.dumps(msg)))
            db.execute("INSERT INTO message VALUES (?,?,?,?)", ("m2", "s1", 1760000000000, json.dumps({"role": "user", "tokens": msg["tokens"]})))
        env = dict(os.environ, OPENCODE_DB=str(source), CLAUDE_USAGE_DATA_DIR=str(root / "cache"))
        def refresh():
            return json.loads(subprocess.check_output([sys.executable, str(SCRIPT), "refresh", "all", "tokens", "opencode"], env=env))
        result = refresh()
        with sqlite3.connect(root / "cache/opencode-usage.sqlite") as db:
            assert db.execute("SELECT model,project,inp,out,cr,cw5 FROM msgs").fetchall() == [("vendor/model-1", "example", 100, 20, 40, 10)]
        assert result["variables"]["provider"] == "opencode"
        with sqlite3.connect(source) as db:
            msg["tokens"]["output"] = 55
            db.execute("UPDATE message SET data=? WHERE id='m1'", (json.dumps(msg),))
        refresh()
        with sqlite3.connect(root / "cache/opencode-usage.sqlite") as db:
            assert db.execute("SELECT count(*), sum(out) FROM msgs").fetchone() == (1, 55)
        source.unlink()
        refresh()
        with sqlite3.connect(root / "cache/opencode-usage.sqlite") as db:
            assert db.execute("SELECT count(*) FROM msgs").fetchone()[0] == 0


def test_opencode_without_database_shows_empty_state():
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, OPENCODE_DB=str(Path(temp) / "missing.db"), CLAUDE_USAGE_DATA_DIR=temp)
        result = json.loads(subprocess.check_output([sys.executable, str(SCRIPT), "refresh", "7d", "tokens", "opencode"], env=env))
        assert 'No OpenCode usage found' in json.dumps(result)
        assert not (Path(temp) / "missing.db").exists()
