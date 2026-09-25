"""
Whisper large-v3-turbo + MMV formatting (Gemma-4 12B QAT).
Local: MMV harness + minimal-edit instruction + lexical acceptance check.
Optional cloud: independent frozen MMV-L harness, explicit GUI consent.
See README.md for startup and validation limits.
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
import yaml

# ─────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────
WHISPER_MODEL_SIZE = "large-v3-turbo"  # tiny/base/small/medium/large-v3/large-v3-turbo
WHISPER_LANGUAGE   = None       # None = auto-detect (multilingual) / "ja" etc. to pin a language
MIN_FREE_VRAM_GB   = 7.0        # Minimum free VRAM (GB) required to load Whisper large-v3-turbo
VRAM_WAIT_MAX_SEC  = 30         # Maximum seconds to wait for VRAM to be released
FORMAT_CHUNK_CHARS = 1000       # Maximum input characters per formatting call
                                # (conservative chunk length shared by the local and optional MMV-L paths)
SPEAKER_BATCH_SEGS = 40         # Segments per speaker-attribution call
MINUTES_MAX_CHARS  = 24000      # Maximum input characters for minutes generation

# ─────────────────────────────────────────────────────────
# Engine loading — MMV 12B QAT (local default) + MMV-L (optional cloud)
# Only the cloud engine obtains its frozen binding via the release pointer.
# ─────────────────────────────────────────────────────────
MMV_REPO    = os.environ.get("MMV_REPO") or os.path.expanduser(
    "~/デスクトップ/mobius_ai/MOBIUS_MMV")
MMV_ROOT    = os.path.join(MMV_REPO, "operate-fr-bench")
DIGEST_DIR  = os.path.join(MMV_REPO, "addons", "secretary", "state", "digests")


def _load_env_key(env_name):
    """Resolve an API key from os.environ first, then from the MMV repository's .env."""
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
    Read the binding from the release pointer releases/<size>/current.yaml.
    Returns: {"profile", "release", "model", "local"}
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
            f"{key_env} is not set (neither in the environment nor in {MMV_REPO}/.env)")
    return {
        "profile": profile,
        "release": ptr.get("release", "?"),
        "model":   ptr.get("provider_model_id", profile.get("model_id", "?")),
        "local":   profile.get("backend") == "ollama",
    }


MMV_M        = None   # Local default engine (MMV / 12B QAT)
MMV_L        = None   # Optional cloud engine (MMV-L / 120B via Groq)
MMV_LOAD_ERR = None   # If M cannot be loaded, the whole formatting feature is disabled
MMV_L_ERR    = None   # If L cannot be loaded, only the cloud switch is disabled

from voice_mmv import MMVFormatter, MODEL, PROFILE_PATH, audit_report
try:
    sys.path.insert(0, MMV_ROOT)
    from harness.adapters import call_adapter
    MMV_CLIENT = MMVFormatter(call_adapter)
    MMV_M = {"release":"MMV-Format-v2 (trial)", "model":MODEL, "local":True,
             "backend":"mmv_format", "profile":MMV_CLIENT.profile,
             "profile_path":str(PROFILE_PATH)}
except Exception as _e:
    MMV_LOAD_ERR = f"{type(_e).__name__}: {_e}"
try:
    MMV_L = _load_mmv_binding("large")
except Exception as _e:
    MMV_L_ERR = f"{type(_e).__name__}: {_e}"

MMV_RELEASE = MMV_M["release"] if MMV_M else "MMV unavailable"
MMV_MODEL = MMV_M["model"] if MMV_M else "12B QAT q4_0"


