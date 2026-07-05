#!/bin/bash
# =============================================================
# Whisper + Qwen3.5:9b(Ollama) 音声整形ツール ランチャー
# =============================================================
# 使い方:
#   初回のみ: chmod +x launch.sh
#   起動:     launch.sh をダブルクリック
#             （ファイルマネージャーで「実行する」を選択）
# =============================================================

# このスクリプト自身のディレクトリに移動（相対パスを確実にする）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Python 環境を自動検出 ────────────────────────────────
# 優先順位: conda(whisper) > conda(base) > venv(.venv) > system python3
find_python() {
    # condaがあれば whisper という名前の環境を優先して探す
    if command -v conda &>/dev/null; then
        CONDA_BASE=$(conda info --base 2>/dev/null)
        for ENV_NAME in whisper whisper_env audio base; do
            PY="$CONDA_BASE/envs/$ENV_NAME/bin/python"
            if [ -x "$PY" ]; then
                echo "$PY"
                return
            fi
        done
        # base環境のpython
        PY="$CONDA_BASE/bin/python"
        [ -x "$PY" ] && echo "$PY" && return
    fi

    # venv / virtualenv
    for VENV in .venv venv env; do
        PY="$SCRIPT_DIR/$VENV/bin/python"
        [ -x "$PY" ] && echo "$PY" && return
    done

    # システムPython
    command -v python3 && return
    command -v python  && return

    echo ""
}

# WISPER_PYTHON 環境変数 > pyenv 3.10.14 > find_python の順で解決
PYTHON="${WISPER_PYTHON:-$HOME/.pyenv/versions/3.10.14/bin/python3}"
[ -x "$PYTHON" ] || PYTHON=$(find_python)

if [ -z "$PYTHON" ]; then
    zenity --error \
        --title="起動エラー" \
        --text="Pythonが見つかりませんでした。\nPythonをインストールするか、仮想環境を作成してください。" \
        2>/dev/null || \
    xmessage -center "エラー: Pythonが見つかりません。" 2>/dev/null || \
    echo "エラー: Pythonが見つかりません。" >&2
    exit 1
fi

echo "[launcher] Python: $PYTHON"

# ── Ollama サーバーを自動起動 ────────────────────────────
if ! pgrep -x "ollama" > /dev/null; then
    echo "[launcher] Ollamaを起動します…"
    nohup ollama serve > /tmp/ollama_serve.log 2>&1 &
    OLLAMA_PID=$!
    echo "[launcher] Ollama PID: $OLLAMA_PID"

    # 起動待ち（最大10秒）
    for i in $(seq 1 10); do
        sleep 1
        if curl -s http://localhost:11434 > /dev/null 2>&1; then
            echo "[launcher] Ollama起動完了"
            break
        fi
        echo "[launcher] Ollama起動待ち… ($i/10)"
    done
else
    echo "[launcher] Ollamaはすでに起動中です"
fi

# ── GUI 起動 ────────────────────────────────────────────
echo "[launcher] GUIを起動します…"
"$PYTHON" "$SCRIPT_DIR/whisper_gui.py"

# GUIが終了してもOllamaは残す（他アプリが使っている可能性があるため）
echo "[launcher] GUIが終了しました"
