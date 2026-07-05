"""
Whisper large-v3-turbo + MMV-M-RC3.3 (gemma4:12b) 音声文字起こし＆整形ツール
============================================================================
パイプライン:
  1. Whisper large-v3-turbo で文字起こし（GPU、日本語）
  2. 話者分離（pyannote が使える環境なら音声ベース、なければ
     MMV経由のテキスト帰属にフォールバック）
  3. MMV-M-RC3.3 ハーネス(route_transformer + post_validator +
     force_reanchor_v2)経由の gemma4:12b で整形
  4. 忠実性検証 — 整形文が原文の意味内容を保存しているかをチャンク毎に
     MMV経由で検査し、疑わしいチャンクに ⚠️ を付ける
  5. 議事メモ生成（概要/論点/決定事項/TODO）
  6. 秘書digest出力 — MOBIUS秘書システムの digests ディレクトリへ
     voice_note_<ts>.md として保存

モデル束縛は releases/medium/current.yaml のリリースポインタから読むため、
MMV側の束縛更新に自動追従する。

起動方法:
  bash launch.sh   または   デスクトップアイコンをダブルクリック
"""

import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import threading
import sys
import os
import io
import re
import time
import whisper
import torch
import requests
import yaml

# ─────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────
OLLAMA_CHAT        = "http://localhost:11434/api/chat"
OLLAMA_TAGS        = "http://localhost:11434/api/tags"
WHISPER_MODEL_SIZE = "large-v3-turbo"  # tiny/base/small/medium/large-v3/large-v3-turbo
MIN_FREE_VRAM_GB   = 7.0        # Whisper large-v3-turboロードに必要な最低空きVRAM(GB)
VRAM_WAIT_MAX_SEC  = 30         # VRAM解放待ち最大秒数
FORMAT_CHUNK_CHARS = 1000       # MMV整形1回あたりの最大入力文字数
                                # (MMVプロファイルはmax_tokens=1024凍結のため分割)
SPEAKER_BATCH_SEGS = 40         # 話者帰属1回あたりのセグメント数
MINUTES_MAX_CHARS  = 24000      # 議事メモ生成の最大入力文字数

# ─────────────────────────────────────────────────────────
# MMV ハーネス読み込み — Medium(ローカル既定) + Large(任意クラウド120B)
# 凍結プロファイルには一切手を加えず、リリースポインタ経由で束縛を取得する。
# ─────────────────────────────────────────────────────────
MMV_REPO    = os.environ.get("MMV_REPO") or os.path.expanduser(
    "~/デスクトップ/mobius_ai/MOBIUS_MMV")
MMV_ROOT    = os.path.join(MMV_REPO, "operate-fr-bench")
DIGEST_DIR  = os.path.join(MMV_REPO, "addons", "secretary", "state", "digests")