# ─────────────────────────────────────────────────────────
# Real-time capture of Whisper stdout
# ─────────────────────────────────────────────────────────
class WhisperOutputCapture(io.StringIO):
    """
    Intercepts the standard output of whisper.transcribe(verbose=True)
    and forwards it line by line to a callback.
    Example: "[00:00.000 --> 00:05.000]  Hello"
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
# MMV connectivity check
# ─────────────────────────────────────────────────────────
def check_mmv_ready():
    if MMV_LOAD_ERR:
        return False, f"⚠️ MMV configuration error: {MMV_LOAD_ERR}"
    try:
        MMV_CLIENT.check_ready()
        return True, f"✅ {MMV_RELEASE} [{MMV_MODEL}] connected."
    except Exception as e:
        return False, f"⚠️ MMV not connected: {e} → see the Ollama startup steps in README."


# The model sometimes echoes the route_transformer micro-instruction (the
# re-anchoring scaffold sentence used for benchmarking) at the start of its
# output (e.g. "Correction of the premise: …"). Everyday English conversation
# trips the stale_premise detection patterns (with/after/still, etc.) at the
# content level, so for formatting purposes only the echoed part is removed
# from the result. The governance itself (route_transformer/post_validator)
# has already run, and the frozen harness is never touched.
_SCAFFOLD_ECHO = re.compile(
    r"^\s*[^\n]{0,200}?(?:premise\s+embedded\s+in\s+your\s+question|"
    r"re-anchor\s+against\s+what\s+I\s+actually\s+know|"
    r"as\s+of\s+my\s+training\s+data)"
    r"[^\n]*?(?:before\s+answering\.|answering\.|\.)\s*",
    re.IGNORECASE)


def _strip_governance_scaffold(text):
    prev = None
    while prev != text:
        prev = text
        text = _SCAFFOLD_ECHO.sub("", text, count=1)
    return text


def _mmv_call(instruction, engine=None, context=None):
    """Dispatch to the selected MMV engine (local default or opt-in cloud path)."""
    engine = engine or MMV_M
    if engine is None:
        return "", f"Local MMV not loaded: {MMV_LOAD_ERR}"
    try:
        res = call_adapter(instruction + (context or ""), engine["profile"])
        return _strip_governance_scaffold((res.text or "").strip()), res.error
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


# ─────────────────────────────────────────────────────────
# Language helpers — switch the instruction by Whisper's auto-detected
# language (ISO 639-1). Japanese uses dedicated instructions; every other
# language uses English instructions that say "answer in the input language".
# ─────────────────────────────────────────────────────────
def _is_ja(lang):
    return (lang or "ja").startswith("ja")


def speaker_label(lang, n):
    return f"話者{n}" if _is_ja(lang) else f"Speaker {n}"


# ─────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────
FORMAT_INSTRUCTION_JA = (
    "あなたは日本語テキストの整形アシスタントです。\n"
    "以下は音声の文字起こしテキストです。"
    "句読点・段落を整え、フィラー（えー、あの、まあ等）を除去し、"
    "話し言葉を自然な書き言葉に整えてください。"
    "元の意味・内容は変えないこと。整形後のテキストのみを出力すること。\n\n"
)

FORMAT_INSTRUCTION_SPK_JA = (
    "あなたは日本語テキストの整形アシスタントです。\n"
    "以下は話者ラベル付きの音声文字起こしテキストです。"
    "句読点を整え、フィラー（えー、あの、まあ等）を除去し、"
    "話し言葉を自然な書き言葉に整えてください。"
    "行頭の話者ラベル（「話者1:」等）は必ずそのまま保持すること。"
    "発話の順序・意味・内容は変えないこと。"
    "整形後のテキストのみを出力すること。\n\n"
)

FORMAT_INSTRUCTION_EN = (
    "You are a transcript-formatting assistant.\n"
    "The following is a raw speech transcript. Fix punctuation and "
    "paragraphs, remove filler words (um, uh, well, etc.), and turn the "
    "spoken language into natural written prose IN THE SAME LANGUAGE as "
    "the input. Do not change the meaning or content. "
    "Output only the formatted text.\n\n"
)

FORMAT_INSTRUCTION_SPK_EN = (
    "You are a transcript-formatting assistant.\n"
    "The following is a speech transcript with speaker labels. Fix "
    "punctuation, remove filler words (um, uh, well, etc.), and turn the "
    "spoken language into natural written prose IN THE SAME LANGUAGE as "
    "the input. Keep the leading speaker labels (e.g. \"Speaker 1:\") "
    "exactly as they are. Do not change the order, meaning or content "
    "of the utterances. Output only the formatted text.\n\n"
)


def format_instruction(lang, with_speakers):
    if _is_ja(lang):
        return FORMAT_INSTRUCTION_SPK_JA if with_speakers else FORMAT_INSTRUCTION_JA
    return FORMAT_INSTRUCTION_SPK_EN if with_speakers else FORMAT_INSTRUCTION_EN


def _split_for_format(text, limit=FORMAT_CHUNK_CHARS):
    """Split into chunks of roughly `limit` characters, preferring sentence ends (。．！？.!?/newline)."""
    sentences = re.split(r"(?<=[。．！？!?.\n])", text)
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


def mmv_formatting(text, progress_cb=None, with_speakers=False, engine=None,
                   lang=None):
    """
    Format transcript text through the MMV harness.
    Calls are made on short chunks to limit dropped output.
    Returns: (formatted full text, list of chunk pairs [(source, formatted, had_error), ...])
    """
    engine = engine or MMV_M
    if engine and engine.get("backend") == "mmv_format":
        formatted, audit = MMV_CLIENT.format(text, lang, progress_cb)
        engine["format_audit"] = audit
        return formatted, [(r["source"],r["text"],not r["accepted"]) for r in audit]
    instruction = format_instruction(lang, with_speakers)
    chunks = _split_for_format(text)
    pairs = []
    for i, chunk in enumerate(chunks):
        if progress_cb:
            progress_cb(f"{engine['release']} formatting… ({i + 1}/{len(chunks)})")
        out, err = _mmv_call(instruction, engine, context=chunk)
        if err:
            pairs.append((chunk,
                          f"[ERROR] MMV call failed: {err}\n"
                          f"--- unformatted source ---\n{chunk}", True))
        else:
            pairs.append((chunk, out, False))
    formatted = "\n\n".join(p[1] for p in pairs)
    return formatted, pairs


# ─────────────────────────────────────────────────────────
# Speaker attribution
# ─────────────────────────────────────────────────────────
SPEAKER_INSTRUCTION_JA = (
    "以下は会話の文字起こしを発話順に番号付きで並べたものです。\n"
    "内容から各発話の話者を推定してください。話者は 話者1, 話者2, … と表記。\n"
    "出力は各行「番号: 話者N」の形式のみ（例「3: 話者2」）。説明は書かないこと。\n"
)

SPEAKER_INSTRUCTION_EN = (
    "Below is a conversation transcript, numbered in utterance order.\n"
    "Infer the speaker of each utterance from its content. Name speakers "
    "Speaker 1, Speaker 2, ...\n"
    "Output ONLY lines of the form \"number: Speaker N\" "
    "(e.g. \"3: Speaker 2\"). No explanations.\n"
)


def _pyannote_diarize(audio_path, segments, lang=None):
    """
    Audio-based speaker diarization via pyannote.audio.
    Returns None when unavailable (not installed / HF gate not accepted),
    and the caller falls back to text-based attribution.
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
        # Normalize pyannote labels (SPEAKER_00 etc.) to 話者1 / Speaker 1 …
        mapping, out = {}, []
        for spk in labels:
            if spk is None:
                out.append(out[-1] if out else speaker_label(lang, 1))
                continue
            if spk not in mapping:
                mapping[spk] = speaker_label(lang, len(mapping) + 1)
            out.append(mapping[spk])
        return out
    except Exception:
        return None


