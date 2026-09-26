# Shipped engines on held-out audio: default vs readable draft (2026-09-26)

Exploratory, descriptive, unreviewed. Compares the three local engines shipped in mmv-voice v0.2.8 (code imported from the tagged release, unmodified) on audio none of them was tuned on. It does not change any default: readable mode is opt-in and labelled review-required regardless of these numbers.

## Conditions

| Code | Engine | Model | Contract |
|---|---|---|---|
| V12 | default `MMVFormatter` | `gemma4:12b-it-qat` | punctuation and line breaks only; any word/number change is rejected and the source chunk retained |
| R12 | `ReadableFormatter` | `gemma4:12b-it-qat` | rewrite for readability, no unsupported guesses, unclear spans kept and marked `（※要確認）`; review required |
| R26 | `ReadableFormatter` | `gemma4:26b-a4b-it-qat` | same prompt and rules, larger mixture-of-experts model |

Each condition ran 3 times per input at temperature 0 (repeat agreement, not independent seeds); the order of the three engines alternated per input and repeat. One isolated loopback Ollama instance on one GPU; Whisper `large-v3-turbo`, temperature 0, language pinned per panel, one run per clip, transcripts shared by all conditions.

## Inputs (fixed before inference)

- FLEURS test split (revision `70bb2e84b976…`): the first 12 rows per language in `test.tsv` order after excluding every text ID and normalised reference used by any earlier mmv-voice experiment (excluded: English 28, Japanese 28, Mandarin 8 IDs). Read speech, one sentence per clip.
- AMI `TS3010a` (CC BY 4.0, Mix-Headset, 17.4 min, four speakers): the baseline Whisper transcript saved in the v0.3b study; never formatted by readable mode before. Manual word reference from the AMI public annotations. Whisper's automatic language detection had labelled this English meeting as Dutch in that study; the transcript is used as-is.

## Metrics (all machine, calibrated on known-good and known-bad samples before use)

1. **Error rate against the reference** — WER (English, words) or CER (Japanese/Mandarin, characters) of the delivered text; punctuation and case ignored. The reference is never shown to the model. Reported as the paired change from the raw Whisper text (negative = closer to the recording), with a clip-level bootstrap 95% interval (10,000 resamples, seed 20260926).
2. **Invented tokens per 100 source tokens** — tokens present in the delivered text but in neither the Whisper source nor the reference (words for English, characters for Japanese/Mandarin). The default engine is 0 by construction.
3. **Omitted tokens per 100** — source content tokens (a short filler list removed) absent from the delivered text.
4. **Marker usefulness** — for each model-placed `（※要確認）`, whether the preceding phrase (3 words / 12 characters) overlaps a place where the Whisper source differs from the reference ("hit"); and the number of such error regions with no marker nearby ("unmarked"). Rule-triggered chunk-end markers are counted separately.
5. **Punctuation position F1 / position+type F1** against the reference punctuation.
6. **Median seconds per chunk** after model load (descriptive; the alternating order forces model reloads, so absolute values are not comparable to single-model runs).

## English FLEURS, 12 clips

| Metric | V12 default | R12 readable 12B | R26 readable 26B |
|---|---:|---:|---:|
| Raw Whisper error rate (same for all) | 3.44% | 3.44% | 3.44% |
| Delivered error rate | 3.44% | 3.16% | 3.44% |
| Change vs raw Whisper, clip mean [95% CI] | +0.00 pt [+0.00, +0.00] | -0.29 pt [-0.86, +0.00] | +0.00 pt [+0.00, +0.00] |
| Change vs V12 (paired) | — | -0.29 pt [-0.86, +0.00] | +0.00 pt [+0.00, +0.00] |
| Invented tokens / 100 | 0.00 | 0.00 | 0.00 |
| Omitted tokens / 100 | 0.00 | 0.29 | 0.00 |
| Punctuation position F1 | 0.856 | 0.883 | 0.846 |
| Punctuation position+type F1 | 0.807 | 0.831 | 0.795 |
| Model markers: hits / placed | 0/0 | 0/0 | 0/0 |
| Error regions left unmarked / total | 27/27 | 27/27 | 27/27 |
| Rule-marked chunks / chunks | 0/36 | 0/36 | 0/36 |
| Chunks formatted / unchanged / source retained | 9/24/3 | 15/21/0 | 12/24/0 |
| Clips with 3 identical repeats | 12/12 | 12/12 | 12/12 |
| Median seconds per chunk | 3.54 | 1.30 | 4.81 |