def _load_env_key(env_name):
    """APIキーを os.environ → MMVリポジトリの .env の順で解決する。"""
    if os.environ.get(env_name):
        return True
    try:
        with open(os.path.join(MMV_REPO, ".env"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(env_name + "="):
                    os.environ[env_name] = \
                        line.split("=", 1)[1].strip().strip('"').strip("'")
                    return True
    except Exception:
        pass
    return False


def _load_mmv_binding(size):
    """
    releases/<size>/current.yaml のリリースポインタから束縛を読む。
    返り値: {"profile", "release", "model", "local"}
    """
    pointer = os.path.join(MMV_ROOT, "releases", size, "current.yaml")
    with open(pointer, encoding="utf-8") as fh:
        ptr = yaml.safe_load(fh)
    profiles_path = os.path.join(MMV_REPO, ptr["profile_path"])
    with open(profiles_path, encoding="utf-8") as fh:
        profiles = yaml.safe_load(fh)["profiles"]
    profile = dict(profiles[ptr["profile_name"]])
    key_env = profile.get("api_key_env")
    if key_env and not _load_env_key(key_env):
        raise RuntimeError(
            f"{key_env} が未設定（環境変数にも {MMV_REPO}/.env にも無い）")
    return {
        "profile": profile,
        "release": ptr.get("release", "?"),
        "model":   ptr.get("provider_model_id", profile.get("model_id", "?")),
        "local":   profile.get("backend") == "ollama",
    }


MMV_M        = None   # ローカル既定エンジン (MMV-M / gemma4:12b)
MMV_L        = None   # 任意クラウドエンジン (MMV-L / 120B via Groq)
MMV_LOAD_ERR = None   # Mが読めない場合は整形機能全体を無効化
MMV_L_ERR    = None   # Lが読めない場合はクラウド切替だけ無効化

try:
    sys.path.insert(0, MMV_ROOT)
    from harness.adapters import call_adapter
    MMV_M = _load_mmv_binding("medium")
except Exception as _e:                     # MMV不在時は整形を無効化(素通し禁止)
    MMV_LOAD_ERR = f"{type(_e).__name__}: {_e}"

if MMV_LOAD_ERR is None:
    try:
        MMV_L = _load_mmv_binding("large")
    except Exception as _e:
        MMV_L_ERR = f"{type(_e).__name__}: {_e}"

MMV_RELEASE = MMV_M["release"] if MMV_M else "?"
MMV_MODEL   = MMV_M["model"]   if MMV_M else "?"   # Ollamaアンロード/存在確認にも使う


# ─────────────────────────────────────────────────────────
# Whisper stdout リアルタイムキャプチャ
# ─────────────────────────────────────────────────────────
class WhisperOutputCapture(io.StringIO):
    """
    whisper.transcribe(verbose=True) の標準出力を横取りし、
    1行ごとにコールバックへ送る。
    例: "[00:00.000 --> 00:05.000]  こんにちは"
    """
    def __init__(self, line_callback):
        super().__init__()
        self._cb  = line_callback
        self._buf = ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._cb(line)
        return len(text)

    def flush(self):
        pass


# ─────────────────────────────────────────────────────────
# Ollama ヘルパー
# ─────────────────────────────────────────────────────────
def check_ollama_ready():
    """Ollamaサーバー起動確認 + MMV束縛モデルの存在確認。(ok, message)を返す"""
    if MMV_LOAD_ERR is not None:
        return False, (f"⚠️ MMVハーネスを読み込めません: {MMV_LOAD_ERR}\n"
                       f"  → {MMV_ROOT} を確認してください。")
    try:
        resp = requests.get(OLLAMA_TAGS, timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        if MMV_MODEL not in models:
            return False, (f"⚠️ モデル [{MMV_MODEL}] が見つかりません。\n"
                           f"  → ollama pull {MMV_MODEL}")
        l_state = "利用可" if MMV_L else "利用不可"
        return True, (f"✅ {MMV_RELEASE} [{MMV_MODEL}] 接続済み"
                      f"（MMV-L 120B: {l_state}）。ファイルを選択してください。")
    except requests.exceptions.ConnectionError:
        return False, "⚠️ Ollama未起動。 → ollama serve を実行してください。"
    except Exception as e:
        return False, f"⚠️ Ollama確認エラー: {e}"


def ollama_unload():
    """
    OllamaのモデルをVRAMからアンロードする。
    keep_alive=0 を渡すことで即時アンロードを要求する。
    WhisperがVRAMを確保できるようにするために呼ぶ。
    """
    try:
        requests.post(OLLAMA_CHAT, json={
            "model": MMV_MODEL,
            "messages": [{"role": "user", "content": ""}],
            "keep_alive": 0
        }, timeout=10)
    except Exception:
        pass  # アンロード失敗は致命的ではない


def _mmv_call(prompt, engine=None):
    """MMVハーネス経由の1コール。(text, error) を返す。"""
    engine = engine or MMV_M
    if engine is None:
        return "", f"MMVハーネス未ロード: {MMV_LOAD_ERR}"
    res = call_adapter(prompt, engine["profile"])
    return (res.text or "").strip(), res.error


# ─────────────────────────────────────────────────────────
# 整形
# ─────────────────────────────────────────────────────────
FORMAT_INSTRUCTION = (
    "あなたは日本語テキストの整形アシスタントです。\n"
    "以下は音声の文字起こしテキストです。"
    "句読点・段落を整え、フィラー（えー、あの、まあ等）を除去し、"
    "話し言葉を自然な書き言葉に整えてください。"
    "元の意味・内容は変えないこと。整形後のテキストのみを出力すること。\n\n"
)

FORMAT_INSTRUCTION_SPK = (
    "あなたは日本語テキストの整形アシスタントです。\n"
    "以下は話者ラベル付きの音声文字起こしテキストです。"
    "句読点を整え、フィラー（えー、あの、まあ等）を除去し、"
    "話し言葉を自然な書き言葉に整えてください。"
    "行頭の話者ラベル（「話者1:」等）は必ずそのまま保持すること。"
    "発話の順序・意味・内容は変えないこと。"
    "整形後のテキストのみを出力すること。\n\n"
)


def _split_for_format(text, limit=FORMAT_CHUNK_CHARS):
    """文末(。！？/改行)を優先してlimit文字前後のチャンクに分割する。"""
    sentences = re.split(r"(?<=[。！？\n])", text)
    chunks, buf = [], ""
    for s in sentences:
        if buf and len(buf) + len(s) > limit:
            chunks.append(buf)
            buf = s
        else:
            buf += s
    if buf.strip():
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


def mmv_formatting(text, progress_cb=None, with_speakers=False, engine=None):
    """
    文字起こしテキストをMMVハーネス経由で整形する。
    凍結プロファイルのmax_tokens=1024を超えないよう文単位で分割して呼ぶ。
    返り値: (整形済み全文, チャンク対リスト [(原文, 整形文, エラー有無), ...])
    """
    engine = engine or MMV_M
    instruction = FORMAT_INSTRUCTION_SPK if with_speakers else FORMAT_INSTRUCTION
    chunks = _split_for_format(text)
    pairs = []
    for i, chunk in enumerate(chunks):
        if progress_cb:
            progress_cb(f"{engine['release']} 整形中… ({i + 1}/{len(chunks)})")
        out, err = _mmv_call(instruction + chunk, engine)
        if err:
            pairs.append((chunk,
                          f"【エラー】MMV呼び出し失敗: {err}\n"
                          f"--- 未整形原文 ---\n{chunk}", True))
        else:
            pairs.append((chunk, out, False))
    formatted = "\n\n".join(p[1] for p in pairs)
    return formatted, pairs


# ─────────────────────────────────────────────────────────
# 話者分離
# ─────────────────────────────────────────────────────────
SPEAKER_INSTRUCTION = (
    "以下は会話の文字起こしを発話順に番号付きで並べたものです。\n"
    "内容から各発話の話者を推定してください。話者は 話者1, 話者2, … と表記。\n"
    "出力は各行「番号: 話者N」の形式のみ（例「3: 話者2」）。説明は書かないこと。\n"
)


def _pyannote_diarize(audio_path, segments):
    """
    pyannote.audio による音声ベース話者分離。
    利用不可（未インストール/HFゲート未承認）なら None を返し、
    呼び出し側がテキスト帰属にフォールバックする。
    """
    try:
        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
        diar = pipeline(audio_path)
        labels = []
        for seg in segments:
            mid = (seg["start"] + seg["end"]) / 2.0
            spk = None
            for turn, _, label in diar.itertracks(yield_label=True):
                if turn.start <= mid <= turn.end:
                    spk = label
                    break
            labels.append(spk)
        # pyannoteのラベル(SPEAKER_00等)を 話者1,話者2… に正規化
        mapping, out = {}, []
        for spk in labels:
            if spk is None:
                out.append(out[-1] if out else "話者1")
                continue
            if spk not in mapping:
                mapping[spk] = f"話者{len(mapping) + 1}"
            out.append(mapping[spk])
        return out
    except Exception:
        return None


def _mmv_text_attribution(segments, progress_cb=None, engine=None):
    """MMV経由のテキストベース話者帰属。セグメント毎の話者ラベルを返す。"""
    labels = [None] * len(segments)
    n_batches = (len(segments) + SPEAKER_BATCH_SEGS - 1) // SPEAKER_BATCH_SEGS
    prev_note = ""
    for b in range(n_batches):
        lo = b * SPEAKER_BATCH_SEGS
        hi = min(lo + SPEAKER_BATCH_SEGS, len(segments))
        if progress_cb:
            progress_cb(f"話者推定中… ({b + 1}/{n_batches})")
        lines = "\n".join(f"{i + 1}. {segments[i]['text'].strip()}"
                          for i in range(lo, hi))
        out, err = _mmv_call(SPEAKER_INSTRUCTION + prev_note + "\n" + lines,
                             engine)
        if not err:
            for m in re.finditer(r"^\s*(\d+)\s*[:：]\s*(話者\s*\d+)",
                                 out, re.MULTILINE):
                idx = int(m.group(1)) - 1
                if lo <= idx < hi:
                    labels[idx] = m.group(2).replace(" ", "")
        last = labels[hi - 1]
        if last:
            prev_note = f"（この会話の続き。直前の発話の話者は {last}）\n"
    # 未推定セグメントは直前の話者を引き継ぐ
    cur = "話者1"
    for i in range(len(labels)):
        if labels[i] is None:
            labels[i] = cur
        else:
            cur = labels[i]
    return labels


def speaker_attribution(audio_path, segments, progress_cb=None, engine=None):
    """
    話者分離のエントリポイント。
    返り値: (話者付きテキスト, backend名) — 例 "話者1: こんにちは\\n話者2: …"
    """
    engine = engine or MMV_M
    if audio_path:
        labels = _pyannote_diarize(audio_path, segments)
        backend = "pyannote"
    else:
        labels = None
        backend = None
    if labels is None:
        labels = _mmv_text_attribution(segments, progress_cb, engine)
        backend = f"{engine['release']} テキスト帰属"
    # 連続する同一話者の発話をターンに結合
    turns = []
    for seg, spk in zip(segments, labels):
        text = seg["text"].strip()
        if not text:
            continue
        if turns and turns[-1][0] == spk:
            turns[-1][1] += text
        else:
            turns.append([spk, text])
    joined = "\n".join(f"{spk}: {text}" for spk, text in turns)
    return joined, backend


# ─────────────────────────────────────────────────────────
# 忠実性検証
# ─────────────────────────────────────────────────────────
FIDELITY_INSTRUCTION = (
    "次の「原文」と「整形文」を比較してください。整形文は原文に対して"
    "フィラー除去・句読点/段落の整形・話し言葉の書き言葉化のみを行った"
    "ものであるべきです。意味の変化・内容の脱落・勝手な追加・過度な要約が"
    "ないか検査してください。\n"
    "出力は1行のみ:\n"
    "- 問題がなければ「OK」\n"
    "- 問題があれば「NG: <40字以内の理由>」\n\n"
)


def mmv_fidelity_check(pairs, progress_cb=None, engine=None):
    """
    整形チャンク対 [(原文, 整形文, err), ...] を検証する。
    返り値: [{"index", "ok", "reason"}, ...]（整形エラーのチャンクは対象外=NG扱い）
    """
    results = []
    for i, (orig, fmt, had_err) in enumerate(pairs):
        if progress_cb:
            progress_cb(f"忠実性検証中… ({i + 1}/{len(pairs)})")
        if had_err:
            results.append({"index": i, "ok": False, "reason": "整形自体が失敗"})
            continue
        prompt = (FIDELITY_INSTRUCTION +
                  f"【原文】\n{orig}\n\n【整形文】\n{fmt}")
        out, err = _mmv_call(prompt, engine)
        if err:
            results.append({"index": i, "ok": False,
                            "reason": f"検証呼び出し失敗: {err}"})
        elif out.upper().startswith("OK"):
            results.append({"index": i, "ok": True, "reason": ""})
        else:
            reason = re.sub(r"^NG\s*[:：]?\s*", "", out.splitlines()[0])
            results.append({"index": i, "ok": False, "reason": reason})
    return results


def build_fidelity_report(results):
    """検証結果を人が読むレポート文字列にする。"""
    if not results:
        return "（検証は実行されていません）"
    n_ng = sum(1 for r in results if not r["ok"])
    lines = [f"忠実性検証: {len(results)}チャンク中 {n_ng}件 要確認",
             ""]
    for r in results:
        mark = "✅ OK" if r["ok"] else f"⚠️ 要確認: {r['reason']}"
        lines.append(f"チャンク{r['index'] + 1}: {mark}")
    return "\n".join(lines)


def annotate_formatted(pairs, results):
    """疑わしいチャンクに ⚠️ マーカーを付けた表示用整形全文を作る。"""
    ng = {r["index"]: r["reason"] for r in results if not r["ok"]}
    out = []
    for i, (_, fmt, _) in enumerate(pairs):
        if i in ng:
            out.append(f"⚠️【要確認 チャンク{i + 1}: {ng[i]}】\n{fmt}")
        else:
            out.append(fmt)
    return "\n\n".join(out)


# ─────────────────────────────────────────────────────────
# 議事メモ生成
# ─────────────────────────────────────────────────────────
MINUTES_INSTRUCTION = (
    "以下の整形済み文字起こしから、日本語の議事メモをMarkdownで作成して"
    "ください。構成は次のとおり:\n"
    "## 概要（2〜3文）\n## 主な論点\n## 決定事項\n## TODO・宿題\n"
    "該当する内容がない節は「(なし)」と書くこと。"
    "本文にない事柄を追加しないこと。\n\n"
)


def mmv_minutes(text, progress_cb=None, engine=None):
    """整形済みテキストから議事メモを生成する。"""
    if progress_cb:
        progress_cb("議事メモ生成中…")
    src = text
    if len(src) > MINUTES_MAX_CHARS:
        src = src[:MINUTES_MAX_CHARS] + "\n…（以降省略）"
    out, err = _mmv_call(MINUTES_INSTRUCTION + src, engine)
    if err:
        return f"【エラー】議事メモ生成失敗: {err}"
    return out


# ─────────────────────────────────────────────────────────
# 秘書digest出力（MOBIUSエコシステム編入）
# ─────────────────────────────────────────────────────────
def write_secretary_digest(meta, formatted, minutes, fidelity_report):
    """
    MOBIUS秘書システムの digests ディレクトリへ voice_note_<ts>.md を書く。
    返り値: 書き込んだファイルパス。
    """
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = os.path.join(DIGEST_DIR, f"voice_note_{ts}.md")
    lines = [
        "# Voice Note Digest",
        "",
        f"- source_audio: `{meta.get('source', '?')}`",
        f"- generated_at: {time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())}",
        f"- transcriber: whisper {WHISPER_MODEL_SIZE}",
        f"- formatter: {meta.get('engine', '?')} via MMV harness",
        f"- speaker_backend: {meta.get('speaker_backend') or '(話者分離なし)'}",
        f"- fidelity: {meta.get('fidelity_summary', '(未検証)')}",
        "",
    ]
    if minutes:
        lines += ["## 議事メモ", "", minutes, ""]
    lines += ["## 整形テキスト", "", formatted, ""]
    if fidelity_report:
        lines += ["## 忠実性検証レポート", "", fidelity_report, ""]
    os.makedirs(DIGEST_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


# ─────────────────────────────────────────────────────────
# GPU ヘルパー
# ─────────────────────────────────────────────────────────
def get_free_vram_gb(gpu_id):
    """指定GPUの空きVRAM(GB)を返す"""
    if not torch.cuda.is_available():
        return 0.0
    total    = torch.cuda.get_device_properties(gpu_id).total_memory / 1024**3
    reserved = torch.cuda.memory_reserved(gpu_id) / 1024**3
    return total - reserved


def get_best_gpu():
    """最も空きVRAMが多いGPUのインデックスを返す。なければNone"""
    best_id, best_free = None, 0.0
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            free = get_free_vram_gb(i)
            if free > best_free:
                best_id, best_free = i, free
    return best_id


def gpu_info_str():
    """GPU一覧を文字列で返す"""
    if not torch.cuda.is_available():
        return "GPU: なし（CPU動作）"
    lines = []
    for i in range(torch.cuda.device_count()):
        prop  = torch.cuda.get_device_properties(i)
        total = prop.total_memory / 1024**3
        free  = get_free_vram_gb(i)
        lines.append(f"GPU{i}: {prop.name}  空き{free:.1f}/{total:.1f}GB")
    return "  |  ".join(lines)


def wait_for_vram(gpu_id, required_gb, timeout_sec, progress_cb):
    """
    指定GPUの空きVRAMが required_gb を超えるまで待機する。
    timeout_sec 秒以内に確保できなければ False を返す。
    progress_cb(msg) でUIに進捗を通知する。
    """
    if gpu_id is None:
        return True  # CPU動作は待機不要
    for i in range(timeout_sec):
        free = get_free_vram_gb(gpu_id)
        if free >= required_gb:
            return True
        progress_cb(f"VRAM解放待ち… GPU{gpu_id}: 空き{free:.1f}GB / 必要{required_gb:.1f}GB ({i+1}/{timeout_sec}秒)")
        time.sleep(1)
    return False


# ─────────────────────────────────────────────────────────
# GUI メインクラス
# ─────────────────────────────────────────────────────────
class WhisperMMVGUI:

    def __init__(self, master):
        self.master = master
        master.title(f"Whisper {WHISPER_MODEL_SIZE} ＋ {MMV_RELEASE} ({MMV_MODEL})  音声整形ツール")
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 状態変数
        self.mode_var   = tk.StringVar(value="起動中…")
        self.status_var = tk.StringVar(value="初期化中…")
        self.kill_flag  = threading.Event()

        self.opt_speaker  = tk.BooleanVar(value=True)
        self.opt_fidelity = tk.BooleanVar(value=True)
        self.opt_minutes  = tk.BooleanVar(value=True)
        self.engine_var   = tk.StringVar(value="M")   # M=ローカル / L=Groq 120B

        self.whisper_thread = None
        self.post_thread    = None
        self.whisper_model  = None
        self.whisper_device = None
        self.last_whisper_text = ""
        self.last_segments     = None
        self.current_audio     = None
        self.last_result       = None   # digest保存用

        self._build_ui()

        # 起動時チェック（スレッドでGUI起動をブロックしない）
        threading.Thread(target=self._startup_check, daemon=True).start()

    # ─────────────────────────────────────────
    # UI 構築
    # ─────────────────────────────────────────
    def _build_ui(self):
        m = self.master

        # 上部ステータスバー
        bar = tk.Frame(m, bg="#f0f0f0", pady=4)
        bar.pack(fill="x")
        tk.Label(bar, textvariable=self.mode_var,
                 fg="#1a4a8a", bg="#f0f0f0",
                 font=("Meiryo", 10, "bold")).pack(side="left", padx=8)
        tk.Label(bar, textvariable=self.status_var,
                 fg="#555", bg="#f0f0f0",
                 font=("Meiryo", 9)).pack(side="left", padx=4)

        # テキストエリア（左右分割）
        pane = tk.Frame(m)
        pane.pack(expand=True, fill="both", padx=6, pady=4)

        # 左：Whisper生ログ
        lf = tk.LabelFrame(pane, text=" Whisper 生ログ（リアルタイム） ",
                            fg="navy", font=("Meiryo", 10, "bold"))
        lf.pack(side="left", expand=True, fill="both", padx=(0, 3))
        self.whisper_textbox = scrolledtext.ScrolledText(
            lf, font=("Meiryo", 9), width=54, height=26, wrap="word")
        self.whisper_textbox.pack(expand=True, fill="both")
        self.whisper_progress = tk.Label(
            lf, text="", fg="green", font=("Meiryo", 9))
        self.whisper_progress.pack()
        tk.Button(lf, text="全コピー",
                  command=lambda: self.copy_to_clipboard(self.whisper_textbox)
                  ).pack(pady=2)

        # 右：MMV出力タブ（整形済み / 議事メモ / 検証レポート）
        rf = tk.LabelFrame(pane, text=f" {MMV_RELEASE} ({MMV_MODEL})  出力 ",
                            fg="purple", font=("Meiryo", 10, "bold"))
        rf.pack(side="left", expand=True, fill="both", padx=(3, 0))
        self.notebook = ttk.Notebook(rf)
        self.notebook.pack(expand=True, fill="both")

        self.fmt_textbox      = self._make_tab("整形済み")
        self.minutes_textbox  = self._make_tab("議事メモ")
        self.fidelity_textbox = self._make_tab("検証レポート")

        self.fmt_progress = tk.Label(
            rf, text="処理待機中。", fg="gray", font=("Meiryo", 9))
        self.fmt_progress.pack()
        tk.Button(rf, text="表示中タブを全コピー",
                  command=self.copy_active_tab).pack(pady=2)

        # オプション行
        of = tk.Frame(m)
        of.pack(pady=2)
        tk.Checkbutton(of, text="話者分離", variable=self.opt_speaker,
                       font=("Meiryo", 10)).pack(side="left", padx=8)
        tk.Checkbutton(of, text="忠実性検証", variable=self.opt_fidelity,
                       font=("Meiryo", 10)).pack(side="left", padx=8)
        tk.Checkbutton(of, text="議事メモ生成", variable=self.opt_minutes,
                       font=("Meiryo", 10)).pack(side="left", padx=8)

        # エンジン切替行（既定=ローカルM / 任意=クラウドL 120B）
        ef = tk.Frame(m)
        ef.pack(pady=2)
        tk.Label(ef, text="MMVエンジン:", font=("Meiryo", 10, "bold")
                 ).pack(side="left", padx=(8, 4))
        tk.Radiobutton(
            ef, text=f"MMV-M（{MMV_MODEL}・ローカル）",
            variable=self.engine_var, value="M",
            font=("Meiryo", 10)).pack(side="left", padx=4)
        label_l = (f"MMV-L（{MMV_L['model']}・Groqクラウド）"
                   if MMV_L else "MMV-L（利用不可）")
        self.engine_l_btn = tk.Radiobutton(
            ef, text=label_l, variable=self.engine_var, value="L",
            font=("Meiryo", 10), fg="#a05000",
            command=self._confirm_cloud_engine)
        self.engine_l_btn.pack(side="left", padx=4)
        if MMV_L is None:
            self.engine_l_btn.config(state="disabled")

        # ボタン行
        bf = tk.Frame(m)
        bf.pack(pady=6)
        self.select_btn = tk.Button(
            bf, text="🎙  音声ファイル選択 → 処理開始",
            font=("Meiryo", 11), width=26, command=self.select_file)
        self.select_btn.pack(side="left", padx=6)

        self.kill_btn = tk.Button(
            bf, text="⏹  Whisper停止 → MMV整形",
            font=("Meiryo", 11), fg="red", width=24,
            command=self.kill_whisper, state="disabled")
        self.kill_btn.pack(side="left", padx=6)

        self.digest_btn = tk.Button(
            bf, text="📤  秘書digestへ保存",
            font=("Meiryo", 11), width=20,
            command=self.save_digest, state="disabled")
        self.digest_btn.pack(side="left", padx=6)

        self._add_context_menu(self.whisper_textbox)
        for tb in (self.fmt_textbox, self.minutes_textbox,
                   self.fidelity_textbox):
            self._add_context_menu(tb)

    def _make_tab(self, title):
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        tb = scrolledtext.ScrolledText(
            frame, font=("Meiryo", 9), width=54, height=24, wrap="word")
        tb.pack(expand=True, fill="both")
        return tb

    def copy_active_tab(self):
        idx = self.notebook.index(self.notebook.select())
        tb = (self.fmt_textbox, self.minutes_textbox,
              self.fidelity_textbox)[idx]
        self.copy_to_clipboard(tb)

    def _confirm_cloud_engine(self):
        """MMV-L(クラウド)選択時に外部送信の確認を取る。拒否ならMへ戻す。"""
        if self.engine_var.get() != "L":
            return
        ok = messagebox.askokcancel(
            "クラウド送信の確認",
            "MMV-L を選ぶと、文字起こしテキストが Groq（クラウド）へ\n"
            f"送信されます（モデル: {MMV_L['model']}）。\n\n"
            "ローカル完結ではなくなります。続行しますか？")
        if not ok:
            self.engine_var.set("M")

    def _active_engine(self):
        """現在選択中のMMVエンジン束縛を返す。"""
        if self.engine_var.get() == "L" and MMV_L is not None:
            return MMV_L
        return MMV_M

    # ─────────────────────────────────────────
    # 起動時チェック（バックグラウンド）
    # ─────────────────────────────────────────
    def _startup_check(self):
        gpu_str    = gpu_info_str()
        ok, ol_msg = check_ollama_ready()
        self.ui(lambda: self.mode_var.set(gpu_str))
        self.ui(lambda: self.status_var.set(ol_msg))
        if not ok:
            self.ui(lambda: messagebox.showwarning("Ollama未準備", ol_msg))

    # ─────────────────────────────────────────
    # UI ヘルパー
    # ─────────────────────────────────────────
    def ui(self, func):
        """バックグラウンドスレッドからスレッドセーフにUI更新"""
        self.master.after(0, func)

    def _add_context_menu(self, tb):
        menu = tk.Menu(tb, tearoff=0)
        menu.add_command(label="コピー",
                         command=lambda: self.copy_to_clipboard(tb))
        tb.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        tb.bind("<Control-c>", lambda e: self.copy_to_clipboard(tb))

    def copy_to_clipboard(self, tb):
        try:
            txt = tb.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            txt = tb.get("1.0", tk.END)
        self.master.clipboard_clear()
        self.master.clipboard_append(txt)

    def _set_textbox(self, tb, text):
        self.ui(lambda: (tb.delete("1.0", tk.END), tb.insert(tk.END, text)))

    def _append_whisper_line(self, line):
        self.ui(lambda: (
            self.whisper_textbox.insert(tk.END, line + "\n"),
            self.whisper_textbox.see(tk.END)
        ))

    def _set_processing(self, active):
        self.select_btn.config(state="disabled" if active else "normal")
        self.kill_btn.config(state="normal" if active else "disabled")

    def _post_progress(self, msg):
        self.ui(lambda: self.fmt_progress.config(text=msg))

    # ─────────────────────────────────────────
    # ファイル選択・処理開始（メインスレッド）
    # ─────────────────────────────────────────
    def select_file(self):
        filepath = filedialog.askopenfilename(
            title="音声ファイルを選択",
            filetypes=[
                ("Audio Files",
                 "*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.wma *.mp4 *.mkv"),
                ("All Files", "*.*"),
            ]
        )
        if not filepath:
            return

        # UI初期化（メインスレッドなので直接呼び出し）
        self.kill_flag.clear()
        self.last_whisper_text = ""
        self.last_segments     = None
        self.current_audio     = filepath
        self.last_result       = None
        self.digest_btn.config(state="disabled")
        self.whisper_textbox.delete("1.0", tk.END)
        for tb in (self.fmt_textbox, self.minutes_textbox,
                   self.fidelity_textbox):
            tb.delete("1.0", tk.END)
        self.whisper_progress.config(text="")
        self.fmt_progress.config(text="Whisper完了後に処理します。")
        self._set_processing(True)
        self.status_var.set("準備中…")

        self.whisper_thread = threading.Thread(
            target=self.run_whisper, args=(filepath,), daemon=True)
        self.whisper_thread.start()

    # ─────────────────────────────────────────
    # VRAM 解放
    # ─────────────────────────────────────────
    def _release_whisper_model(self):
        """WhisperモデルをVRAMから解放する"""
        if self.whisper_model is not None:
            del self.whisper_model
            self.whisper_model  = None
            self.whisper_device = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # ─────────────────────────────────────────
    # Whisper 処理（バックグラウンドスレッド）
    # ─────────────────────────────────────────
    def run_whisper(self, audio_path):
        try:
            # ── Step1: OllamaをアンロードしてVRAMを確保
            self.ui(lambda: self.whisper_progress.config(
                text="OllamaをアンロードしてVRAMを確保中…"))
            ollama_unload()
            time.sleep(2)  # アンロード完了を待つ

            # ── Step2: 空きVRAMが十分になるまで待機
            gpu_id = get_best_gpu()
            if gpu_id is not None:
                def progress_cb(msg):
                    self.ui(lambda: self.whisper_progress.config(text=msg))

                ok = wait_for_vram(gpu_id, MIN_FREE_VRAM_GB,
                                   VRAM_WAIT_MAX_SEC, progress_cb)
                if not ok:
                    # タイムアウトしても最善を尽くす（CPUフォールバック）
                    gpu_id = None
                    self.ui(lambda: self.whisper_progress.config(
                        text="VRAM不足のためCPU動作に切り替えます…"))
                    time.sleep(1)

            device = f"cuda:{gpu_id}" if gpu_id is not None else "cpu"
            prop_str = ""
            if gpu_id is not None:
                prop  = torch.cuda.get_device_properties(gpu_id)
                free  = get_free_vram_gb(gpu_id)
                prop_str = f"GPU{gpu_id}: {prop.name} 空き{free:.1f}GB"
            else:
                prop_str = "CPU動作"

            self.ui(lambda: self.status_var.set(f"Whisper処理中… [{prop_str}]"))

            # ── Step3: Whisperモデルロード（デバイス変化時のみ再ロード）
            if self.whisper_model is None or self.whisper_device != device:
                self.ui(lambda: self.whisper_progress.config(
                    text=f"Whisperモデル({WHISPER_MODEL_SIZE})読み込み中…"))
                self.whisper_model  = whisper.load_model(
                    WHISPER_MODEL_SIZE, device=device)
                self.whisper_device = device

            # ── Step4: 文字起こし（stdoutをキャプチャしてリアルタイム表示）
            self.ui(lambda: self.whisper_progress.config(
                text="文字起こし中…（リアルタイム表示）"))
            capture    = WhisperOutputCapture(self._append_whisper_line)
            old_stdout = sys.stdout
            sys.stdout = capture
            try:
                result = self.whisper_model.transcribe(
                    audio_path, language="ja", verbose=True)
            finally:
                sys.stdout = old_stdout

            self.last_whisper_text = result["text"]
            self.last_segments     = result.get("segments") or None
            self._set_textbox(self.whisper_textbox, result["text"])
            self.ui(lambda: self.whisper_progress.config(text="✅ Whisper完了"))
            self.ui(lambda: self.status_var.set(
                "Whisper完了。VRAMを解放して後処理を開始します…"))

            # ── Step5: VRAMを解放してOllamaへ渡す
            self._release_whisper_model()
            time.sleep(2)  # キャッシュクリアの反映を待つ
            self.ui(lambda: self.mode_var.set(gpu_info_str()))

            # kill_flagが立っていればkill_whisper側が後処理を起動済み
            if not self.kill_flag.is_set():
                self.post_thread = threading.Thread(
                    target=self.run_postprocess,
                    args=(self.last_whisper_text, self.last_segments,
                          audio_path),
                    daemon=True)
                self.post_thread.start()

        except Exception as e:
            err = str(e)
            self.ui(lambda: self.status_var.set(f"Whisperエラー: {err}"))
            self.ui(lambda: self.whisper_progress.config(text="❌ エラー"))
            self.ui(lambda: self._set_processing(False))

    # ─────────────────────────────────────────
    # 後処理（話者分離→整形→検証→議事メモ）バックグラウンドスレッド
    # ─────────────────────────────────────────
    def run_postprocess(self, text, segments, audio_path):
        try:
            engine = self._active_engine()
            speaker_backend = None
            with_speakers   = False
            work_text       = text

            # ── Step1: 話者分離
            if self.opt_speaker.get() and segments and len(segments) > 1:
                self._post_progress("話者分離中…")
                work_text, speaker_backend = speaker_attribution(
                    audio_path, segments, self._post_progress, engine)
                with_speakers = True

            # ── Step2: MMV整形
            formatted, pairs = mmv_formatting(
                work_text, self._post_progress,
                with_speakers=with_speakers, engine=engine)

            # ── Step3: 忠実性検証
            fidelity_results = []
            fidelity_report  = ""
            display_text     = formatted
            if self.opt_fidelity.get() and pairs:
                fidelity_results = mmv_fidelity_check(
                    pairs, self._post_progress, engine)
                fidelity_report  = build_fidelity_report(fidelity_results)
                display_text     = annotate_formatted(pairs, fidelity_results)
                self._set_textbox(self.fidelity_textbox, fidelity_report)
            self._set_textbox(self.fmt_textbox, display_text)

            # ── Step4: 議事メモ
            minutes = ""
            if self.opt_minutes.get() and formatted.strip():
                minutes = mmv_minutes(formatted, self._post_progress, engine)
                self._set_textbox(self.minutes_textbox, minutes)

            # ── Step5: digest保存用に結果を保持
            n_ng = sum(1 for r in fidelity_results if not r["ok"])
            fidelity_summary = (
                f"{len(fidelity_results)}チャンク中 {n_ng}件 要確認"
                if fidelity_results else "(未検証)")
            engine_str = f"{engine['release']} ({engine['model']})"
            engine_str += "・ローカル" if engine["local"] else "・Groqクラウド"
            self.last_result = {
                "meta": {
                    "source": audio_path or self.current_audio or "?",
                    "engine": engine_str,
                    "speaker_backend": speaker_backend,
                    "fidelity_summary": fidelity_summary,
                },
                "formatted": formatted,
                "minutes": minutes,
                "fidelity_report": fidelity_report,
            }
            self.ui(lambda: self.digest_btn.config(state="normal"))

            done = "✅ 全工程完了"
            if fidelity_results and n_ng:
                done += f"（⚠️ 要確認 {n_ng}件 — 検証レポート参照）"
            self.ui(lambda: self.fmt_progress.config(text=done))
            self.ui(lambda: self.status_var.set(
                done + "。次のファイルを選択できます。"))
            self.ui(lambda: self.mode_var.set(gpu_info_str()))
        except Exception as e:
            err = str(e)
            self.ui(lambda: self.fmt_progress.config(
                text=f"❌ 後処理エラー: {err}"))
        finally:
            self.ui(lambda: self._set_processing(False))

    # ─────────────────────────────────────────
    # 秘書digest保存（メインスレッド）
    # ─────────────────────────────────────────
    def save_digest(self):
        if not self.last_result:
            return
        try:
            r = self.last_result
            path = write_secretary_digest(
                r["meta"], r["formatted"], r["minutes"],
                r["fidelity_report"])
            self.status_var.set(f"📤 digest保存済み: {os.path.basename(path)}")
            messagebox.showinfo("保存完了",
                                f"秘書digestへ保存しました:\n{path}")
        except Exception as e:
            messagebox.showerror("保存失敗", f"digest保存に失敗しました:\n{e}")

    # ─────────────────────────────────────────
    # Whisper 強制停止（メインスレッド）
    # ─────────────────────────────────────────
    def kill_whisper(self):
        self.kill_flag.set()
        self.status_var.set("停止要求済み。取得済みテキストでMMV整形します。")
        self.whisper_progress.config(text="⏹ 停止要求中（transcribe完了後に終了）")
        self.kill_btn.config(state="disabled")

        current = self.whisper_textbox.get("1.0", tk.END).strip()
        # 生ログのタイムスタンプ行頭 "[00:00.000 --> 00:05.000]" を除去
        current = re.sub(r"\[[\d:.]+\s*-->\s*[\d:.]+\]\s*", "", current)
        if current:
            self.fmt_progress.config(text=f"{MMV_RELEASE} 整形中…")
            # 部分テキストのためセグメント情報なし → 話者分離はスキップされる
            self.post_thread = threading.Thread(
                target=self.run_postprocess, args=(current, None, None),
                daemon=True)
            self.post_thread.start()
        else:
            self.fmt_progress.config(
                text="テキスト未取得。Whisper完了後に自動処理します。")

    # ─────────────────────────────────────────
    # ウィンドウ終了処理
    # ─────────────────────────────────────────
    def on_closing(self):
        running = (
            (self.whisper_thread and self.whisper_thread.is_alive()) or
            (self.post_thread    and self.post_thread.is_alive())
        )
        if running:
            if not messagebox.askokcancel(
                    "確認", "処理中です。終了しますか？\n"
                             "（VRAMは自動解放されます）"):
                return
        self._release_whisper_model()
        self.master.destroy()


# ─────────────────────────────────────────────────────────
# エントリポイント
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    root.minsize(1000, 650)
    gui = WhisperMMVGUI(root)
    root.mainloop()
