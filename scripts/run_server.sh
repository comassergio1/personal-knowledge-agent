#!/usr/bin/env bash
#
# run_server.sh — local production wrapper for the PKA FastAPI server.
#
# Runs the exact single command used to serve the app:
#   uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
#
# - bash strict mode (set -euo pipefail): any error aborts the run.
# - Single-instance guard: a pidfile under /tmp prevents a second instance.
#   flock(1) would be the cleaner primitive, but macOS does not ship it
#   (no /usr/bin/flock on this system), so we use pidfile + kill -0: a live
#   pid refuses startup, a dead pid is reclaimed as stale. The pid survives
#   the exec below, so the file always names the actual server process.
# - stdout/stderr pass through to the caller untouched: launchd redirects
#   them via the plist; a manual run just sees the server output.
set -euo pipefail

# Resolve the repo root from the script location (works from any cwd, and
# whether the script is invoked by absolute or relative path).
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# launchd GUI jobs inherit a minimal PATH; make sure uv is found even when
# this script is the LaunchAgent entry point.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

pidfile="/tmp/my-notebooklm-server.pid"

# --- single-instance lock ------------------------------------------------
if [ -f "$pidfile" ]; then
    old_pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        echo "error: another server instance is already running (pid ${old_pid}; pidfile ${pidfile})" >&2
        echo "error: refusing to start a second instance" >&2
        exit 1
    fi
    echo "note: stale pidfile '${pidfile}' (pid ${old_pid:-unknown} is gone) — reclaiming it" >&2
    rm -f "$pidfile"
fi

echo $$ > "$pidfile"
# Cleans the pidfile if anything fails before exec (including 'uv' missing).
trap 'rm -f "$pidfile"' EXIT

# --- run ------------------------------------------------------------------
exec uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000