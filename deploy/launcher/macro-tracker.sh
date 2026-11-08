#!/usr/bin/env bash
# Phase 7: desktop launcher for the Streamlit app.
#   macro-tracker.sh         start the app if it isn't running, then open it
#   macro-tracker.sh stop    stop the app
# Runs Streamlit in the background (log: ~/.cache/macro-tracker.log) with a
# watchdog: once no browser tab has been connected for GRACE seconds (30 by
# default, so a page refresh doesn't count), the app shuts itself down.
# "Stop" in the icon's right-click menu stops it right away.
# @author Tony Shin <tonyshin4065@gmail.com>

APP_DIR="${APP_DIR:-$HOME/calorie-tracker/Calorie-Macro-Tracker}"   # symlink, no spaces
STREAMLIT="${STREAMLIT:-$HOME/venv/bin/streamlit}"
PORT="${PORT:-8501}"
URL="http://localhost:$PORT"
LOG="$HOME/.cache/macro-tracker.log"
PATTERN="streamlit run src/python/app.py"
GRACE="${GRACE:-30}"        # seconds with no open tab before shutting down
CHECK_EVERY=5

notify() {
    command -v notify-send >/dev/null && notify-send -i "$HOME/.local/share/icons/macro-tracker.svg" "Macro Tracker" "$1"
    echo "$1"
}

is_up() {   # is something listening on the port? (bash built-in, no curl needed)
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null
}

open_tabs() {   # browser connections to the app (each open tab holds one)
    ss -Htn state established "( sport = :$PORT )" 2>/dev/null | wc -l
}

watchdog() {
    trap '' HUP                       # survive the terminal closing
    local seen=0 idle=0
    while pgrep -f "$PATTERN" >/dev/null; do
        sleep "$CHECK_EVERY"
        if [ "$(open_tabs)" -gt 0 ]; then
            seen=1; idle=0
        else
            idle=$((idle + CHECK_EVERY))
        fi
        # tab closed for GRACE s, or the page never connected within 2 min
        if { [ "$seen" -eq 1 ] && [ "$idle" -ge "$GRACE" ]; } ||
           { [ "$seen" -eq 0 ] && [ "$idle" -ge 120 ]; }; then
            pkill -f "$PATTERN"
            notify "Closed: no open tabs."
            break
        fi
    done
}

if [ "$1" = "stop" ]; then
    if pkill -f "$PATTERN"; then notify "Stopped."; else notify "It wasn't running."; fi
    exit 0
fi

if ! is_up; then
    if [ ! -x "$STREAMLIT" ] || [ ! -d "$APP_DIR" ]; then
        notify "Can't find the app or Streamlit. Check APP_DIR and STREAMLIT in macro-tracker.sh."
        exit 1
    fi
    mkdir -p "$(dirname "$LOG")"
    cd "$APP_DIR" || exit 1
    # headless: we open the browser ourselves, so a second click doesn't open two tabs
    nohup "$STREAMLIT" run src/python/app.py \
        --server.headless true --server.port "$PORT" >"$LOG" 2>&1 &
    for _ in $(seq 1 40); do          # wait up to 20 s for it to come up
        is_up && break
        sleep 0.5
    done
    if ! is_up; then
        notify "Didn't start. See ~/.cache/macro-tracker.log"
        exit 1
    fi
    watchdog >/dev/null 2>&1 &        # only the run that started the app watches it
    disown
fi

xdg-open "$URL" >/dev/null 2>&1 &
