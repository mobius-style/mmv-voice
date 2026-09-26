# mmv-voice v0.2.2 — Mandarin Chinese reference measurement

**Status: exploratory local measurement completed; suitable as a bounded release-note reference, not as a general Chinese-quality claim.** The shipped `v0.2.2` formatter accepted 21/24 Mandarin runs (87.5%) and produced identical output across all three temperature-zero repeats for each clip. On these eight FLEURS clips, delivered punctuation position F1 rose from 0.278 to 0.786, while position+type F1 rose from 0.056 to 0.500. Character error rate remained exactly 14.45% before and after formatting by construction: accepted output preserves lexical content, and rejected output returns the source.

## Five-line summary

| Line | Language / output | Acceptance | CER (95% clip-bootstrap CI) | Position F1 (95% CI) | Position+type F1 (95% CI) |
|---:|---|---:|---:|---:|---:|
| 1 | Mandarin acceptance | 21/24 runs = 87.50%; 7/8 clips passed all repeats | — | — | — |
| 2 | Mandarin Whisper raw | — | 14.45% [5.14%, 24.20%] | 0.278 [0.000, 0.500] | 0.056 [0.000, 0.136] |
| 3 | Mandarin delivered | 87.50% | 14.45% [5.14%, 24.20%] | 0.786 [0.667, 0.912] | 0.500 [0.296, 0.646] |
| 4 | English Whisper raw (saved 2026-09-24) | — | not recomputed | 0.766 [0.605, 0.909] | 0.681 [0.453, 0.885] |
| 5 | English delivered (saved 2026-09-24) | 24/24 accepted | not recomputed | 0.769 [0.653, 0.889] | 0.500 [0.353, 0.655] |

All intervals are descriptive percentile 95% intervals from 10,000 resamples of independent clip IDs (fixed seed 20260926). The delivered estimates keep the three repeats clustered inside each clip; 24 outputs are not treated as 24 independent observations.

## Frozen protocol and provenance