def _mmv_text_attribution(segments, progress_cb=None, engine=None, lang=None):
    """Text-based speaker attribution via MMV. Returns a speaker label per segment."""
    ja = _is_ja(lang)
    instruction = SPEAKER_INSTRUCTION_JA if ja else SPEAKER_INSTRUCTION_EN
    labels = [None] * len(segments)
    n_batches = (len(segments) + SPEAKER_BATCH_SEGS - 1) // SPEAKER_BATCH_SEGS
    prev_note = ""
    for b in range(n_batches):
        lo = b * SPEAKER_BATCH_SEGS
        hi = min(lo + SPEAKER_BATCH_SEGS, len(segments))
        if progress_cb:
            progress_cb(f"Inferring speakers… ({b + 1}/{n_batches})")
        lines = "\n".join(f"{i + 1}. {segments[i]['text'].strip()}"
                          for i in range(lo, hi))
        out, err = _mmv_call(instruction, engine, context=prev_note + "\n" + lines)
        if not err:
            for m in re.finditer(
                    r"^\s*(\d+)\s*[:：]\s*(話者\s*\d+|Speaker\s+\d+)",
                    out, re.MULTILINE | re.IGNORECASE):
                idx = int(m.group(1)) - 1
                if lo <= idx < hi:
                    label = m.group(2)
                    labels[idx] = (label.replace(" ", "") if ja
                                   else label.title())
        last = labels[hi - 1]
        if last:
            prev_note = (f"（この会話の続き。直前の発話の話者は {last}）\n" if ja
                         else f"(Continuation. The previous utterance was "
                              f"by {last}.)\n")
    # Missing or failed labels remain visibly unknown; do not invent attribution.
    for i, label in enumerate(labels):
        if label is None:
            labels[i] = "話者不明" if ja else "Speaker unknown"
    return labels


def speaker_attribution(audio_path, segments, progress_cb=None, engine=None,
                        lang=None):
    """
    Entry point for speaker attribution.
    Returns: (speaker-labelled text, backend name) — e.g. "Speaker 1: Hello\\nSpeaker 2: …"
    """
    engine = engine or MMV_M
    if audio_path:
        labels = _pyannote_diarize(audio_path, segments, lang)
        backend = "pyannote"
    else:
        labels = None
        backend = None
    if labels is None:
        labels = _mmv_text_attribution(segments, progress_cb, engine, lang)
        backend = f"{engine['release']} text attribution"
    # Merge consecutive utterances by the same speaker into turns
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
# Fidelity check
# ─────────────────────────────────────────────────────────
FIDELITY_INSTRUCTION_JA = (
    "次の「原文」と「整形文」を比較してください。整形文は原文に対して"
    "フィラー除去・句読点/段落の整形・話し言葉の書き言葉化のみを行った"
    "ものであるべきです。意味の変化・内容の脱落・勝手な追加・過度な要約が"
    "ないか検査してください。\n"
    "出力は1行のみ:\n"
    "- 問題がなければ「OK」\n"
    "- 問題があれば「NG: <40字以内の理由>」\n\n"
)

FIDELITY_INSTRUCTION_EN = (
    "Compare the ORIGINAL and the FORMATTED text below. The formatted text "
    "should only differ by filler-word removal, punctuation/paragraph "
    "fixes, and spoken-to-written style. Check for meaning changes, "
    "omissions, additions, or over-summarization.\n"
    "Output exactly one line:\n"
    "- \"OK\" if there is no problem\n"
    "- \"NG: <reason within 20 words>\" if there is\n\n"
)


