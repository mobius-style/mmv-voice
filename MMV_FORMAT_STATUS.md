# MMV 12B QAT Japanese Formatting v2 — 2026-09-25

**This round's target, "a Japanese candidate acceptance rate above 70%", was met. Reflected in the local trial build; not released.** On the post-hoc punctuation-position accuracy (below) it ties the old v1 (F1 0.857 / 0.857), so the rise in acceptance rate does not mean the punctuation became more accurate. On 12 new clips × 3 repetitions, 33/36 outputs (91.7%) were accepted. Of these, 30/36 (83.3%) were actually formatted, 3/36 (8.3%) needed no change, and 3/36 (8.3%) were rejected with the source retained. The previous method, on the same clips with the same model, scored 30/36 (83.3%).

## Changes and trial-and-error

The only change is the Japanese prompt. Model weights, the 12B QAT tag/digest, MMV's 3 settings, temperature and output cap, the lexical/numeric preservation check, and the splitting and source-retention handling are unchanged. The English prompt is also identical. Existing uncommitted work was preserved; no change to the canonical MMV profile, no training, and no external release.

The previous 16 Japanese clips (including the previous holdout) were explicitly moved to the development set this time. Separately, 8 examples containing typos, place names, personal names, numbers, fillers and in-speech instructions were prepared.

| Development candidate | Candidate acceptance on 16 Japanese clips | Formatting of 8 unpunctuated examples |
|---|---:|---:|
| J1: transcribe verbatim and insert punctuation only; concrete examples of preserving typos; no added brackets; output body text only | 16/16 | 8/8 |
| J2: concise instruction of insertion operations only | 12/16 | 7/8 |

J2 had failures where the body text was returned wrapped in JSON, and was not adopted. J1 was selected, and the prompt, evaluation conditions and additional examples were hash-frozen before the transcripts and reference texts of the new clips were viewed. No re-tuning based on the new evaluation results was done. Since the target was reached with these 2 candidates, further trials were stopped.

## Results on new clips

The next 12 clips in Japanese test.tsv order from Google FLEURS at pinned revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, excluding duplicates against all past Japanese/English text IDs and normalized reference texts. 152.46 seconds in total. Transcribed once each with Whisper large-v3-turbo, GPU1, language=ja, temperature 0, and saved. Old v1 and new J1 were each run 3 times on the same input, alternating the order. There are 12 independent clips, not 36.

| Metric | Previous method v1 | Improved method v2/J1 |
|---|---:|---:|
| Candidate acceptance rate | 83.3% (30/36) | 91.7% (33/36) |
| Actually formatted outputs | 24 | 30 |
| Accepted unchanged | 6 | 3 |
| Source retained (unformatted) | 6 | 3 |
| Processing time, median | 0.801 s | 0.816 s |
| Generated-candidate CER | 6.03% | 6.34% |
| Final-output CER | 6.34% | 6.34% |

The source CER is 6.34%. CER is the character error rate excluding punctuation and whitespace. The final-output CER equals the source because of lexical preservation and source retention on rejection; it does not mean transcription errors decreased. Generated candidates and final outputs were tallied separately, and source retention is not counted among acceptances.

The paired difference on identical clips is **+8.33 points**. The 95% interval from a 10,000-run clip-level bootstrap (seed 20260925) is [0.00, +25.00] points. Of the 12 independent clips, 11 were accepted in all 3 runs; the Wilson 95% interval for that proportion is 64.6%–98.5%. **An observed value above 70% was achieved this time, but the sample size cannot guarantee above 70% in the population.** This is an exploratory comparison; no significance test of superiority was performed. The 3 repetitions are repeats at temperature 0, not 3 independent seeds.

The previous 62.5% was a result on a different set of 8 clips. The 91.7% here is not subtracted from it directly as an improvement amount. On the same new clips, old v1 also reached 83.3%, so there is sample-dependent variation. Speed, likewise, is compared only as values from the same current environment and inputs.

## Punctuation-position accuracy (added post hoc 2026-09-25, exploratory)

The acceptance rate is "the rate that passed the preservation check"; whether punctuation sits in the correct position had not been measured. Using FLEURS's punctuated source text as the reference, matches were taken at boundary positions on the punctuation-stripped string, and precision, recall and F1 were computed over the 36 outputs combined (`punct_position.py`, `PUNCT_POSITION.json`; saved outputs only, no regeneration). This is a post-hoc metric not in PLAN.md, added after the results were seen. Strings containing ASR typos were mapped to reference positions by diff alignment.

Instrument calibration: reference vs. reference gives F1 1.000; no punctuation 0.000; only a trailing kuten (。) 0.522; 3 random tōten (、) plus a kuten 0.375.

| Final output (incl. source retained) | Previous method v1 | Improved method v2/J1 |
|---|---:|---:|
| Punctuation F1 | 0.857 | 0.857 |
| Precision / recall | 0.931 / 0.794 | 0.833 / 0.882 |
| Kuten 。 F1 | 0.923 | 0.963 |
| Tōten 、 F1 | 0.811 | 0.791 |
| Tōten output count (reference 60) | 51 | 69 |
| Unformatted source (for reference) | F1 0.409 | same |

