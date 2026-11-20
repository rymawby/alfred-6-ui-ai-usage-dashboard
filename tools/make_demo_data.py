#!/usr/bin/env python3
"""Generate synthetic Claude Code transcripts for screenshots and testing.

    python3 tools/make_demo_data.py /tmp/claude-demo

Writes /tmp/claude-demo/projects/<project>/<session>.jsonl with invented projects and
plausible usage. Nothing here comes from real transcripts. Point the workflow at it with
CLAUDE_CONFIG_DIR=/tmp/claude-demo.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

PROJECTS = [("acme-api", 0.30), ("orbit-web", 0.22), ("payments-service", 0.18),
            ("atlas-docs", 0.12), ("mobile-app", 0.11), ("infra-terraform", 0.07)]
MODELS = [("claude-sonnet-5-5", 0.58), ("claude-opus-5-5", 0.31), ("claude-haiku-5-5", 0.07),
          ("claude-sonnet-5", 0.025), ("claude-opus-4-8", 0.015)]
HOUR_W = [0, 0, 0, 0, 0, 0, 0.2, 1, 3, 6, 8, 8, 5, 6, 8, 8, 7, 5, 2, 1.5, 1.2, 1, 0.6, 0.2]


def pick(rnd, table):
    r, acc = rnd.random() * sum(w for _, w in table), 0.0
    for k, w in table:
        acc += w
        if r <= acc:
            return k
    return table[-1][0]


def main(out, days=75, seed=11):
    rnd = random.Random(seed)
    now = datetime.now(timezone.utc).astimezone()
    root = os.path.join(out, "projects")
    os.makedirs(root, exist_ok=True)

    def write_session(project, start, n_msgs, model_bias=None, until=None):
        sid = str(uuid.UUID(int=rnd.getrandbits(128)))
        cwd = "/Users/demo/work/" + project
        d = os.path.join(root, "-Users-demo-work-" + project)
        os.makedirs(d, exist_ok=True)
        ts, ctx = start, rnd.randint(8000, 30000)
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            for i in range(n_msgs):
                ts += timedelta(seconds=rnd.randint(8, 140))
                if until and ts > until:
                    break
                if ts > now - timedelta(seconds=30):
                    break
                model = model_bias or pick(rnd, MODELS)
                ctx = min(ctx + rnd.randint(400, 5000), 480000)
                out_tok = int(min(rnd.lognormvariate(6.2, 0.9), 9000))
                created = rnd.choice([0, 0, 0, rnd.randint(300, 6000), rnd.randint(2000, 20000)])
                u = {"input_tokens": rnd.randint(1, 12), "output_tokens": out_tok,
                     "cache_read_input_tokens": max(ctx - created, 0),
                     "cache_creation_input_tokens": created,
                     "cache_creation": {"ephemeral_1h_input_tokens": created, "ephemeral_5m_input_tokens": 0}}
                rec = {"type": "assistant", "sessionId": sid, "cwd": cwd,
                       "timestamp": ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                       "requestId": "req_" + uuid.UUID(int=rnd.getrandbits(128)).hex[:20],
                       "message": {"id": "msg_" + uuid.UUID(int=rnd.getrandbits(128)).hex[:22],
                                   "model": model, "usage": u}}
                f.write(json.dumps(rec) + "\n")

    for back in range(days, -1, -1):
        day = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        weekend = day.weekday() >= 5
        ramp = 0.35 + 0.65 * (1 - back / float(days)) ** 1.4          # usage grows over time
        sessions = int(round(rnd.uniform(2, 5) * ramp * (0.25 if weekend else 1.0) * 2.2))
        for _ in range(sessions):
            hour = pick(rnd, [(h, w) for h, w in enumerate(HOUR_W)])
            start = day + timedelta(hours=hour, minutes=rnd.randint(0, 59))
            if start > now:
                continue
            write_session(pick(rnd, PROJECTS), start, int(rnd.uniform(40, 230) * ramp + 15))
    # a live session so the 5-hour block ring is active
    write_session("acme-api", now - timedelta(minutes=95), 400, model_bias=None)
    print("wrote synthetic transcripts to", root)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-demo")
