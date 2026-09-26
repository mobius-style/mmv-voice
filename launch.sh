#!/bin/bash
# =============================================================
# Whisper + MOBIUS MMV 12B QAT Voice Formatting Tool launcher
# =============================================================
# Usage:
#   First time only: chmod +x launch.sh
#   Start:           double-click launch.sh
#                    (choose "Run" in the file manager)
# =============================================================

# Change to this script's own directory (makes relative paths reliable)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Settings written by install.sh (MMV_REPO); local file, never committed
[ -f "$SCRIPT_DIR/.mmv-voice.env" ] && . "$SCRIPT_DIR/.mmv-voice.env"

# ── Auto-detect the Python environment ──────────────────────
# Priority: conda(whisper) > conda(base) > venv(.venv) > system python3
find_python() {
    # If conda is available, prefer an environment named whisper
    if command -v conda &>/dev/null; then
        CONDA_BASE=$(conda info --base 2>/dev/null)
        for ENV_NAME in whisper whisper_env audio base; do
            PY="$CONDA_BASE/envs/$ENV_NAME/bin/python"
            if [ -x "$PY" ]; then
                echo "$PY"
                return
            fi
        done
        # python of the base environment
        PY="$CONDA_BASE/bin/python"
        [ -x "$PY" ] && echo "$PY" && return
    fi

    # venv / virtualenv
    for VENV in .venv venv env; do
        PY="$SCRIPT_DIR/$VENV/bin/python"
        [ -x "$PY" ] && echo "$PY" && return
    done

    # System Python
    command -v python3 && return
    command -v python  && return

    echo ""
}

# Resolution: WISPER_PYTHON > ./.venv (created by install.sh) > pyenv 3.10.14 > auto-detect
PYTHON="${WISPER_PYTHON:-}"
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || PYTHON="$SCRIPT_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$HOME/.pyenv/versions/3.10.14/bin/python3"
[ -x "$PYTHON" ] || PYTHON=$(find_python)

if [ -z "$PYTHON" ]; then
    zenity --error \
        --title="Startup error" \
        --text="Python was not found.\nInstall Python or create a virtual environment." \
        2>/dev/null || \
    xmessage -center "Error: Python was not found." 2>/dev/null || \
    echo "Error: Python was not found." >&2
    exit 1
fi

echo "[launcher] Python: $PYTHON"

# Ollama is managed separately; see README.md.
# Never start or stop another application's inference service here.

# ── Start the GUI ───────────────────────────────────────────
echo "[launcher] Starting the GUI…"
"$PYTHON" "$SCRIPT_DIR/whisper_gui.py"

# The lifecycle of an external Ollama server is managed by whoever started it
echo "[launcher] GUI exited"
