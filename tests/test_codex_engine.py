"""Behavioral checks for Codex rollout indexing."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "workflow/claude-usage.alfredui/scripts/dashboard"


def test_codex_counter_snapshots_and_appends():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        sessions = root / "codex/sessions"
        sessions.mkdir(parents=True)
        log = sessions / "rollout.jsonl"
        def event(total, cached, output):
            return {"timestamp": "2026-11-20T10:00:00Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": total, "cached_input_tokens": cached, "output_tokens": output}}}}
        records = [{"type": "session_meta", "payload": {"id": "one", "cwd": "/work/example"}}, {"type": "turn_context", "payload": {"model": "gpt-5.4"}}, event(100, 40, 10), event(100, 40, 10)]
        log.write_text("".join(json.dumps(r) + "\n" for r in records))
        env = dict(os.environ, CODEX_HOME=str(root / "codex"), CLAUDE_USAGE_DATA_DIR=str(root / "data"))
        def refresh():
            output = subprocess.check_output([sys.executable, str(SCRIPT), "refresh", "all", "tokens", "codex"], env=env)
            return json.loads(output)
        refresh()
        import sqlite3
        with sqlite3.connect(root / "data/codex-usage.sqlite") as db:
            assert db.execute("select sum(inp),sum(cr),sum(out),count(*) from msgs").fetchone() == (60, 40, 10, 1)
        with log.open("a") as f:
            f.write(json.dumps(event(180, 70, 20)) + "\n")
        result = refresh()
        with sqlite3.connect(root / "data/codex-usage.sqlite") as db:
            assert db.execute("select sum(inp),sum(cr),sum(out),count(*) from msgs").fetchone() == (110, 70, 20, 2)
        assert result["variables"]["provider"] == "codex"
        assert "gpt-5.4" in json.dumps(result)


def test_codex_empty_home_can_switch_provider():
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, CODEX_HOME=temp, CLAUDE_USAGE_DATA_DIR=temp)
        result = json.loads(subprocess.check_output([sys.executable, str(SCRIPT), "refresh", "7d", "tokens", "codex"], env=env))
        assert result["variables"]["provider"] == "codex"
        assert '"claude"' in json.dumps(result)
