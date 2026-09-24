#!/usr/bin/env bash
#
# install_launchagent.sh — manage the user LaunchAgent for the PKA server.
#
# The agent keeps the server alive across reboots and restarts it only after
# an *unexpected* exit (KeepAlive with SuccessfulExit=false), so a clean stop
# does not spin it back up.
#
#   Plist: ~/Library/LaunchAgents/com.my-notebooklm.server.plist
#   Label: com.my-notebooklm.server
#   Logs:  ~/Library/Logs/my-notebooklm/{server,server-err}.log
#
# Validation hook: setting PLIST_DIR=<dir> writes the plist to that directory
# and skips every launchd interaction (used to lint the generated XML without
# touching the system, e.g.):
#   PLIST_DIR="$(mktemp -d)" ./scripts/install_launchagent.sh install
#   plutil -lint "$(printf '%s' "$PLIST_DIR")/com.my-notebooklm.server.plist"
set -euo pipefail

label="com.my-notebooklm.server"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
run_script="$repo_root/scripts/run_server.sh"
plist_dir="${PLIST_DIR:-$HOME/Library/LaunchAgents}"
plist_path="$plist_dir/com.my-notebooklm.server.plist"
log_dir="$HOME/Library/Logs/my-notebooklm"
pidfile="/tmp/my-notebooklm-server.pid"
service_target="gui/$(id -u)/$label"

# PLIST_DIR override => lint/validation mode: plist only, no launchd calls.
lint_mode=0
[ "$plist_dir" != "$HOME/Library/LaunchAgents" ] && lint_mode=1

usage() {
    cat <<'USAGE'
Usage: install_launchagent.sh <command> [options]

Commands:
  install [--force]  write the LaunchAgent plist and register the service
                     with launchd (default). A plain install is a no-op when
                     the plist exists and the service is already loaded;
                     --force rewrites the plist and reloads it.
  uninstall          unload the service and remove the plist; logs are kept.
  status             report launchd/pidfile state and the health-check hint.
  logs               tail the last 50 lines of the server log files.
  -h, --help         show this help; never touches launchd.

Health check once running: curl -s http://localhost:8000/api/v1/health
USAGE
}

is_loaded() {
    launchctl print "$service_target" >/dev/null 2>&1
}

cmd_install() {
    local force=0 arg
    for arg in "$@"; do
        case "$arg" in
            --force) force=1 ;;
            *)
                echo "error: unknown install option '$arg' (only --force is supported)" >&2
                usage >&2
                exit 1
                ;;
        esac
    done

    if [ "$lint_mode" = "1" ]; then
        echo "[lint mode] PLIST_DIR=${plist_dir} — writing plist only, launchd untouched"
    else
        # Refuse to overwrite a live agent unless forced.
        if [ -f "$plist_path" ] && is_loaded && [ "$force" != "1" ]; then
            echo "refusing: $label is already installed and loaded (${plist_path})" >&2
            echo "refusing: nothing changed — use 'install --force' to rewrite and reload it" >&2
            exit 1
        fi
        if [ "$force" = "1" ] && is_loaded; then
            echo "unloading current agent before forced reinstall..."
            launchctl bootout "$service_target" >/dev/null 2>&1 || true
        fi
    fi

    mkdir -p "$plist_dir" "$log_dir"

    cat > "$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${run_script}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${repo_root}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>${log_dir}/server.log</string>
    <key>StandardErrorPath</key>
    <string>${log_dir}/server-err.log</string>
</dict>
</plist>
PLIST

    echo "wrote ${plist_path}"
    if [ "$lint_mode" = "1" ]; then
        echo "[lint mode] launchd untouched; validate with: plutil -lint '${plist_path}'"
        return 0
    fi

    # Modern bootstrap flow; legacy 'load -w' is the fallback. A defensive
    # bootout clears a ghost registration left behind by a racy uninstall
    # (bootout returning 0 while the label lingers), which would otherwise
    # make bootstrap fail with "service already loaded".
    launchctl bootout "$service_target" 2>/dev/null || true
    if launchctl bootstrap "gui/$(id -u)" "$plist_path" 2>/dev/null; then
        echo "bootstrapped $label"
    elif launchctl load -w "$plist_path" 2>/dev/null; then
        echo "loaded $label (legacy 'launchctl load -w' fallback)"
    else
        echo "error: could not register $label with launchd (bootstrap and load both failed)" >&2
        exit 1
    fi
    launchctl enable "$service_target" 2>/dev/null || true

    if launchctl print "$service_target" >/dev/null 2>&1; then
        echo "verified: $label is loaded (launchctl print gui/$(id -u)/$label)"
    else
        echo "warning: plist written, but 'launchctl print' could not confirm the service is loaded" >&2
    fi
    echo "logs:   ${log_dir}/{server.log,server-err.log}"
    echo "health: curl -s http://localhost:8000/api/v1/health"
}

cmd_uninstall() {
    if is_loaded; then
        launchctl bootout "$service_target" >/dev/null 2>&1 \
            && echo "unloaded $label" \
            || echo "note: 'launchctl bootout' errored — the service may already be gone"
    else
        echo "note: $label was not loaded — nothing to unload"
    fi
    if [ -f "$plist_path" ]; then
        rm -f "$plist_path"
        echo "removed ${plist_path}"
    else
        echo "note: no plist at ${plist_path} — nothing to remove"
    fi
    echo "logs kept at ${log_dir}/{server.log,server-err.log} (remove manually if unwanted)"
}

cmd_status() {
    echo "== launchd =="
    if is_loaded; then
        echo "loaded:   ${service_target}"
    else
        echo "not loaded: $label is not registered with launchd"
    fi

    echo
    echo "== server process =="
    local pid=""
    [ -f "$pidfile" ] && pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "running:  pid ${pid} (pidfile ${pidfile})"
    elif [ -n "$pid" ]; then
        echo "not running (stale pidfile: pid ${pid} is no longer alive)"
    else
        echo "not running (no pidfile at ${pidfile})"
    fi

    echo
    echo "== health =="
    echo "hint: curl -s http://localhost:8000/api/v1/health"
}

cmd_logs() {
    echo "== ${log_dir}/server.log (stdout) =="
    if [ -s "$log_dir/server.log" ]; then
        tail -n 50 "$log_dir/server.log"
    else
        echo "(empty or not created yet)"
    fi
    echo
    echo "== ${log_dir}/server-err.log (stderr) =="
    if [ -s "$log_dir/server-err.log" ]; then
        tail -n 50 "$log_dir/server-err.log"
    else
        echo "(empty or not created yet)"
    fi
}

# --- dispatch --------------------------------------------------------------
cmd="${1:-install}"
case "$cmd" in
    install) shift || true; cmd_install "$@" ;;
    uninstall) cmd_uninstall ;;
    status) cmd_status ;;
    logs) cmd_logs ;;
    -h | --help | help) usage ;;
    *)
        echo "error: unknown command '$cmd'" >&2
        usage >&2
        exit 1
        ;;
esac