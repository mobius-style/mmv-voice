# MMV 12B QAT formatting custom — measured results (2026-09-24)

**Conclusion: prototype implementation and trial complete. The formal adoption decision is HOLD.** English met this round's minimum condition, but the Japanese candidate acceptance rate of 62.5% did not reach the pre-set criterion of 75%. The threshold is not changed after the fact, and promotion to normal use including Japanese is deferred. The current local GUI is an explicitly labeled trial build. No release, no commit, no change to the existing MMV release.

## What was changed

No additional training. The model is pinned to `gemma4:12b-it-qat`; a punctuation-and-line-break-only instruction, a source-preservation check, and saving of candidate/source/rejection reason were added. Option B, which keeps MMV's existing 3 settings, was selected. The C1 prompt is not used. Speaker attribution, additional LLM verification and minutes are off by default. No quality regeneration; normally 1 request per chunk. The existing harness's error retry of at most 1 remains.

## Tuning process

The development set is the already-used 16 FLEURS Japanese/English clips and 8 unpunctuated examples. A = conventional instruction + MMV; B = dedicated instruction + existing MMV; C = dedicated instruction + the 3 MMV settings aimed at general questions disabled. B/C share the same preservation check.

| Tuning | B candidates accepted /24 | B punctuation examples formatted /8 | C candidates accepted /24 | C punctuation examples formatted /8 |
|---|---:|---:|---:|---:|
| Initial | 20 | 5 | 20 | 5 |
| Tuning 1: added explanation of lowercase preservation | 11 | 4 | 13 | 5 |
| Tuning 2: concise instruction on semicolons | 21 | 7 | 21 | 7 |

Tuning 1 increased cases that lowercased even the start of the input and was not adopted. Tuning 2 gave both options the same acceptance count and CER. Following the plan's ranking rule, B was selected on development medians of B 1.861 s vs. C 1.877 s. This small difference is not itself taken as evidence of a speed advantage. The prompt has not been changed since.

## Verification on separate clips

From Google FLEURS at pinned revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, the next 8 items per language were taken in test.tsv order, excluding all previous text IDs and duplicate reference texts. 16 clips in total, 201.96 seconds. Each transcribed once with Whisper large-v3-turbo, CUDA, language specified, temperature=0, and the same input compared. The conventional MMV also used the same 12B QAT this time. 3 runs per clip, 48 outputs per method. The number of independent samples is 8 per language, not 24.

| Metric | Japanese | English |
|---|---:|---:|
| Whisper source CER | 5.52% | 5.01% |
| Conventional MMV 12B QAT CER | 13.50% | 20.82% |
| New method: generated-candidate CER before check | 4.61% | 5.01% |
| New method: final-output CER | 5.52% | 5.01% |
| New method: candidate acceptance rate | 62.5% | 100.0% |
| New method: formatted / unchanged / source retained | 9 / 6 / 9 | 21 / 3 / 0 |
| Conventional MMV median per request | 2.82 s | 2.15 s |
| New method median per request | 2.66 s | 2.03 s |

CER is the character error rate excluding punctuation and whitespace. The new method's final CER equals the source because of the check that forbids content changes and source retention. **It is neither the result of improved ASR accuracy nor of counting source retention as formatting success.** Punctuation appropriateness and semantic fidelity cannot be measured by this metric. The conventional MMV figures have the original app's confirmation-sentence removal applied. Raw-output CER without removal is 13.50% for Japanese and 60.25% for English.

Paired difference averaging 3 runs per clip (new-method final − conventional, 10,000-run bootstrap, seed 20260924):
- Japanese: -7.98 points, 95% CI [-13.12, -3.42].
- English: -15.81 points, 95% CI [-37.92, +0.37].

The CIs are descriptive. Power is low at n=8 per language, and the methods were run in a fixed order, so no causal comparison of speed is possible. No superiority claim by hypothesis test or multiple comparison is made. These are 3 repetitions at temperature 0, not a 3-independent-seed trial.