def mmv_fidelity_check(pairs, progress_cb=None, engine=None, lang=None):
    """
    Verify formatted chunk pairs [(source, formatted, err), ...].
    Returns: [{"index", "ok", "reason"}, ...] (chunks whose formatting failed are treated as NG)
    """
    results = []
    for i, (orig, fmt, had_err) in enumerate(pairs):
        if progress_cb:
            progress_cb(f"Checking fidelity… ({i + 1}/{len(pairs)})")
        if had_err:
            results.append({"index": i, "ok": False, "reason": "formatting itself failed"})
            continue
        if _is_ja(lang):
            instruction = FIDELITY_INSTRUCTION_JA
            prompt = (
                      f"【原文】\n{orig}\n\n【整形文】\n{fmt}")
        else:
            instruction = FIDELITY_INSTRUCTION_EN
            prompt = (
                      f"[ORIGINAL]\n{orig}\n\n[FORMATTED]\n{fmt}")
        out, err = _mmv_call(instruction, engine, context=prompt)
        if err:
            results.append({"index": i, "ok": False,
                            "reason": f"verification call failed: {err}"})
        elif re.fullmatch(r"OK[.!。]?", out.strip(), re.IGNORECASE):
            results.append({"index": i, "ok": True, "reason": ""})
        else:
            reason = re.sub(r"^NG\s*[:：]?\s*", "", (out.splitlines() or ["empty verification response"])[0])
            results.append({"index": i, "ok": False, "reason": reason})
    return results


def build_fidelity_report(results):
    """Turn the verification results into a human-readable report string."""
    if not results:
        return "(verification was not run)"
    n_ng = sum(1 for r in results if not r["ok"])
    lines = [f"Fidelity check: {len(results)} chunks, {n_ng} flagged for review",
             ""]
    for r in results:
        mark = "✅ OK" if r["ok"] else f"⚠️ Needs review: {r['reason']}"
        lines.append(f"Chunk {r['index'] + 1}: {mark}")
    return "\n".join(lines)


def annotate_formatted(pairs, results):
    """Build the display version of the formatted text with ⚠️ markers on suspicious chunks."""
    ng = {r["index"]: r["reason"] for r in results if not r["ok"]}
    out = []
    for i, (_, fmt, _) in enumerate(pairs):
        if i in ng:
            out.append(f"⚠️ [NEEDS REVIEW chunk {i + 1}: {ng[i]}]\n{fmt}")
        else:
            out.append(fmt)
    return "\n\n".join(out)


# ─────────────────────────────────────────────────────────
# Minutes generation
# ─────────────────────────────────────────────────────────
MINUTES_INSTRUCTION_JA = (
    "以下の整形済み文字起こしから、日本語の議事メモをMarkdownで作成して"
    "ください。構成は次のとおり:\n"
    "## 概要（2〜3文）\n## 主な論点\n## 決定事項\n## TODO・宿題\n"
    "該当する内容がない節は「(なし)」と書くこと。"
    "本文にない事柄を追加しないこと。\n\n"
)

MINUTES_INSTRUCTION_EN = (
    "From the formatted transcript below, write meeting minutes in "
    "Markdown, IN THE SAME LANGUAGE as the transcript. Structure:\n"
    "## Summary (2-3 sentences)\n## Key Points\n## Decisions\n"
    "## Action Items\n"
    "Write \"(none)\" for sections with no relevant content. "
    "Do not add anything that is not in the transcript.\n\n"
)


def mmv_minutes(text, progress_cb=None, engine=None, lang=None):
    """Generate meeting minutes from the formatted text."""
    if progress_cb:
        progress_cb("Generating minutes…")
    instruction = MINUTES_INSTRUCTION_JA if _is_ja(lang) else MINUTES_INSTRUCTION_EN
    src = text
    if len(src) > MINUTES_MAX_CHARS:
        src = src[:MINUTES_MAX_CHARS] + "\n…(truncated)"
    out, err = _mmv_call(instruction, engine, context=src)
    if err:
        return f"[ERROR] minutes generation failed: {err}"
    return out