The plan was frozen before acquisition as SHA-256 `4e17e380f35111ce6c1b100a015c88601f090f718e0ad0e0b75747b3d9d6edfd`. The study used the first eight distinct text IDs in `test.tsv` order from Google FLEURS `cmn_hans_cn`, revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd` (101.62 seconds total; CC BY 4.0). `samples.json` records every reference, order index, duration, and audio SHA-256.

Each clip was transcribed exactly once by Whisper `large-v3-turbo` with `language=zh` and temperature 0. The formatter was the unmodified shipped `voice_mmv.py` at commit `18cd76ea131e53e26fd4d2752ed78432955417ae` / tag `v0.2.2`. It used `gemma4:12b-it-qat`, digest `38044be4f923e5a55264ed7df4eaac2676651a905f735197c504045140c02bd3`, the shipped profile, temperature 0, and three calls per transcript.

Chinese takes the **`en` prompt branch**, not `ja` and not a third generic branch: line 87 of the shipped formatter selects `ja` only for language codes beginning with `ja`, otherwise `en`. That English instruction explicitly requires output in the input language. The isolated Ollama server listened on port 11436, used GPU0, and was stopped by exact PID after inference; the pre-existing service on 11434 remained running.

## Measurements

Acceptance was 21/24 per run (87.50%, clustered bootstrap CI [62.50%, 100.00%]) and 7/8 per clip when a clip counts only if all three repeats passed (87.50%, bootstrap CI [62.50%, 100.00%]). Every repeat was 7/8; all candidate, delivered text, status, reason, and acceptance decisions were identical within each clip. There were 21 formatted outputs, zero accepted-but-unchanged outputs, and three source-retained outputs. Median formatter time was 0.798 seconds per call (first-load time is present in the per-run record and is not removed).

Mandarin raw CER was 51/353 = 14.45%; delivered CER was 153/1059 = 14.45%. Delivered counts are tripled because all three outputs are retained, but the rate and its clip-bootstrap interval are exactly equal to raw. This equality is an implementation invariant, not evidence that formatting improved ASR accuracy.

For Mandarin, delivered-minus-raw F1 was +0.508 for boundary position (95% CI [0.283, 0.826]) and +0.444 for boundary+type (95% CI [0.283, 0.583]). On the saved English panel, the corresponding changes were +0.003 [-0.059, 0.081] and -0.181 [-0.281, -0.075]. Thus English boundary placement was essentially unchanged in this panel, while exact punctuation type was lower after formatting; the formatter's semicolon choices often differed from the reference.

## Metric definition

CER applies Unicode NFKC normalization and lowercase, removes Unicode punctuation and whitespace, then computes micro character-level Levenshtein distance. Punctuation scoring first maps common ASCII forms to full-width Chinese equivalents (for example `,→，`, `.→。`, `?→？`, `!→！`, ASCII parentheses to full-width parentheses); ideographic comma `、` remains distinct from `，`. It removes punctuation and spaces to obtain content-character sequences, aligns hypothesis content to reference content with deterministic global minimum-edit alignment, and projects each hypothesis punctuation boundary onto the aligned reference boundary. Position F1 matches boundary only; position+type F1 also requires the normalized punctuation type. Counts are micro-aggregated; bootstrap sampling is by clip.

The scorer passed fixed known-good and known-bad probes: exact identity, no punctuation, wrong type at the correct boundary, shifted boundary, ASCII/full-width equivalence, punctuation-free CER identity, and a lexical substitution. Machine checks are recorded in `RESULTS.json`; they validate the implementation behavior tested, not the linguistic correctness of the reference punctuation.

## Failure case

All three rejected runs were clip `cmn_hans_cn_1779`. Whisper produced `特朗普与土耳其总统雷杰普、塔伊普、埃尔多安通话后发表了声明`; the model proposed `特朗普与土耳其总统雷杰普·塔伊普·埃尔多安通话后发表了声明`. The proposal moves toward the reference's name separators, but the shipped lexical guard treats replacing `、` with `·` as a content change, rejects it, and returns the exact source. This is correctly counted as failure under the frozen shipped-output protocol, not retrospectively rescued because the candidate looks preferable.

## Existing English comparison

English values were computed only from the saved 2026-09-24 unseen hold-out (per-clip outputs of the 2026-09-24 trial, not in this repository; summarized in `eval/mmv_format_12b_qat_20260924.md`): eight clips, three saved formatter outputs per clip, 24/24 accepted. That earlier `B` prompt is byte-for-byte the same English prompt now shipped in v0.2.2. No English model or ASR call was made in this study. The same scorer, punctuation mapping, alignment, aggregation, bootstrap count, clustering rule, and seed family were used for English and Mandarin.

## Limitations

- This is a small convenience panel: eight clean read-speech clips from one public dataset. It does not measure meetings, spontaneous speech, noise, long recordings, dialect breadth, code-switching, or multiple speakers.
- The three temperature-zero calls were identical and are not independent seeds. The independent sampling unit is the clip (n=8); intervals are wide and descriptive, with no hypothesis test or multiplicity claim.
- **FLEURS contamination is unresolved.** FLEURS is public, the model's exact training corpus/cutoff is unavailable, and this run cannot perform a meaningful canary or corpus-level 13-gram exclusion. These numbers therefore cannot establish generalization to unseen Chinese text.
- The reference itself is one punctuation rendering. Position/type F1 rewards agreement with it, not all linguistically acceptable punctuation. English semicolon penalties illustrate this distinction.
- Global alignment is deterministic but can choose one of several equally short paths around repeated characters; boundary scores near ASR edits may depend on that tie rule. The method and tie order are frozen and disclosed.
- CER deliberately removes punctuation and therefore cannot assess the formatting benefit; equality is expected. The lexical validator likewise does not prove semantic adequacy or ASR correctness.
- During the post-run health check, the already-occupied physical GPU1 reported a reset-required kernel condition. This trial had explicitly used physical GPU0, completed all audio/model calls, and persisted all outputs before that observation; GPU1 and its unrelated process were not stopped or reset.

## Research gates and claim grade

【Anecdotal / exploratory / unreviewed】 local engineering evidence. G1 passed locally: the timestamped plan, sample rule, metrics, repeats, and stopping rule were hashed before collection, but there was no external preregistration. G2 limits claims to this shipped build and panel. G3 reports effects and clip-bootstrap 95% intervals without a significance or power claim; n=8 is underpowered for population-level guarantees. G4 uses calibrated deterministic machine metrics; no human-rater reliability was measured, so no subjective naturalness claim is made. G5 fails for general performance because FLEURS contamination remains unresolved. G6 preserves the negative case and the two strongest threats—small single-domain sample and unresolved contamination—and makes no novelty claim.

The falsification condition was met in one bounded sense: the system did not accept all clips, and exact-type punctuation remained only 0.500 F1. The defensible conclusion is therefore narrow: on this frozen eight-clip panel, the shipped delivery path usually added reference-aligned punctuation without changing delivered lexical content; broader Mandarin quality remains unestablished.

## Reproduction artifacts

`PLAN.md` and `PLAN.md.sha256` freeze the protocol. `samples.json` and `cmn_hans_cn/` contain selection/audio provenance; `asr/` contains one transcription per clip; `per_clip/` contains all 24 formatter records; `failure_cases.json` extracts rejected runs; `runtime_conditions.json` records code/profile/model identity; `score_results.py` and `RESULTS.json` define and store metrics. `VALIDATION.json` and `ARTIFACT_SHA256.json` provide final machine checks and hashes.