## Japanese FLEURS, 12 clips

| Metric | V12 default | R12 readable 12B | R26 readable 26B |
|---|---:|---:|---:|
| Raw Whisper error rate (same for all) | 6.10% | 6.10% | 6.10% |
| Delivered error rate | 6.10% | 6.20% | 6.30% |
| Change vs raw Whisper, clip mean [95% CI] | +0.00 pt [+0.00, +0.00] | +0.10 pt [+0.00, +0.29] | +0.19 pt [+0.00, +0.48] |
| Change vs V12 (paired) | — | +0.10 pt [+0.00, +0.29] | +0.19 pt [+0.00, +0.48] |
| Invented tokens / 100 | 0.00 | 0.00 | 0.00 |
| Omitted tokens / 100 | 0.00 | 0.00 | 0.10 |
| Punctuation position F1 | 0.831 | 0.876 | 0.877 |
| Punctuation position+type F1 | 0.831 | 0.876 | 0.877 |
| Model markers: hits / placed | 0/0 | 18/21 | 24/33 |
| Error regions left unmarked / total | 51/51 | 27/51 | 21/51 |
| Rule-marked chunks / chunks | 0/36 | 0/36 | 0/36 |
| Chunks formatted / unchanged / source retained | 33/3/0 | 33/3/0 | 33/3/0 |
| Clips with 3 identical repeats | 11/12 | 12/12 | 12/12 |
| Median seconds per chunk | 3.63 | 1.43 | 4.89 |

## Mandarin FLEURS, 12 clips

| Metric | V12 default | R12 readable 12B | R26 readable 26B |
|---|---:|---:|---:|
| Raw Whisper error rate (same for all) | 8.17% | 8.17% | 8.17% |
| Delivered error rate | 8.17% | 8.17% | 8.17% |
| Change vs raw Whisper, clip mean [95% CI] | +0.00 pt [+0.00, +0.00] | +0.00 pt [+0.00, +0.00] | +0.00 pt [+0.00, +0.00] |
| Change vs V12 (paired) | — | +0.00 pt [+0.00, +0.00] | +0.00 pt [+0.00, +0.00] |
| Invented tokens / 100 | 0.00 | 0.00 | 0.00 |
| Omitted tokens / 100 | 0.00 | 0.00 | 0.00 |
| Punctuation position F1 | 0.976 | 0.972 | 0.983 |
| Punctuation position+type F1 | 0.884 | 0.951 | 0.963 |
| Model markers: hits / placed | 0/0 | 12/14 | 15/21 |
| Error regions left unmarked / total | 54/54 | 30/54 | 27/54 |
| Rule-marked chunks / chunks | 0/36 | 0/36 | 0/36 |
| Chunks formatted / unchanged / source retained | 36/0/0 | 36/0/0 | 36/0/0 |
| Clips with 3 identical repeats | 12/12 | 10/12 | 12/12 |
| Median seconds per chunk | 3.71 | 1.37 | 4.91 |

## AMI TS3010a meeting (17.4 min, English)

