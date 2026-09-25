---
title: MMV Voice
emoji: 🎙️
colorFrom: purple
colorTo: indigo
sdk: static
app_file: index.html
pinned: false
license: agpl-3.0
short_description: Whisper transcription + local Gemma punctuation with a preservation check
---

*The block above is Hugging Face Space metadata; it is not application configuration.*

# mmv-voice — Whisper large-v3-turbo + MMV formatting pipeline

> Governance-mediated voice pipeline: Whisper transcription, MMV-governed
> formatting, optional speaker attribution, fidelity check, minutes and
> secretary-digest output. A sibling of
> [mobius-style/mmv](https://github.com/mobius-style/mmv) — every LLM call
> goes through the MMV harness, never a raw API.

A Linux desktop GUI (Tk) that turns an audio file into verified, structured
text on your own machine. Whisper detects the language automatically
(about 100 languages); Japanese gets dedicated instructions, other languages
are processed with "reply in the same language as the input" instructions.

**v0.2 (2026-09-25) — local formatting engine replaced.** The default
formatter is now a *minimal-edit* formatter: it asks a local
`gemma4:12b-it-qat` (Ollama, via the MMV harness) to insert punctuation and
line breaks only, then **rejects any candidate whose words or numbers
changed** and keeps the raw transcript for that chunk instead. Measured
results and their limits are in [MMV_FORMAT_STATUS.md](MMV_FORMAT_STATUS.md).
This is a **local trial build**: no fine-tuning, no claim of general model
quality, small read-speech test panels only. The previous release is
preserved as tag `v0.1`.

## What it does

1. **Transcription** — Whisper `large-v3-turbo` (GPU when available,
   language auto-detected). The raw log streams into the left pane.
2. **Formatting (default engine: MMV-Format, local)** — punctuation and
   paragraph breaks only. Each chunk's candidate must pass a
   lexical/numeric preservation check; otherwise the unformatted source is
   retained and the "Verification report" tab shows source, candidate and
   rejection reason.
3. **Speaker attribution (optional, off by default)** — pyannote.audio if
   installed and gated models are approved; otherwise text-based
   attribution through MMV. Output is structured as `Speaker 1: …` turns
   (`話者1:` for Japanese). Unattributable utterances stay visibly
   `Speaker unknown`.
4. **Fidelity check (optional, off by default)** — an additional LLM pass
   comparing each source/formatted pair; suspicious chunks get a ⚠️ marker.
5. **Minutes (optional, off by default)** — Markdown minutes
   (summary / key points / decisions / action items) from the formatted
   text, first 24,000 characters.
6. **Secretary digest** — one button writes
   `voice_note_<ts>.md` into the MOBIUS secretary digest directory with
   metadata, source/candidate/reason audit and `human_verified: false`.

## Engines

| Engine | Model | Runs on | Purpose |
|---|---|---|---|
| **MMV-Format** (default) | `gemma4:12b-it-qat` (Ollama) | local | punctuation-only formatting with preservation check |
| **MMV-L** (opt-in) | `gpt-oss-120b` via Groq | **cloud** | legacy path; sends transcript text off-machine after an explicit confirmation dialog |

- MMV-Format uses the profile shipped in this repository
  (`profiles/mmv_format_12b_qat.json`): MMV `route_transformer`,
  `post_validator` and `force_reanchor_v2` stay on, temperature 0,
  `num_ctx` 8192, `max_tokens` 1024, `think: false`. The canonical MMV
  release profiles are not modified.
- Before the first call, the tool checks that the Ollama model tag **and
  digest** match the evaluated build
  (`38044be4f923e5a55264ed7df4eaac2676651a905f735197c504045140c02bd3`).
  On mismatch it does not generate and keeps the source text; it never
  silently falls back to another model.
- Normally one generation request per chunk, no quality-driven
  regeneration. The harness's own retry on transport/empty-response errors
  (max 1) remains.
- Input is split at about 1,000 characters without cutting an ASCII word or
  a numeric expression; the split is checked to reconstruct the original
  string exactly. An oversized single token is retained unformatted rather
  than cut.
- MMV-L reads its binding from the MMV release pointer
  (`operate-fr-bench/releases/large/current.yaml`) and needs
  `GROQ_API_KEY` (environment or `MOBIUS_MMV/.env`). Without it the
  cloud radio button is disabled. The digest records which engine was used.

**This is not a transcription-error corrector.** A candidate that fixes a
misheard word is still rejected because the words changed. Punctuation can
change meaning, and the preservation check does not prove semantic
fidelity. Typo correction, summarisation and speaker attribution are
separate problems. Languages other than Japanese and English are
unevaluated.

## Measured results (summary)

From [MMV_FORMAT_STATUS.md](MMV_FORMAT_STATUS.md), FLEURS read speech,
Whisper large-v3-turbo, 3 repeats per clip at temperature 0:

| Panel | Candidate acceptance | Actually formatted | Source retained | Punctuation-position F1 vs reference |
|---|---:|---:|---:|---:|
| Japanese, 12 new clips, v2 prompt | 91.7% (33/36) | 30/36 | 3/36 | 0.857 |
| Japanese, same clips, previous v1 prompt | 83.3% (30/36) | 24/36 | 6/36 | 0.857 |
| English, 8 clips (regression, 1 run) | 8/8 | 6/8 | 0/8 | — |

Acceptance means the candidate passed the preservation check, not that its
punctuation is correct. The post-hoc punctuation-position F1 is identical
for v1 and v2 (paired delta +0.001, bootstrap 95% CI [−0.089, +0.088]); v2
misses fewer sentence ends but inserts more commas than the reference. The
panels are small; none of this is a population guarantee. The 2026-09-24
trial that was put on HOLD is kept unchanged in
[eval/mmv_format_12b_qat_20260924.md](eval/mmv_format_12b_qat_20260924.md).

## Repository layout

```
mmv-voice/
├── whisper_gui.py                 # GUI and pipeline
├── voice_mmv.py                   # MMV-Format engine: prompts, preservation check, splitting, audit
├── profiles/mmv_format_12b_qat.json
├── tests/test_mmv_formatter.py    # boundary and preservation tests (HTTP fixture, real harness path)
├── eval/                          # measured trials and raw metrics (JSON)
├── MMV_FORMAT_STATUS.md           # current adoption status and measurements
├── launch.sh / whisper_tool.desktop
├── requirements.txt
├── LICENSE                        # AGPL-3.0
└── README.md
```

Private audio, transcripts and local backups are ignored by `.gitignore`.
**Never commit audio files.**

## Requirements and tested environment

| Item | Tested with |
|---|---|
| OS | Linux (Tk desktop) |
| GPU | 2 × NVIDIA RTX 5070 Ti (16 GB); Ollama on GPU 0, Whisper on GPU 1 |
| Python | 3.10.14 (pyenv) |
| PyTorch | 2.10.0 + cu128 (Blackwell needs cu128 or newer) |
| Whisper | openai-whisper 20250625 |
| LLM | Ollama + `gemma4:12b-it-qat` (7.2 GB, Q4_0 QAT) |
| MMV harness | [mobius-style/mmv](https://github.com/mobius-style/mmv), `operate-fr-bench/harness/adapters.py` |

A single 16 GB GPU also works: Whisper is loaded only after the free VRAM
threshold (`MIN_FREE_VRAM_GB`, default 7 GB) is met, falls back to CPU
after a 30 s wait, and is released before formatting starts. The launcher
does **not** start or stop Ollama; an inference server belongs to whoever
started it.

## Setup

```bash
# 1. system packages
sudo apt install ffmpeg python3-tk
# 2. PyTorch matching your CUDA (Blackwell example)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
# 3. Python packages (openai-whisper, requests, pyyaml, rcgov)
pip install -r requirements.txt
# 4. Ollama and the evaluated model (network and disk required, once)
ollama serve            # in another terminal, if not already running as a service
ollama pull gemma4:12b-it-qat
# 5. the MMV harness
git clone https://github.com/mobius-style/mmv ~/MOBIUS_MMV
export MMV_REPO=~/MOBIUS_MMV
```

Optional: `pip install pyannote.audio` and accept the Hugging Face gates
for `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` for
audio-based speaker attribution.

## Run

```bash
bash launch.sh
```

or install `whisper_tool.desktop` (edit its `Exec=` path) and use the
desktop icon. Pick an audio file; transcription starts immediately and
formatting follows. "Stop Whisper → format" formats what has been
transcribed so far.

## Configuration

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MMV_REPO` | `~/デスクトップ/mobius_ai/MOBIUS_MMV` | path of the MMV repository (harness + release pointers + digest dir) |
| `MMV_FORMAT_HOST` | `http://127.0.0.1:11434` | Ollama endpoint for MMV-Format; **loopback HTTP only**, anything else is refused |
| `WISPER_PYTHON` | pyenv 3.10.14, then auto-detect | interpreter used by `launch.sh` |
| `GROQ_API_KEY` | — | only for the opt-in MMV-L cloud engine |

Constants at the top of `whisper_gui.py`:

| Constant | Default | Meaning |
|---|---|---|
| `WHISPER_MODEL_SIZE` | `large-v3-turbo` | `large-v3` is more accurate, ~4.7× slower, needs ~11 GB |
| `WHISPER_LANGUAGE` | `None` (auto) | e.g. `"ja"` to pin the language |
| `MIN_FREE_VRAM_GB` | `7.0` | raise to `11.0` for `large-v3` |
| `FORMAT_CHUNK_CHARS` | `1000` | maximum characters per formatting request |

If the MMV harness or the formatting profile cannot be loaded, formatting
is disabled with a visible error; there is no silent fallback to a raw
model call.

## Verification report, minutes and digest

- **Verification report tab** — for every chunk: status (formatted /
  unchanged / source retained), reason, source text and model candidate.
  With the optional fidelity check on, the LLM verdicts are appended and
  flagged chunks are marked `⚠️` in the formatted text.
- **Minutes tab** — Markdown; sections without content read "(none)"; the
  instruction forbids adding anything not in the transcript.
- **Secretary digest** — written to
  `$MMV_REPO/addons/secretary/state/digests/voice_note_<ts>.md` with
  source audio, language, engine, profile path, speaker backend, fidelity
  summary and `human_verified: false`.

## Tests

```bash
python3 -m pytest -q tests/
```

Covers the real harness path through a local HTTP fixture, rejection of
word/number changes, model-digest mismatch, exception handling that keeps
the exact source, splitting without cutting tokens, refusal of non-loopback
endpoints, and digest provenance. Passing tests are not a claim about
formatting quality; that comes only from held-out audio trials recorded in
`eval/`.

## Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `MMV not connected` | Ollama not running | start `ollama serve` (or the system service) |
| `gemma4:12b-it-qat with measured digest … is required` | model missing or a different build | `ollama pull gemma4:12b-it-qat`; a different digest is outside the evaluated configuration |
| `MMV configuration error` | `MMV_REPO` wrong or harness moved | set `MMV_REPO` |
| `MMV_FORMAT_HOST must be a loopback HTTP origin` | remote endpoint configured | use `http://127.0.0.1:<port>` |
| `No module named 'whisper'` | packages not installed | `pip install -r requirements.txt` |
| `ffmpeg not found` | ffmpeg missing | `sudo apt install ffmpeg` |
| `CUDA out of memory` | not enough VRAM | close other GPU applications, or let the tool fall back to CPU |

## Versions

| Tag | Date | Content |
|---|---|---|
| `v0.1` | 2026-07-06 | original release: MMV-M (`gemma4:12b`) via release pointer, filler removal and rewriting, fidelity check, speaker attribution, minutes, digest, opt-in MMV-L |
| `v0.2` | 2026-09-25 | default engine replaced by MMV-Format (punctuation-only, preservation check, digest pinning, audit in report); speaker / fidelity / minutes now off by default; English documentation; measured trials in `eval/` |

The v0.1 formatter rewrote text (filler removal, spoken-to-written style)
and relied on an LLM fidelity check to catch silent changes. v0.2 inverts
that: the model may only add punctuation, and a deterministic check
enforces it. If you need the old behaviour, check out tag `v0.1`.

## Privacy

Everything runs locally by default. Text leaves the machine only when
MMV-L is selected, and only after a confirmation dialog. No audio,
transcripts or digests are part of this repository.

## License

AGPL-3.0 — Copyright (C) 2025-2026 MOBIUS LLC (author: Taiko Toeda).
Sibling of [mobius-style/mmv](https://github.com/mobius-style/mmv). The MMV
harness, frozen profiles and release pointers are artefacts of the mmv
repository; this repository contains only the application layer that calls
them.
