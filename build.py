#!/usr/bin/env python3
"""Build the AI Usage Stats Alfred workflow.

    python3 build.py          -> writes workflow/info.plist, workflow/icon.png,
                                 and dist/AI-usage-stats.alfredworkflow

Double-click the .alfredworkflow to install it into Alfred 6.
"""
from __future__ import annotations

import math
import os
import plistlib
import struct
import zipfile
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(ROOT, "workflow")
DIST = os.path.join(ROOT, "dist")

BUNDLE_ID = "dev.claude-usage.alfred"
UID_KEYWORD = "5C2B8E0A-3F59-4E2B-9E57-0D6B7A1C4A01"
UID_HOTKEY = "5C2B8E0A-3F59-4E2B-9E57-0D6B7A1C4A02"
UID_EXTERNAL = "5C2B8E0A-3F59-4E2B-9E57-0D6B7A1C4A03"
UID_UI = "5C2B8E0A-3F59-4E2B-9E57-0D6B7A1C4A04"

README = """# AI Usage Stats

A native Alfred UI dashboard for Claude Code, Codex and OpenCode usage.

Type the keyword (default `usage`) to open it, then select Claude, Codex or OpenCode.
Claude shows estimated spend, tokens, messages,
cache efficiency, a stacked time chart by model family, model mix, your current
5-hour block, top projects and a weekly activity heatmap. Codex shows local token
usage, model mix, sessions, projects and activity, without estimated cost or limits.
OpenCode shows the same token statistics from its local SQLite database.

## Data
Everything is read locally from `~/.claude/projects/**/*.jsonl` (also honours
`CLAUDE_CONFIG_DIR`) and Codex sessions in `~/.codex/sessions` (or `CODEX_HOME`).
OpenCode is read from ~/.local/share/opencode/opencode.db (or OPENCODE_DB).
Nothing leaves your machine. The first launch indexes
your history once; later refreshes re-read changed Codex sessions and new Claude bytes.

Costs are API-equivalent estimates at Anthropic list prices. If you are on a
subscription this is the value of your usage, not what you were billed.

## Controls
- `1` to `4` with Cmd: Today / 7 days / 30 days / All time
- Cmd+R: refresh now (it also refreshes every 30 seconds)
- Esc: close

## Other ways in
- Set a hotkey on the unassigned Hotkey object.
- External trigger `dashboard`:
  `tell application id "com.runningwithcrayons.Alfred" to run trigger "dashboard" in workflow "dev.claude-usage.alfred"`
"""


# --------------------------------------------------------------------- icon
def make_icon(path, size=512):
    """Draw a neutral blue statistics icon with antialiased white bars."""
    SS = 3
    top, bot = (75, 119, 181), (45, 68, 125)
    radius = size * 0.225
    cx = cy = size / 2.0

    def inside_round(x, y):
        dx = max(abs(x - cx) - (size / 2.0 - radius), 0.0)
        dy = max(abs(y - cy) - (size / 2.0 - radius), 0.0)
        return dx * dx + dy * dy <= radius * radius

    def in_bar(x, y, left, top, right, bottom):
        radius = size * 0.035
        cx = min(max(x, left + radius), right - radius)
        cy = min(max(y, top + radius), bottom - radius)
        return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2

    raw = bytearray()
    for py in range(size):
        raw.append(0)
        for px in range(size):
            cov = white = 0
            for sy_ in range(SS):
                for sx_ in range(SS):
                    x = px + (sx_ + 0.5) / SS
                    y = py + (sy_ + 0.5) / SS
                    if inside_round(x, y):
                        cov += 1
                        if any(in_bar(x, y, size * left, size * top_, size * right, size * 0.72)
                               for left, top_, right in ((0.22, 0.49, 0.36), (0.43, 0.30, 0.57), (0.64, 0.40, 0.78))):
                            white += 1
            n = SS * SS
            t = py / float(size)
            base = [top[i] + (bot[i] - top[i]) * t for i in range(3)]
            wf = white / float(cov) if cov else 0.0
            col = [int(round(base[i] * (1 - wf) + 255 * wf)) for i in range(3)]
            raw += bytes(col) + bytes([int(round(255 * cov / n))])

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


# -------------------------------------------------------------------- plist
def make_plist(path):
    def conn(dest):
        return [{"destinationuid": dest, "modifiers": 0, "modifiersubtext": "", "vitoclose": False}]

    info = {
        "bundleid": BUNDLE_ID,
        "name": "AI Usage Stats",
        "description": "Your Claude Code, Codex and OpenCode usage as a native Alfred UI dashboard",
        "category": "Productivity",
        "createdby": "",
        "webaddress": "",
        "version": "1.0.0",
        "disabled": False,
        "readme": README,
        "connections": {UID_KEYWORD: conn(UID_UI), UID_HOTKEY: conn(UID_UI), UID_EXTERNAL: conn(UID_UI)},
        "objects": [
            {"type": "alfred.workflow.input.keyword", "uid": UID_KEYWORD, "version": 1,
             "config": {"argumenttype": 2, "keyword": "{var:usage_keyword}", "skipuniversalaction": True,
                        "subtext": "Spend, tokens, models, projects and your 5-hour block",
                        "text": "AI Usage Stats", "withspace": False}},
            {"type": "alfred.workflow.trigger.hotkey", "uid": UID_HOTKEY, "version": 2,
             "config": {"action": 0, "argument": 0, "focusedappvariable": False, "focusedappvariablename": "",
                        "hotkey": 0, "hotmod": 0, "hotstring": "", "leftcursor": False, "modsmode": 0,
                        "relatedAppsMode": 0}},
            {"type": "alfred.workflow.trigger.external", "uid": UID_EXTERNAL, "version": 1,
             "config": {"availableviaurlhandler": False, "triggerid": "dashboard"}},
            {"type": "alfred.workflow.userinterface.alfredui", "uid": UID_UI, "version": 1,
             "config": {"launchmode": 1, "path": "claude-usage.alfredui", "stackview": False}},
        ],
        "uidata": {
            UID_KEYWORD: {"xpos": 40.0, "ypos": 40.0},
            UID_HOTKEY: {"xpos": 40.0, "ypos": 180.0},
            UID_EXTERNAL: {"xpos": 40.0, "ypos": 320.0},
            UID_UI: {"xpos": 340.0, "ypos": 180.0},
        },
        "userconfigurationconfig": [
            {"label": "Keyword", "type": "textfield", "variable": "usage_keyword",
             "description": "Type this in Alfred to open the dashboard.",
             "config": {"default": "usage", "placeholder": "usage", "required": True, "trim": True}},
        ],
    }
    with open(path, "wb") as f:
        plistlib.dump(info, f, sort_keys=False)


# -------------------------------------------------------------------- zip
def package(out):
    os.makedirs(DIST, exist_ok=True)
    skip_dirs = {"__pycache__"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirs, files in os.walk(WF):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fn in sorted(files):
                if fn.endswith(".pyc") or fn == ".DS_Store":
                    continue
                full = os.path.join(dirpath, fn)
                arc = os.path.relpath(full, WF)
                zi = zipfile.ZipInfo.from_file(full, arc)
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    z.writestr(zi, fh.read())


if __name__ == "__main__":
    icon = os.path.join(WF, "icon.png")
    make_icon(icon)
    print("wrote", icon)
    make_plist(os.path.join(WF, "info.plist"))
    out = os.path.join(DIST, "AI-usage-stats.alfredworkflow")
    package(out)
    print("built", out)