Of the 4 unused punctuation examples, 3 were actually formatted and 1 had the source retained (a spelling change `um`→`Um`). The minimum condition of 3/4 passed.

## Failure cases and interpretation

For Japanese, the source was retained every time on 3 of the 8 clips:

- Added corner brackets `「」` around a Latin name that were not in the source. Rejected as an unpermitted symbol addition.
- Lexical correction `裏名` → `裏面` ("reverse side").
- Lexical corrections `使徒` ("apostle") → `首都` ("capital") and `チンウン` → `チシナウ` ("Chișinău").

The corrections may well be right; indeed, the pre-check candidates' Japanese CER is lower than the source's. But this round's goal is formatting that keeps the source wording, and automatic corrections are not adopted without confirming the meaning of the clip. Such candidates can be inspected in the report. The ability to format Japanese without modification is not achieved, and the criterion is not loosened to count it as success. A next trial could examine, on new evaluation clips, approaches such as proposing only permitted punctuation edits rather than generating the full text.

## Implementation verification

17 regression tests pass. They include a local HTTP fixture through the real MMV harness, rejection of a different model, communication exceptions, retention on disconnect/empty reply/lexical change, numeric and English-word boundaries, an overlong single token, and digest saving. The preservation check was confirmed on 500 random Japanese inputs to reject deletions and substitutions and to permit punctuation additions. The CER implementation was cross-checked against an independent shortest-path computation on 225 pairs and against known-good/bad cases. This is not a universal guarantee beyond the test coverage.

A GUI virtual-display test confirmed the local MMV path, add-on features off, and source retention plus unformatted display on candidate rejection. A separate verification passing 4 real transcripts of other clips from GUI post-processing through to the real model is also saved. At the GUI boundary the original leading/trailing whitespace is also preserved. Chunk splitting and model connection confirmation are integration-side additions, checked separately from the short clips of the comparison trial.

## Limitations and research gates

An [anecdotal, exploratory, unreviewed] local engineering trial. G1: plan and candidates hash-frozen, but no external registration; the app post-processing correction for the baseline method is stated in DEVIATIONS.md. G2: limited to exploratory. G3: paired difference/CI, low power at n8, no tests. G4: machine metrics calibrated; inter-rater agreement on subjective formatting quality is unmeasured. G5: training contamination from public FLEURS is unresolved; a general model-performance advantage is withheld. G6: failure cases and mutated inputs saved; no novelty claimed. Adoption as independent research evidence is on hold.

This is a small sample of read speech; generalization to meetings, noise, long clips and multiple speakers is unevaluated. Punctuation and whitespace themselves can change meaning. The candidate preservation check does not detect ASR errors. Meaning preservation under permitted-symbol changes has not been proven.

## Reproduction and rollback

Evaluation model digest: `38044be4f923e5a55264ed7df4eaac2676651a905f735197c504045140c02bd3`. 11.9B/Q4_0, QAT tag, temperature 0, num_ctx 8192, max_tokens 1024, think=false. On the dual RTX 5070 Ti machine, Ollama on GPU0 and Whisper on GPU1. No inference service of other existing sessions was stopped.

Record set: `/home/happy/.codex/work/mmv_formatter_12bqat_20260924`. PLAN/FREEZE/RESULTS/DEV_SUMMARY/DEVIATIONS, every input, candidate and timing, clip SHA-256, and GUI real-path results are saved. The baseline code is the preceding trial's `original_whisper_gui.py` (original commit bd7fd83). The pre-change GUI and README are kept as `.before` files in this trial folder. Reverting to the original public version also involves the preceding C1 changes, so do not discard the working tree wholesale; compare and revert only the files needed.

**Completed scope**: tuning, evaluation on separate clips, local trial implementation and regression verification. **Not achieved**: Japanese candidate acceptance rate, formal adoption conditions for both Japanese and English, and release.
