# mmv-voice fidelity and speaker-attribution scoring protocol (measurement 12)

**Purpose:** quantify mmv-voice's (a) transcription fidelity and (b) text speaker-attribution
accuracy against human-made ground-truth labels. No judge model; deterministic scoring.

## What we ask of the owner (only this)

1. Pick one target recording (e.g. `meeting.m4a`).
2. Listen to **about 5 contiguous minutes** of the recording and write the ground truth
   into `eval/reference_<name>.csv`. 1 row = 1 utterance segment:

```csv
start_sec,end_sec,speaker,text
12.5,18.2,A,ここは正確に聞こえたとおりの文字列を書く
18.9,24.0,B,相手の発話も同様に
```

(The example `text` values are placeholder Japanese transcript strings: "write here exactly the string as heard" / "the other party's utterance likewise".)

- `speaker` may be a symbol such as A/B/C… (no names needed).
- `text` is verbatim as heard (fillers such as "ee/uh" are optional, but keep the policy consistent).
- Guide: 5 minutes ≈ 40–60 rows. Takes 20–30 minutes.

## Automatic side (done by the script)

`python3 eval/score_fidelity.py <audio> eval/reference_<name>.csv`

1. Process the same span with the mmv-voice pipeline (large-v3-turbo + MMV formatting).
2. **Fidelity:** compute the character error rate (CER) / word error rate (WER-equivalent;
   character-based for Japanese) against the ground-truth text after segment alignment.
   - Score both the raw transcript and the MMV-formatted output → measure separately
     whether formatting breaks fidelity (Δ fidelity). This is the verification of
     mmv-voice's core claim.
3. **Speaker attribution:** agreement rate (accuracy + confusion matrix) between each
   ground-truth segment's speaker label and that of the output segment matched to it by
   time overlap.
4. Output: `eval/results_<name>_<ts>.json` + a Markdown summary.

## How to read pass/fail (preregistered)

- Fidelity: formatted CER within raw-transcript CER + 2pt → "formatting preserves fidelity".
- Attribution: accuracy ≥ 0.85 is practical level; < 0.7 needs rework.
- With n=1 recording, directional only. If it reproduces on a 2nd recording (different speaker
  configuration), fix it as a finding.
