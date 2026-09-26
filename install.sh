#!/bin/bash
# =============================================================
# mmv-voice installer — local-first
# =============================================================
# One command sets up everything this tool needs ON THIS MACHINE.
# Network is used only here, once, for: pip packages, the Whisper
# weights, the local model (ollama pull), and the MMV harness (git clone). After that
# the tool runs fully offline; audio and text never leave the machine.
#
# This script never uses sudo and never starts or stops Ollama.
#
# Usage:
#   bash install.sh            interactive install
#   bash install.sh --yes      answer yes to every download prompt
#   bash install.sh --check    only check the environment, change nothing
#   bash install.sh --python /path/to/python3
#                              use an existing interpreter instead of
#                              creating .venv (e.g. one that already has
#                              a CUDA build of PyTorch)
# =============================================================
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODEL="gemma4:12b-it-qat"
MODEL_DIGEST_PREFIX="38044be4f923"
OLLAMA_URL="${MMV_FORMAT_HOST:-http://127.0.0.1:11434}"
CONFIG="$SCRIPT_DIR/.mmv-voice.env"
DEFAULT_MMV="$HOME/.local/share/mmv-voice/mmv"
# Public MMV harness commit this release was checked against (formatting smoke test).
MMV_COMMIT="6eae1e0f4ba660f99043400d44bd1f77223aec34"
export OLLAMA_HOST="${OLLAMA_URL#http://}"   # ollama CLI talks to the same loopback server

YES=0; CHECK=0; USE_PY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) YES=1 ;;
        --check)  CHECK=1 ;;
        --python) shift; USE_PY="${1:-}" ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$*"; FAILED=1; }
ask()  { [ "$YES" = 1 ] && return 0; [ "$CHECK" = 1 ] && return 1
         read -r -p "  $1 [y/N] " a; [ "$a" = y ] || [ "$a" = Y ]; }
FAILED=0

echo "mmv-voice installer (local-first)"
[ "$CHECK" = 1 ] && echo "(check only — nothing will be changed)"

# ── 1. system tools ─────────────────────────────────────────
echo; echo "1/5 System tools"
command -v ffmpeg >/dev/null && ok "ffmpeg" || bad "ffmpeg missing — run: sudo apt install ffmpeg"
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
    ok "NVIDIA GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
    GPU=1
else
    warn "no NVIDIA GPU detected — Whisper will run on CPU (slow); the local model needs a GPU with ~8 GB for comfortable use"
    GPU=0
fi

# ── 2. Python environment ───────────────────────────────────
echo; echo "2/5 Python environment"
if [ -n "$USE_PY" ]; then
    PY="$USE_PY"
elif [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PY="$SCRIPT_DIR/.venv/bin/python"
else
    PY=""
fi
if [ -z "$PY" ]; then
    BASEPY="$(command -v python3 || true)"
    if [ -z "$BASEPY" ]; then bad "python3 not found"; else
        if [ "$CHECK" = 1 ]; then warn ".venv not created yet"
        elif ask "Create a virtual environment in ./.venv ?"; then
            "$BASEPY" -m venv "$SCRIPT_DIR/.venv" && PY="$SCRIPT_DIR/.venv/bin/python" && ok "created .venv"
        fi
    fi
fi
[ -z "$PY" ] && bad "no Python environment (run without --check to create ./.venv)"
if [ -n "$PY" ]; then
    "$PY" -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null \
        && ok "Python $("$PY" -c 'import platform;print(platform.python_version())') ($PY)" \
        || bad "Python 3.10+ required ($PY)"
    "$PY" -c 'import tkinter' 2>/dev/null && ok "tkinter" || bad "tkinter missing — run: sudo apt install python3-tk"
    if ! "$PY" -c 'import torch' 2>/dev/null; then
        if [ "$CHECK" = 0 ] && ask "Install PyTorch (downloads ~2–3 GB)?"; then
            if [ "$GPU" = 1 ]; then IDX="https://download.pytorch.org/whl/cu128"; else IDX="https://download.pytorch.org/whl/cpu"; fi
            "$PY" -m pip install --upgrade pip >/dev/null && "$PY" -m pip install torch --index-url "$IDX"
        fi
    fi
    "$PY" -c 'import torch' 2>/dev/null \
        && ok "PyTorch $("$PY" -c 'import torch;print(torch.__version__, "CUDA" if torch.cuda.is_available() else "CPU")')" \
        || bad "PyTorch not installed"
    if ! "$PY" -c 'import whisper, requests, yaml' 2>/dev/null; then
        if [ "$CHECK" = 0 ] && ask "Install Python packages from requirements.txt?"; then
            "$PY" -m pip install -r requirements.txt
        fi
    fi
    "$PY" -c 'import whisper, requests, yaml' 2>/dev/null && ok "openai-whisper, requests, pyyaml" || bad "Python packages missing"
    # Whisper downloads its weights on first use; fetch them now so the tool
    # never needs the network while you work.
    WCACHE="${XDG_CACHE_HOME:-$HOME/.cache}/whisper"
    if [ ! -s "$WCACHE/large-v3-turbo.pt" ]; then
        if [ "$CHECK" = 0 ] && ask "Download Whisper large-v3-turbo weights (~1.6 GB) now, so transcription works offline?"; then
            "$PY" -c "import whisper,os; whisper._download(whisper._MODELS['large-v3-turbo'], os.path.expanduser('$WCACHE'), False)"
        fi
    fi
    [ -s "$WCACHE/large-v3-turbo.pt" ] && ok "Whisper large-v3-turbo weights cached ($WCACHE)" \
        || bad "Whisper weights not cached yet (the first transcription would download them)"
fi

# ── 3. local model server (Ollama) ──────────────────────────
echo; echo "3/5 Local model (Ollama at $OLLAMA_URL)"
case "$OLLAMA_URL" in
    http://127.0.0.1:*|http://localhost:*|http://\[::1\]:*) ok "endpoint is loopback-only" ;;
    *) bad "MMV_FORMAT_HOST must be a loopback address; got $OLLAMA_URL" ;;
