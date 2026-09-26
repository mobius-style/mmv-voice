# Readable draft mode v2 — four-arm exploratory comparison (2026-09-26)

This mode is opt-in in the released application; the default remains the punctuation-only mode with the lexical/numeric preservation check. Its outputs are drafts that require human review.

2026-09-26. Exploratory, unreviewed, single evaluator. Conclusion: there are concrete examples where the direction improved toward retaining the source and flagging spans for verification. It is not, however, a complete elimination of guessing, omission, or misses. Candidate for a review-assisted trial; automatic (unreviewed) adoption: HOLD.

## Implementation

1. Splitting with an upper bound of 1,000 characters, preferring sentence ends. The source is fully reconstructible. A single sentence that is too long falls back to the previous token-protected splitting.
2. Editing instructions for English, Japanese and Chinese that prioritise retention of evidence over fluency. Person names, place names and technical terms are not replaced from external knowledge or by phonetic approximation. Agent, causation, negation, conditions and uncertainty are preserved.
3. Unclear words or phrases are left as in the source, immediately followed by `（※要確認）`. This marker means "please verify" and is deliberately identical in all three languages. When the machine check detects a change in numbers or similar, an annotation/marker is also appended at the end of the affected chunk. A warning whose position cannot be localised is recorded as annotation_scope=chunk. The absence of an annotation/marker does not mean the text was verified.
4. Explicit selection of 12B / 26B-A4B and digest verification for each model were implemented. Default is 12B. The source, the model output, the actual annotated output, and the diff are retained. No changes to the shared MMV core.

## Comparison conditions

current (previous readable-cleanup build) / v2, x 12B QAT / 26B-A4B QAT, x 38 inputs x 3 repeats = 456 outputs. 114 outputs per arm. 14 English, 12 Japanese, 12 Chinese. Breakdown: 26 inputs from real audio (FLEURS 24 + 2 excerpts from the same AMI meeting) and 12 synthetic inputs. Whisper's saved results were held fixed; speech recognition was not re-run this time.

Identical settings: temperature 0, context 4096, max output 1024, no thinking output. One generation per chunk, retries only for transport errors. Order alternated. A dedicated inference endpoint on GPU0 was used; GPU1 and the existing production endpoint were left unchanged. No model reference material was supplied as input. 26B_current is an experimental arm in which only the model name of the current algorithm was swapped.

## Measurement overview

| Arm | Known unsupported substitutions (guesses) detected (see note) | Outputs with an annotation/marker | Median processing time |
|---|---:|---:|---:|
| 12B_current | 9/15 | 0/114 | 0.90 s |
| 12B_v2 | 0/15 | 41/114 | 0.90 s |
| 26B_current | 9/15 | 0/114 | 0.69 s |
| 26B_v2 | 0/15 | 51/114 | 0.68 s |

Note: this is not an overall correctness rate of the results. It is a limited regression diagnostic over 5 post-hoc defined known failure items (a guessed change of a city name, a change to a different person's name, an interpretation as "low energy", a substitution with `庫仑` (Coulomb), and cooches -> coaches/couches) x 3 repeats. The detection strings were calibrated on known-good/known-bad examples. Undetected errors and omissions are not included in these counts. The 3 repeats are not 15 independent cases; there were originally 5 inputs.

Times cover readable editing only, after model load. They exclude speech-recognition time and are descriptive values that also include differences due to input length, output length and annotations. They are not statistical proof of quality or of a general speed advantage.

## Specific improvements and remaining problems

- Japanese city name: 26B current (previous readable-cleanup build) replaced `ダルルバリア` (a city name as transcribed) with a different name and also changed the agent who established the trading post. v2 retains the source as `ダルルバリア（※要確認）`. 12B v2 does not substitute, but does not annotate this span either.
- Chinese person name: the change to `黄循财` (a different real person's name) seen in 26B current no longer occurs; both v2 arms retain `黄庚承（※要確認）` (the name as transcribed). This is not an automatic correction to the right name.
- English meeting: both current arms have examples that guess cooches as couches/coaches; both v2 arms retain `cooches（※要確認）`. GP is also retained and annotated. The "expensive" completion seen previously under a different condition did not appear in current this time either, so it is not counted as a v2 improvement.
- English sentence cuts: against current's "international. Market..." / "market. Markets...", v2 keeps "international market" within the same sentence. The split positions are kept in the measurement archive (not published).
- Remaining omission: Chinese 26B v2 deleted the unclear span `起低能量` (an unclear phrase) and annotated the preceding word instead. Even with an annotation, this violates the source-retained contract and is not treated as resolved.
- Remaining meaning changes: in 12B v2 there is still an example at the start of the meeting where a statement is turned into a question. In 26B v2 there is also an example where "must" is added to "user-friendly". It cannot be said that the meaning of the source was fully preserved.
- Misses: the English person name Shandra Shankar Solansky and the Japanese misrecognition `海外` -> `海岸` (overseas -> coast) remain unannotated.
- Over-warning: there are examples that annotate a correct EMO, an explicitly explained work title, and a correct date correction. Warnings from rule-based changes in numeral formatting are also included.
- Cost of not correcting: 26B v2 left `木用日` (a misrecognized word) and `基金为止` (a misrecognized phrase) as source plus annotation instead of correcting them, and in one example did not correct `たたって` -> `たどって` (a misrecognized verb form) either. This is the trade-off against suppressing guesses; prose completeness did not improve uniformly.

## Quality verdict

For both models, the confirmed specific unsupported substitutions (guesses) decreased. 26B v2 stands out for annotating ambiguous words, while also showing omissions and over-annotation. 12B v2 still has misses and meaning changes. A blanket switch to 26B, 100% meaning preservation, no need for verification, and practical time savings cannot be claimed.

If adopted, it should be as a review-assisted trial with access to the source retained. This is known data that records the failures seen before the change; the next quality check needs new, real meeting recordings, human correction time, and a check for misses.

## Verification and research limitations

32 unit tests; machine checks of the existence of all 456 outputs, denominators, source reconstruction, unverified-status display, and frozen hashes. Plan and instructions were frozen before generation; the annotation requirement was also reflected before the first generation. All 38 first-repeat input sets with their four arm outputs were reviewed with model names masked, but the version is guessable from the annotations. Single evaluator with no kappa or similar measured, so no pass rate for semantic quality is reported. The full review, all outputs, and all first-repeat examples are kept in the measurement archive (not published).

G1: frozen, but exploratory because the regression data is known. G2: case-level exploratory, unreviewed. G3: descriptive statistics, no test or power analysis, no superiority inference. G4: inter-rater reliability not measured. G5: FLEURS/AMI training contamination unresolved. G6: omissions, transformed assertions, and missed annotations are the counterexamples. Related-work comparison inherits the ASR error correction literature from the previous report; no novelty is claimed.

The changes are to the generation instructions, splitting, and annotation, not additional training of model weights. The annotation is an aid that makes doubt visible; it is not proof that MMV's core value of "no guessing without evidence" has been achieved.

In the integration copy, only the model name in the progress display was corrected, and 33 tests pass. The evaluated candidate copy and the frozen hashes are kept in the measurement archive (not published). The generation processing is identical. Across repeats, an extra annotation appeared in 1 Chinese example for 12B, so annotations also fluctuate. 26B v2 matched exactly across 3 repeats for all 38 inputs, but since this includes consistent errors it is not a quality guarantee.