| Metric | V12 default | R12 readable 12B | R26 readable 26B |
|---|---:|---:|---:|
| Raw Whisper error rate (same for all) | 43.26% | 43.26% | 43.26% |
| Delivered error rate | 43.26% | 43.74% | 43.35% |
| Change vs raw Whisper, clip mean [95% CI] | +0.00 pt [+0.00, +0.00] | +0.48 pt [+0.48, +0.48] | +0.09 pt [+0.09, +0.09] |
| Change vs V12 (paired) | — | +0.48 pt [+0.48, +0.48] | +0.09 pt [+0.09, +0.09] |
| Invented tokens / 100 | 0.00 | 0.00 | 0.37 |
| Omitted tokens / 100 | 0.00 | 3.52 | 9.28 |
| Punctuation F1 | n/a (manual reference has no punctuation) | n/a | n/a |
| Model markers: hits / placed | 0/0 | 2/3 | 22/24 |
| Error regions left unmarked / total | 423/423 | 421/423 | 402/423 |
| Rule-marked chunks / chunks | 0/18 | 3/18 | 5/18 |
| Chunks formatted / unchanged / source retained | 0/0/18 | 18/0/0 | 18/0/0 |
| Clips with 3 identical repeats | 1/1 | 0/1 | 0/1 |
| Median seconds per chunk | 4.08 | 3.70 | 2.06 |

### Meeting: what the readable engines removed or added (repeat 0)

| | R12 | R26 |
|---|---|---|
| Source tokens → delivered tokens | 1081 → 1016 | 1081 → 961 |
| Omitted content tokens (fillers excluded) | 38 — most frequent: `and`×6, `positive`×4, `have`×2, `it`×2, `that's`×2, `good`×2 | 103 — most frequent: `and`×10, `i'm`×8, `it`×6, `ok`×5, `have`×3, `that's`×3 |
| Invented tokens | 0 | 4: `50`, `comes`, `those`, `many` |
| Model markers placed | 1 | 8 |

Most of the omitted tokens are short function words and false starts (`and`, `it`, `i'm`), not the repetition loops (at most 4–5 of the omitted tokens sit inside a run of three or more identical tokens). R26 also invented a numeral (`50`), which is exactly the kind of change the mode promises not to make; the numeric rule flagged the chunk. Whisper transcribed parts of this meeting in Dutch (automatic language detection), and the markers on those spans (for example `In de Engels （※要確認）`) are hits only in the sense that the source is wrong there.

### Marker examples (repeat 0)

Hits — the marked span is a recognition error: `単語C（※要確認）` (reference `Sie`), `ジャカール・ブムタン（※要確認）` (reference `ジャカール/ブムタン`), `鄙视凯克（※要確認）` (reference `比什凯克`, Bishkek), `华硕EPC（※要確認）` (reference `Eee PC`).

Over-marking — the marked span matches the reference: `78（※要確認）ある提言` (the number is correct), `经济产出（※要確認）` (correct).

Unmarked — the remaining error regions (see the table rows "left unmarked") are mostly particles, one-character substitutions and punctuation-adjacent differences that the model did not treat as unclear.

## How to read this

- A negative "change vs raw Whisper" means the delivered text is closer to what was said than Whisper's own transcript; the default engine cannot move this number except through punctuation-insensitive normalisation (it should be ~0).
- Invented tokens are the direct measure of "unsupported guesses"; omitted tokens measure silent deletion. Both are 0 for V12 by construction and are the price of readable mode.
- Marker hits show whether `（※要確認）` lands on real recognition errors; unmarked error regions show what the reader would not be warned about. Neither is a semantic-safety guarantee.
- FLEURS clips are single read sentences, so chunking and fillers barely matter there; the meeting is where readable mode is meant to help and where it can also do the most damage.

## Limitations

- 12 clips per language and one meeting; exploratory; no significance test, no human rating, single automatic reference per clip (FLEURS references themselves contain punctuation-style choices).
- FLEURS and AMI may be in the models' training data; contamination unresolved.
- Repeats are temperature-0 re-runs, not independent samples.
- Token-level metrics cannot see meaning changes that keep the same tokens (e.g. a statement turned into a question by punctuation alone) and count legitimate paraphrases as invented/omitted tokens.
- The AMI transcript was produced under automatic language detection that chose Dutch; its raw WER is therefore high and the panel mainly tests behaviour on noisy input.

Raw outputs (all 3 repeats × 3 conditions × 37 inputs), the frozen plan and its hash, the scoring script with its calibration block, and the exact input manifest are kept in the measurement archive; the plan hash is recorded in `RESULTS.json`.