# ─────────────────────────────────────────────────────────
# Secretary digest output (integration with the MOBIUS ecosystem)
# ─────────────────────────────────────────────────────────
def write_secretary_digest(meta, formatted, minutes, fidelity_report):
    """
    Write voice_note_<ts>.md into the MOBIUS secretary system's digests directory.
    Returns: the path of the written file.
    """
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = os.path.join(DIGEST_DIR, f"voice_note_{ts}.md")
    lines = [
        "# Voice Note Digest",
        "",
        f"- source_audio: `{meta.get('source', '?')}`",
        f"- generated_at: {time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())}",
        f"- transcriber: whisper {WHISPER_MODEL_SIZE}",
        f"- language: {meta.get('language', '?')}",
        f"- formatter: {meta.get('engine', '?')} via selected engine",
        f"- format_profile: {meta.get('format_profile', '')}",
        "- human_verified: false",
        f"- speaker_backend: {meta.get('speaker_backend') or '(no speaker attribution)'}",
        f"- fidelity: {meta.get('fidelity_summary', '(not verified)')}",
        "",
    ]
    if minutes:
        lines += ["## Minutes", "", minutes, ""]
    lines += ["## Formatted Text", "", formatted, ""]
    if fidelity_report:
        lines += ["## Fidelity Report", "", fidelity_report, ""]
    os.makedirs(DIGEST_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


# ─────────────────────────────────────────────────────────
# GPU helpers
# ─────────────────────────────────────────────────────────
def get_free_vram_gb(gpu_id):
    """Return the free VRAM (GB) of the given GPU"""
    if not torch.cuda.is_available():
        return 0.0
    total    = torch.cuda.get_device_properties(gpu_id).total_memory / 1024**3
    reserved = torch.cuda.memory_reserved(gpu_id) / 1024**3
    return total - reserved


def get_best_gpu():
    """Return the index of the GPU with the most free VRAM, or None if there is none"""
    best_id, best_free = None, 0.0
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            free = get_free_vram_gb(i)
            if free > best_free:
                best_id, best_free = i, free
    return best_id


def gpu_info_str():
    """Return the GPU list as a string"""
    if not torch.cuda.is_available():
        return "GPU: none (CPU mode)"
    lines = []
    for i in range(torch.cuda.device_count()):
        prop  = torch.cuda.get_device_properties(i)
        total = prop.total_memory / 1024**3
        free  = get_free_vram_gb(i)
        lines.append(f"GPU{i}: {prop.name}  free {free:.1f}/{total:.1f}GB")
    return "  |  ".join(lines)


def wait_for_vram(gpu_id, required_gb, timeout_sec, progress_cb):
    """
    Wait until the free VRAM of the given GPU exceeds required_gb.
    Returns False if it cannot be secured within timeout_sec seconds.
    Progress is reported to the UI via progress_cb(msg).
    """
    if gpu_id is None:
        return True  # No waiting needed in CPU mode
    for i in range(timeout_sec):
        free = get_free_vram_gb(gpu_id)
        if free >= required_gb:
            return True
        progress_cb(f"Waiting for VRAM… GPU{gpu_id}: free {free:.1f}GB / required {required_gb:.1f}GB ({i+1}/{timeout_sec}s)")
        time.sleep(1)
    return False


# ─────────────────────────────────────────────────────────
# GUI main class
# ─────────────────────────────────────────────────────────
class WhisperMMVGUI:

    def __init__(self, master):
        self.master = master
        master.title(f"Whisper {WHISPER_MODEL_SIZE} + {MMV_RELEASE} ({MMV_MODEL})  Voice Formatting Tool")
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # State variables
        self.mode_var   = tk.StringVar(value="Starting…")
        self.status_var = tk.StringVar(value="Initializing…")
        self.kill_flag  = threading.Event()

        self.opt_speaker  = tk.BooleanVar(value=False)
        self.opt_fidelity = tk.BooleanVar(value=False)
        self.opt_minutes  = tk.BooleanVar(value=False)
        self.engine_var   = tk.StringVar(value="M")   # M = local / L = Groq 120B

        self.whisper_thread = None
        self.post_thread    = None
        self.whisper_model  = None
        self.whisper_device = None
        self.last_whisper_text = ""
        self.last_segments     = None
        self.last_language     = None   # Language code auto-detected by Whisper
        self.current_audio     = None
        self.last_result       = None   # Kept for saving the digest

        self._build_ui()

        # Startup check (in a thread so it does not block GUI startup)
        threading.Thread(target=self._startup_check, daemon=True).start()

    # ─────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────
    def _build_ui(self):
        m = self.master

        # Top status bar
        bar = tk.Frame(m, bg="#f0f0f0", pady=4)
        bar.pack(fill="x")
        tk.Label(bar, textvariable=self.mode_var,
                 fg="#1a4a8a", bg="#f0f0f0",
                 font=("Meiryo", 10, "bold")).pack(side="left", padx=8)
        tk.Label(bar, textvariable=self.status_var,
                 fg="#555", bg="#f0f0f0",
                 font=("Meiryo", 9)).pack(side="left", padx=4)

        # Text areas (split left/right)
        pane = tk.Frame(m)
        pane.pack(expand=True, fill="both", padx=6, pady=4)

        # Left: raw Whisper log
        lf = tk.LabelFrame(pane, text=" Whisper raw log (real-time) ",
                            fg="navy", font=("Meiryo", 10, "bold"))
        lf.pack(side="left", expand=True, fill="both", padx=(0, 3))
        self.whisper_textbox = scrolledtext.ScrolledText(
            lf, font=("Meiryo", 9), width=54, height=26, wrap="word")
        self.whisper_textbox.pack(expand=True, fill="both")
        self.whisper_progress = tk.Label(
            lf, text="", fg="green", font=("Meiryo", 9))
        self.whisper_progress.pack()
        tk.Button(lf, text="Copy all",
                  command=lambda: self.copy_to_clipboard(self.whisper_textbox)
                  ).pack(pady=2)

        # Right: MMV output tabs (formatted / minutes / fidelity report)
        rf = tk.LabelFrame(pane, text=f" {MMV_RELEASE} ({MMV_MODEL})  Output ",
                            fg="purple", font=("Meiryo", 10, "bold"))
        rf.pack(side="left", expand=True, fill="both", padx=(3, 0))
        self.notebook = ttk.Notebook(rf)
        self.notebook.pack(expand=True, fill="both")

        self.fmt_textbox      = self._make_tab("Formatted")
        self.minutes_textbox  = self._make_tab("Minutes")
        self.fidelity_textbox = self._make_tab("Fidelity Report")

        self.fmt_progress = tk.Label(
            rf, text="Waiting for input.", fg="gray", font=("Meiryo", 9))
        self.fmt_progress.pack()
        tk.Button(rf, text="Copy all from current tab",
                  command=self.copy_active_tab).pack(pady=2)

        # Options row
        of = tk.Frame(m)
        of.pack(pady=2)
        tk.Checkbutton(of, text="Speaker attribution", variable=self.opt_speaker,
                       font=("Meiryo", 10)).pack(side="left", padx=8)
        tk.Checkbutton(of, text="Fidelity check", variable=self.opt_fidelity,
                       font=("Meiryo", 10)).pack(side="left", padx=8)
        tk.Checkbutton(of, text="Generate minutes", variable=self.opt_minutes,
                       font=("Meiryo", 10)).pack(side="left", padx=8)

        # Engine selector row (default = local M / optional = cloud L 120B)
        ef = tk.Frame(m)
        ef.pack(pady=2)
        tk.Label(ef, text="Engine:", font=("Meiryo", 10, "bold")
                 ).pack(side="left", padx=(8, 4))
        tk.Radiobutton(
            ef, text=f"MMV formatting ({MMV_MODEL} · local)",
            variable=self.engine_var, value="M",
            font=("Meiryo", 10)).pack(side="left", padx=4)
        label_l = (f"MMV-L ({MMV_L['model']} · Groq cloud)"
                   if MMV_L else "MMV-L (unavailable)")
        self.engine_l_btn = tk.Radiobutton(
            ef, text=label_l, variable=self.engine_var, value="L",
            font=("Meiryo", 10), fg="#a05000",
            command=self._confirm_cloud_engine)
        self.engine_l_btn.pack(side="left", padx=4)
        if MMV_L is None:
            self.engine_l_btn.config(state="disabled")

        # Button row
        bf = tk.Frame(m)
        bf.pack(pady=6)
        self.select_btn = tk.Button(
            bf, text="🎙  Select audio file → Start",
            font=("Meiryo", 11), width=26, command=self.select_file)
        self.select_btn.pack(side="left", padx=6)

        self.kill_btn = tk.Button(
            bf, text="⏹  Stop Whisper → MMV formatting",
            font=("Meiryo", 11), fg="red", width=24,
            command=self.kill_whisper, state="disabled")
        self.kill_btn.pack(side="left", padx=6)

        self.digest_btn = tk.Button(
            bf, text="📤  Save to secretary digest",
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
        """Ask for consent to external transmission when MMV-L (cloud) is selected. Revert to M on refusal."""
        if self.engine_var.get() != "L":
            return
        ok = messagebox.askokcancel(
            "Confirm cloud transmission",
            "Selecting MMV-L sends the transcript text to Groq (cloud)\n"
            f"(model: {MMV_L['model']}).\n\n"
            "Processing will no longer be fully local. Continue?")
        if not ok:
            self.engine_var.set("M")

    def _active_engine(self):
        """Return the binding of the currently selected MMV engine."""
        if self.engine_var.get() == "L" and MMV_L is not None:
            return MMV_L
        return MMV_M

    # ─────────────────────────────────────────
    # Startup check (background)
    # ─────────────────────────────────────────
    def _startup_check(self):
        gpu_str    = gpu_info_str()
        ok, ol_msg = check_mmv_ready()
        self.ui(lambda: self.mode_var.set(gpu_str))
        self.ui(lambda: self.status_var.set(ol_msg))
        if not ok:
            self.ui(lambda: messagebox.showwarning("MMV not ready", ol_msg))

    # ─────────────────────────────────────────
    # UI helpers
    # ─────────────────────────────────────────
    def ui(self, func):
        """Thread-safe UI update from a background thread"""
        self.master.after(0, func)

    def _add_context_menu(self, tb):
        menu = tk.Menu(tb, tearoff=0)
        menu.add_command(label="Copy",
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
    # File selection / start processing (main thread)
    # ─────────────────────────────────────────
    def select_file(self):
        filepath = filedialog.askopenfilename(
            title="Select an audio file",
            filetypes=[
                ("Audio Files",
                 "*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.wma *.mp4 *.mkv"),
                ("All Files", "*.*"),
            ]
        )
        if not filepath:
            return

        # Reset UI (called directly since this is the main thread)
        self.kill_flag.clear()
        self.last_whisper_text = ""
        self.last_segments     = None
        self.last_language     = None
        self.current_audio     = filepath
        self.last_result       = None
        self.digest_btn.config(state="disabled")
        self.whisper_textbox.delete("1.0", tk.END)
        for tb in (self.fmt_textbox, self.minutes_textbox,
                   self.fidelity_textbox):
            tb.delete("1.0", tk.END)
        self.whisper_progress.config(text="")
        self.fmt_progress.config(text="Processing starts after Whisper finishes.")
        self._set_processing(True)
        self.status_var.set("Preparing…")

        self.whisper_thread = threading.Thread(
            target=self.run_whisper, args=(filepath,), daemon=True)
        self.whisper_thread.start()

    # ─────────────────────────────────────────
    # VRAM release
    # ─────────────────────────────────────────
    def _release_whisper_model(self):
        """Release the Whisper model from VRAM"""
        if self.whisper_model is not None:
            del self.whisper_model
            self.whisper_model  = None
            self.whisper_device = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # ─────────────────────────────────────────
    # Whisper processing (background thread)
    # ─────────────────────────────────────────
    def run_whisper(self, audio_path):
        try:
            # ── Step 1: check free VRAM without stopping other processes
            self.ui(lambda: self.whisper_progress.config(
                text="Checking free VRAM…"))
            # External inference servers belong to their owners; do not unload them.
            time.sleep(0.1)

            # ── Step 2: wait until enough VRAM is free
            gpu_id = get_best_gpu()
            if gpu_id is not None:
                def progress_cb(msg):
                    self.ui(lambda: self.whisper_progress.config(text=msg))

                ok = wait_for_vram(gpu_id, MIN_FREE_VRAM_GB,
                                   VRAM_WAIT_MAX_SEC, progress_cb)
                if not ok:
                    # Do our best even after a timeout (CPU fallback)
                    gpu_id = None
                    self.ui(lambda: self.whisper_progress.config(
                        text="Not enough VRAM; switching to CPU mode…"))
                    time.sleep(1)

            device = f"cuda:{gpu_id}" if gpu_id is not None else "cpu"
            prop_str = ""
            if gpu_id is not None:
                prop  = torch.cuda.get_device_properties(gpu_id)
                free  = get_free_vram_gb(gpu_id)
                prop_str = f"GPU{gpu_id}: {prop.name} free {free:.1f}GB"
            else:
                prop_str = "CPU mode"

            self.ui(lambda: self.status_var.set(f"Whisper running… [{prop_str}]"))

            # ── Step 3: load the Whisper model (reload only when the device changed)
            if self.whisper_model is None or self.whisper_device != device:
                self.ui(lambda: self.whisper_progress.config(
                    text=f"Loading Whisper model ({WHISPER_MODEL_SIZE})…"))
                self.whisper_model  = whisper.load_model(
                    WHISPER_MODEL_SIZE, device=device)
                self.whisper_device = device

            # ── Step 4: transcribe (capture stdout for real-time display)
            self.ui(lambda: self.whisper_progress.config(
                text="Transcribing… (real-time display)"))
            capture    = WhisperOutputCapture(self._append_whisper_line)
            old_stdout = sys.stdout
            sys.stdout = capture
            try:
                result = self.whisper_model.transcribe(
                    audio_path, language=WHISPER_LANGUAGE, verbose=True)
            finally:
                sys.stdout = old_stdout

            self.last_whisper_text = result["text"]
            self.last_segments     = result.get("segments") or None
            self.last_language     = result.get("language") or "ja"
            self._set_textbox(self.whisper_textbox, result["text"])
            self.ui(lambda: self.whisper_progress.config(text="✅ Whisper finished"))
            self.ui(lambda: self.status_var.set(
                "Whisper finished. Releasing VRAM and starting post-processing…"))

            # ── Step 5: release Whisper's VRAM and move on to post-processing
            self._release_whisper_model()
            time.sleep(2)  # Wait for the cache clear to take effect
            self.ui(lambda: self.mode_var.set(gpu_info_str()))

            # If kill_flag is set, kill_whisper has already started post-processing
            if not self.kill_flag.is_set():
                self.post_thread = threading.Thread(
                    target=self.run_postprocess,
                    args=(self.last_whisper_text, self.last_segments,
                          audio_path),
                    daemon=True)
                self.post_thread.start()

        except Exception as e:
            err = str(e)
            self.ui(lambda: self.status_var.set(f"Whisper error: {err}"))
            self.ui(lambda: self.whisper_progress.config(text="❌ Error"))
            self.ui(lambda: self._set_processing(False))

    # ─────────────────────────────────────────
    # Post-processing (speakers → formatting → fidelity → minutes), background thread
    # ─────────────────────────────────────────
    def run_postprocess(self, text, segments, audio_path):
        try:
            engine = self._active_engine()
            lang   = self.last_language
            speaker_backend = None
            with_speakers   = False
            work_text       = text

            # ── Step 1: speaker attribution
            if self.opt_speaker.get() and segments and len(segments) > 1:
                self._post_progress("Attributing speakers…")
                work_text, speaker_backend = speaker_attribution(
                    audio_path, segments, self._post_progress, engine, lang)
                with_speakers = True

            # ── Step 2: MMV formatting
            formatted, pairs = mmv_formatting(
                work_text, self._post_progress,
                with_speakers=with_speakers, engine=engine, lang=lang)

            # ── Step 3: fidelity check
            fidelity_results = []
            fidelity_report  = audit_report(engine["format_audit"]) if engine.get("format_audit") is not None else ""
            display_text     = formatted
            if self.opt_fidelity.get() and pairs:
                fidelity_results = mmv_fidelity_check(
                    pairs, self._post_progress, engine, lang)
                fidelity_report += "\n\n" + build_fidelity_report(fidelity_results)
                display_text     = annotate_formatted(pairs, fidelity_results)
                self._set_textbox(self.fidelity_textbox, fidelity_report)
            self._set_textbox(self.fidelity_textbox, fidelity_report)
            self._set_textbox(self.fmt_textbox, display_text)

            # ── Step 4: minutes
            minutes = ""
            if self.opt_minutes.get() and formatted.strip():
                minutes = mmv_minutes(formatted, self._post_progress,
                                      engine, lang)
                self._set_textbox(self.minutes_textbox, minutes)

            # ── Step 5: keep the result for saving the digest
            n_ng = sum(1 for r in fidelity_results if not r["ok"])
            fidelity_summary = (
                f"{len(fidelity_results)} chunks, {n_ng} flagged for review"
                if fidelity_results else "lexical/numeric preservation checked; semantic fidelity not verified" if engine.get("backend")=="mmv_format" else "(not verified)")
            engine_str = f"{engine['release']} ({engine['model']})"
            engine_str += " · local" if engine["local"] else " · Groq cloud"
            self.last_result = {
                "meta": {
                    "source": audio_path or self.current_audio or "?",
                    "engine": engine_str,
                    "language": lang or "?",
                    "speaker_backend": speaker_backend,
                    "fidelity_summary": fidelity_summary,
                    "format_profile": engine.get("profile_path", ""),
                },
                "formatted": formatted,
                "minutes": minutes,
                "fidelity_report": fidelity_report,
            }
            self.ui(lambda: self.digest_btn.config(state="normal"))

            retained = sum(r["status"]=="source_retained" for r in engine.get("format_audit",[]))
            done = (f"⚠️ Formatting finished: {retained} chunk(s) kept the unformatted source (see Fidelity Report)"
                    if retained else "✅ All steps complete")
            if fidelity_results and n_ng:
                done += f" (⚠️ {n_ng} flagged for review — see Fidelity Report)"
            self.ui(lambda: self.fmt_progress.config(text=done))
            self.ui(lambda: self.status_var.set(
                done + ". You can select the next file."))
            self.ui(lambda: self.mode_var.set(gpu_info_str()))
        except Exception as e:
            err = str(e)
            self.ui(lambda: self.fmt_progress.config(
                text=f"❌ Post-processing error: {err}"))
        finally:
            self.ui(lambda: self._set_processing(False))

    # ─────────────────────────────────────────
    # Save secretary digest (main thread)
    # ─────────────────────────────────────────
    def save_digest(self):
        if not self.last_result:
            return
        try:
            r = self.last_result
            path = write_secretary_digest(
                r["meta"], r["formatted"], r["minutes"],
                r["fidelity_report"])
            self.status_var.set(f"📤 Digest saved: {os.path.basename(path)}")
            messagebox.showinfo("Saved",
                                f"Saved to the secretary digest:\n{path}")
        except Exception as e:
            messagebox.showerror("Save failed", f"Failed to save the digest:\n{e}")

    # ─────────────────────────────────────────
    # Force-stop Whisper (main thread)
    # ─────────────────────────────────────────
    def kill_whisper(self):
        self.kill_flag.set()
        self.status_var.set("Stop requested. MMV will format the text captured so far.")
        self.whisper_progress.config(text="⏹ Stop requested (ends after transcribe completes)")
        self.kill_btn.config(state="disabled")

        current = self.whisper_textbox.get("1.0", tk.END).strip()
        # Strip the leading timestamps "[00:00.000 --> 00:05.000]" from the raw log
        current = re.sub(r"\[[\d:.]+\s*-->\s*[\d:.]+\]\s*", "", current)
        if current:
            self.fmt_progress.config(text=f"{MMV_RELEASE} formatting…")
            # Partial text has no segment info → speaker attribution is skipped
            self.post_thread = threading.Thread(
                target=self.run_postprocess, args=(current, None, None),
                daemon=True)
            self.post_thread.start()
        else:
            self.fmt_progress.config(
                text="No text captured yet. Processing will start automatically after Whisper finishes.")

    # ─────────────────────────────────────────
    # Window close handling
    # ─────────────────────────────────────────
    def on_closing(self):
        running = (
            (self.whisper_thread and self.whisper_thread.is_alive()) or
            (self.post_thread    and self.post_thread.is_alive())
        )
        if running:
            if not messagebox.askokcancel(
                    "Confirm", "Processing is in progress. Quit anyway?\n"
                             "(VRAM will be released automatically)"):
                return
        self._release_whisper_model()
        self.master.destroy()


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    root.minsize(1000, 650)
    gui = WhisperMMVGUI(root)
    root.mainloop()
