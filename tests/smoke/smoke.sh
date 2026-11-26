#!/bin/sh
# macOS / Linux smoke test for dore: install from this checkout, then save and recall a fact through
# the real Claude Code hook command. Same checks as smoke.ps1 (Windows).
#
#   sh tests/smoke/smoke.sh
#
# Needs Node 18+. Uses its own dore folder, so it does not touch a real dore install.
set -eu
REPO=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
export DORE_HOME="$WORK/home" DORE_PIP_SPEC="$REPO" DORE_MARKETPLACE="$REPO"
FAIL=0
check() { if [ "$2" = 1 ]; then r=PASS; else r=FAIL; FAIL=1; fi; printf '%-52s %s  %s\n' "$1" "$r" "$3" >> "$WORK/results"; }

echo "== 1. install (from $REPO)"
start=$(date +%s)
node "$REPO/npm/bin/dore-memory.js" install </dev/null
ok=0; [ -x "$DORE_HOME/.venv/bin/dore-hook" ] && ok=1
check "install" "$ok" "$(( $(date +%s) - start )) s"

echo "== 2. hook command"
CMD=$(node -e 'console.log(require(process.argv[1]).hooks.UserPromptSubmit[0].hooks[0].command)' "$REPO/plugin/hooks/hooks.json")
mkdir -p "$WORK/project"
# Runs the hook like Claude Code does; prints "<seconds> <output>".
prompt() {
  node -e '
    const [cmd, text, session, cwd] = process.argv.slice(1);
    const input = JSON.stringify({ prompt: text, session_id: session, cwd, hook_event_name: "UserPromptSubmit" });
    const t = Date.now();
    const r = require("child_process").spawnSync("sh", ["-c", cmd], { input, encoding: "utf8" });
    console.log(((Date.now() - t) / 1000).toFixed(2) + " " + (r.stdout || "").replace(/\n/g, " "));
  ' "$CMD" "$1" "$2" "$WORK/project"
}
out=$(prompt "Our billing service runs on port 6200." smoke-1); s=${out%% *}
ok=$(node -e 'console.log(+process.argv[1] < 20 ? 1 : 0)' "$s")
check "first prompt under 20 s (Claude Code's hook limit)" "$ok" "$s s"
out=$(prompt "What port does the billing service use?" smoke-2); s=${out%% *}
ok=0; case "$out" in *6200*) ok=1 ;; esac
check "recall in a new session" "$ok" "$s s"
best=99
for i in 1 2 3; do out=$(prompt "What port does the billing service use?" "smoke-w$i"); best=$(node -e 'console.log(Math.min(+process.argv[1], +process.argv[2]))' "$best" "${out%% *}"); done
ok=$(node -e 'console.log(+process.argv[1] < 1 ? 1 : 0)' "$best")
check "warm helper" "$ok" "best $best s"

echo "== 3. status and uninstall"
node "$REPO/npm/bin/dore-memory.js" status
node "$REPO/npm/bin/dore-memory.js" uninstall
ok=0; [ ! -d "$DORE_HOME/.venv" ] && [ -f "$DORE_HOME/data/memory.db" ] && ok=1
check "uninstall keeps memory" "$ok" ""
ok=0; [ ! -e "$DORE_HOME/data/hook.sock" ] && ok=1
check "uninstall stopped the helper" "$ok" ""

echo; cat "$WORK/results"
rm -rf "$WORK"
exit "$FAIL"