The clip-level paired difference is +0.001, bootstrap 95% interval [−0.089, +0.088]. **The acceptance rate rose by +8.3 points, but punctuation-position accuracy did not change.** In the breakdown, J1 omits fewer kuten but inserts more tōten than the reference (e.g. `自然環境にある時に、最も見栄えが` ("when in a natural environment, [it] looks best"), `砂浜で、安全に泳ぐ` ("swim safely, on the sandy beach")). In one case (ja_jp_1745) where v1 returned the clip "unchanged" and J1 added a tōten and was counted as "formatted", position accuracy fell from v1's 1.000 to J1's 0.667. Part of the 24→30 increase in "actually formatted outputs" is these extra tōten.

FLEURS's tōten placement is only one editorial convention, and the tōten-accuracy difference is weaker evidence than the kuten one. However, if punctuation-position accuracy is used as the adoption criterion, v2 is not superior to v1; it is a different trade-off.

## Check against the "change nothing" loophole

On the new 8 unpunctuated examples, punctuation was added at the specified clause boundaries while preserving words and numbers in all 8. The check, which is not passed by merely appending a kuten at the end, was calibrated on failing cases (the source as-is, trailing kuten only) and a passing case (internal kuten added) before being run. A plain copy or a fallback does not count as success.

Examples:
- `報告は以上です 次は質疑です` → `報告は以上です。次は質疑です。` ("That concludes the report. Next is Q&A.")
- `えー 申請は終わりました あの 結果を待ちます` → `えー、申請は終わりました。あの、結果を待ちます。` ("Uh, the application is done. Um, we'll wait for the result.")
- `量は2.5mgです 変更はしません` → `量は2.5mgです。変更はしません。` ("The dose is 2.5mg. No change will be made.")

## Remaining failures

In 1 of the 12 new clips, the source nakaguro (`・`) was replaced with a tōten (`、`). The check that preserves existing symbols rejected it in all 3 runs, and the source was left as is. The check was not loosened this time, and these 3 outputs were counted as failures. The semantic appropriateness of the punctuation itself and the correctness of ASR misconversions are not guaranteed.

## App integration verification

- The Japanese prompt matches the frozen J1. Verified that the AST of every function and class is identical before and after the change, and that the English prompt is identical. No loosening of the preservation check and no post-hoc editing of candidates.
- The existing 17 regression tests pass. They include an HTTP fixture through the real harness, numeric/lexical/English-word boundaries, model mismatch, source retention, splitting, and digest saving.
- The previous 8 English clips were regression-checked: 8/8 candidates accepted (6 formatted, 2 unchanged). This is not a new English quality evaluation.
- The real model was called through the GUI's real post-processing path; output, source retention and display were confirmed on 4 cases in total: Japanese formatted/unchanged/rejected plus English.
- Speaker attribution, additional LLM verification and minutes remain off by default. Normally 1 generation request per chunk; the existing retry on communication or similar errors is at most 1.

## Evaluation scope and gates

An [anecdotal, exploratory, unreviewed] local engineering trial. G1: PLAN/FREEZE timestamps and hashes, no external preregistration. G2: limited to exploratory. G3: paired difference and clip-level CI, small sample, no test/multiple-comparison claims. G4: preservation check/CER and the internal punctuation check are machine-calibrated; inter-rater agreement on subjective semantic quality is unmeasured. G5: training contamination from public clips is unresolved; general model-performance claims are withheld. G6: rejected candidates and new failure cases are saved; no novelty is claimed.

The pass applies to the observed above-70% condition the user specified this time and to the additional punctuation-usefulness/English-regression conditions. The 24 September HOLD from the previous round is not retroactively rewritten. Generalization to noise, multiple speakers and long meetings, a guaranteed 70% population lower bound, proof of semantic fidelity, and formal release are not achieved / out of scope.

## Reproduction record

- Work set: `/home/happy/.codex/work/mmv_formatter_ja_20260925`
- `PLAN.md`, `FREEZE.json`, `prompts.py`, `DEV_SUMMARY.json`, `RESULTS.json`, `punct_position.py`, `PUNCT_POSITION.json` (added post hoc)
- `dev/`, `holdout/samples.json` (clip SHA-256), `holdout/asr/`, `eval/`, `english/`
- `unit.log`, `integration_verification.json`, `gui_real_path.json`, `gui_real_path.png`
- Pre-change files: `voice_mmv.py.before`, `whisper_gui.py.before`, `README.md.before`, `MMV_FORMAT_STATUS.md.before`

The model is `gemma4:12b-it-qat`, digest `38044be4f923e5a55264ed7df4eaac2676651a905f735197c504045140c02bd3`. 12B QAT/Q4_0, temperature 0, num_ctx 8192, max_tokens 1024, think=false. RTX 5070 Ti; Ollama on GPU0, Whisper on GPU1. The canonical MMV settings were not changed; only the dedicated 11435 server was stopped after the experiment. The existing service on the usual 11434 was kept.

Previous record: [2026-09-24 trial](eval/mmv_format_12b_qat_20260924.md). The original experiment set is also kept as is.