esac
if ! command -v ollama >/dev/null; then
    bad "ollama not installed — see https://ollama.com/download (installing it is your choice; this script will not)"
elif ! curl -s -m 3 "$OLLAMA_URL/api/version" >/dev/null; then
    bad "Ollama is not running — start it yourself (e.g. 'ollama serve' or your system service); this script never starts or stops it"
else
    ok "Ollama running ($(curl -s -m 3 "$OLLAMA_URL/api/version" | sed 's/.*"version":"\([^"]*\)".*/\1/'))"
    if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
        if [ "$CHECK" = 0 ] && ask "Download the local model $MODEL (~7.2 GB)?"; then ollama pull "$MODEL"; fi
    fi
    DIG="$(curl -s -m 5 "$OLLAMA_URL/api/tags" | "${PY:-python3}" -c "
import json,sys
for m in json.load(sys.stdin).get('models',[]):
    if m.get('name')=='$MODEL' or m.get('model')=='$MODEL': print(m.get('digest','')); break" 2>/dev/null)"
    if [ -z "$DIG" ]; then bad "model $MODEL not present"
    elif [ "${DIG#$MODEL_DIGEST_PREFIX}" != "$DIG" ]; then ok "model $MODEL, digest ${DIG:0:12}… (the evaluated build)"
    else warn "model $MODEL present but digest ${DIG:0:12}… differs from the evaluated build ${MODEL_DIGEST_PREFIX}… — the tool will refuse to format until they match"
    fi
fi

# ── 4. MMV harness ──────────────────────────────────────────
echo; echo "4/5 MMV harness"
[ -f "$CONFIG" ] && . "$CONFIG"
MMV="${MMV_REPO:-}"
if [ -z "$MMV" ] || [ ! -f "$MMV/operate-fr-bench/harness/adapters.py" ]; then
    if [ -f "$DEFAULT_MMV/operate-fr-bench/harness/adapters.py" ]; then MMV="$DEFAULT_MMV"
    elif [ "$CHECK" = 0 ] && ask "Clone the MMV harness (github.com/mobius-style/mmv) into $DEFAULT_MMV ?"; then
        mkdir -p "$(dirname "$DEFAULT_MMV")" && git clone -q https://github.com/mobius-style/mmv "$DEFAULT_MMV" \
            && git -C "$DEFAULT_MMV" checkout -q "$MMV_COMMIT" && MMV="$DEFAULT_MMV"
    fi
fi
if [ -n "$MMV" ] && [ -f "$MMV/operate-fr-bench/harness/adapters.py" ]; then
    ok "MMV harness at $MMV"
    HEAD_SHA="$(git -C "$MMV" rev-parse HEAD 2>/dev/null || true)"
    [ "$HEAD_SHA" = "$MMV_COMMIT" ] && ok "harness commit ${MMV_COMMIT:0:7} (the checked one)" \
        || warn "harness commit ${HEAD_SHA:0:7} differs from the checked ${MMV_COMMIT:0:7}; it will likely work, but it is not the tested combination"
    if [ "$CHECK" = 0 ]; then
        printf '# written by install.sh — read by launch.sh\nexport MMV_REPO=%q\n' "$MMV" > "$CONFIG" && ok "saved MMV_REPO to .mmv-voice.env"
    fi
else
    bad "MMV harness not found (set MMV_REPO or rerun without --check)"
fi

# ── 5. local-first summary ──────────────────────────────────
echo; echo "5/5 Local-first check"
ok "formatting endpoint: $OLLAMA_URL (loopback only; anything else is refused by the tool)"
ok "no account, no API key, no telemetry needed for the default engine"
[ -n "${GROQ_API_KEY:-}" ] && warn "GROQ_API_KEY is set — only used if you pick the opt-in cloud engine AND confirm the dialog" \
                           || ok "no cloud key present — the opt-in cloud engine stays unavailable"

echo
if [ "$FAILED" = 0 ]; then
    echo "Ready. Start with:  bash launch.sh"
    exit 0
else
    echo "Some items need attention (✘ above). Fix them and run:  bash install.sh --check"
    exit 1
fi
