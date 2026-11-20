#!/bin/zsh
# Render the dashboard from SYNTHETIC data and capture only its window.
#   tools/screenshot.sh [light|dark|both]    -> docs/screenshot-light.png / docs/screenshot-dark.png
# Needs macOS with Alfred 6 installed. The demo config reaches the scripts through ui.json
# variables (open --env is ignored when Alfred is already running), and the capture is
# deleted unless the isolated demo database exists and contains only the invented projects.
set -e
HERE=${0:A:h}; ROOT=${HERE:h}
MODE=${1:-both}
WORK=$(mktemp -d)
python3 $HERE/make_demo_data.py $WORK/claude >/dev/null
BUNDLE=$ROOT/workflow/claude-usage.alfredui
REAL_DB="$HOME/Library/Application Support/Alfred/Workflow Data/dev.claude-usage.alfred"

shoot() {  # $1 = light|dark
  local ui=$WORK/ui-$1.alfredui data=$WORK/data-$1 out=$ROOT/docs/screenshot-$1.png
  rm -rf $ui; cp -R $BUNDLE $ui
  python3 - "$ui/ui.json" "$1" "$WORK/claude" "$data" <<'PY'
import json, sys
p, mode, cfg, data = sys.argv[1:5]
u = json.load(open(p))
u["window"]["appearance"] = mode
u["bundleid"] = "dev.claude-usage.alfred.screenshot"
for k in ("range", "metric"):
    u["variablesconfig"][k]["persist"] = False
u["variablesconfig"]["range"]["default"] = "30d"
for k, v in (("CLAUDE_CONFIG_DIR", cfg), ("CLAUDE_USAGE_DATA_DIR", data)):
    u["variablesconfig"][k] = {"default": v, "scriptenv": True}
    u.setdefault("variables", {})[k] = v
json.dump(u, open(p, "w"), indent=2)
PY
  osascript -e 'tell application "Alfred UI" to quit' 2>/dev/null || true; sleep 1.5
  open $ui
  sleep 7
  id=$(osascript -l JavaScript $HERE/winid.js | awk '{print $1}')
  [ -z "$id" ] && { echo "no Alfred UI window found"; return 1; }
  mkdir -p $ROOT/docs
  screencapture -x -o -l $id $out
  osascript -e 'tell application "Alfred UI" to quit' 2>/dev/null || true; sleep 1
  # safety: the capture is only valid if it came from the isolated demo data
  projects=$(sqlite3 $data/usage.sqlite "select group_concat(distinct project) from msgs" 2>/dev/null || true)
  if [[ -z "$projects" || -d "$REAL_DB" ]]; then
    rm -f $out; echo "ABORT: demo database missing or real data directory was touched; capture deleted"; return 1
  fi
  for p in ${(s:,:)projects}; do
    case $p in acme-api|orbit-web|payments-service|atlas-docs|mobile-app|infra-terraform) ;;
      *) rm -f $out; echo "ABORT: unexpected project '$p' in demo data; capture deleted"; return 1;; esac
  done
  echo "wrote docs/screenshot-$1.png  (projects: $projects)"
}
[[ $MODE == light || $MODE == both ]] && shoot light
[[ $MODE == dark || $MODE == both ]] && shoot dark
rm -rf $WORK
