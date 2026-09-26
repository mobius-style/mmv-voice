# Readable draft mode — contract (opt-in since v0.2.8)

Readable draft mode is **off by default**. The default local engine remains
the punctuation-only formatter with the lexical/numeric preservation check.
Readable mode is selected per job with the checkbox *Readable draft instead of
punctuation only* in "Optional steps" (`MMV_FORMAT_MODE=readable` only
pre-selects it). It is a draft generator, not a verbatim transcript and not a
semantic-fidelity certificate. The original recognition text is kept alongside
the candidate and a diff in the Review tab.

## 12B editing profile (2026-09-27)

The 12B path uses `profiles/readable_prompts_12b.json`. Japanese and Mandarin
instructions now request local edits and preserve content-word order, alternatives
and self-corrections. English keeps the published E3 wording: the proposed
replacement reduced punctuation quality in the comparison and was not adopted. The 26B prompt stays
in `profiles/readable_prompts.json`; model weights are unchanged.

Uncertainty and conditional expressions now have conservative source-retention
checks: a marker does not make a change from “might” to “will” acceptable.
Number order is checked as well as the values; surviving content tokens must
keep their relative order (English words, Japanese kanji/ASCII, Chinese
non-function characters). These checks still do not prove
semantic fidelity or detect all changes in scope, roles or relationships.
English personal pronouns (I, you, he, she, it, we, they) count as content
words, so a pronoun that appears in the draft but not in the source retains
the chunk; a modal such as "may" is matched case-insensitively and can
collide with the month name. Any language other than Japanese and Mandarin
is processed with the English prompt and the English guard rules.

## Kept from the default path

- Local-only Ollama endpoint (loopback check) and model tag + digest checks
  for `gemma4:12b-it-qat` and `gemma4:26b-a4b-it-qat`.
- Explicit task boundary: transcript content is never treated as instructions.
- Original / candidate / diff / reason, the actual profile path and hash, and
  the count of diagnostic rules in force are recorded per chunk.
- Source fallback on model absence, transport error, empty response, likely
  output truncation or an unexpected known MMV preamble.
- Exact source reconstruction across chunks; optional speaker / fidelity /
  minutes tools unchanged.

## Removed on the readable path

- MMV question-route classification and injected answer instructions.
- Post-validator rewrites and re-anchor scaffolds.
- The exact lexical-match acceptance (it would reject the rewrites this mode
  exists for). **Therefore the word-and-number guarantee does not apply.**
- No second-model judging and no quality-driven retries are added.

One generation per chunk (plus one retry on a transport error or an empty response); then deterministic review
signals: changed numeral expressions, and changes (as multisets) in a short
multilingual negation / uncertainty lexicon. The lexicon was narrowed after the
v2 measurement — bare `不`, `ない`, `場合`, `可能` flagged almost every ordinary
edit — so rule-triggered chunk markers are rarer in the shipped build than in
the measured one; the context window of the shipped profiles is 8192 (measured
with 4096, which also capped the optional minutes step). These are *warnings*, not proof of meaning
change: legitimate rewriting can trigger them and a wrong person's name can
escape them. No warning never means verified. All non-empty readable outputs
require human review; the status line, the Review tab and the digest say so.

## Bounded-edit guard (v0.2.10)

After the model answers, a deterministic check compares the draft with the
source chunk and keeps the source (status `source_retained`, reason
`readable_guard: …`, the draft and a diff still shown in Review) when any of
these holds:

- the ordered sequence of numerals differs (`numerals_changed`) — an explicit
  self-correction that keeps both values passes, one that drops the first
  value does not; kanji numerals and number words are not recognised;
- the number of negation expressions differs (`negation_count_changed`) — a
  dropped "not" or an added `ません` is one token and would otherwise pass;
- surviving content tokens change relative order (`content_order_changed`);
- uncertainty-expression counts differ (`uncertainty_changed`), or the
  per-expression counts in a small language-specific condition/modality lexicon
  differ (`condition_or_modality_changed`); legitimate paraphrases may be retained;
- more than min(15, max(1, 3 per 100 source tokens)) content tokens are
  missing from the draft, after removing an unambiguous filler list (um, uh,
  okay, well, `えー`, `あのー`, `嗯` … and the phrases "you know" / "I mean" /
  "sort of" / "kind of"); words that can carry content (right, like, so,
  `その`, `あの`, `这个`) are not treated as fillers (`omission_over_limit`);
- the draft contains content the source does not: English words outside a
  small function-word list, Japanese kanji or kana runs that cannot be built
  from particles / auxiliaries / formal nouns and kana runs already present
  in the source (so `すべて` counts, `ています` or a source name wrapped in
  new particles does not), Mandarin characters outside a small function-character list
  (`content_added`). Japanese negation is counted on `ない` / `なかった` /
  `ません` / `ではなく`; Mandarin on `不 没 无 非 未`; English on not / never /
  no / without and contracted forms.

This bounds what a readable draft can do; it does not make it correct. It
cannot see a meaning change made with the same tokens, and it will retain
some legitimate rewrites (a singular/plural change, a paraphrase that
introduces a new kanji). The thresholds were set on the 2026-09-26 held-out
outputs (read speech never lost more than one token per chunk; meeting drafts
that lost 4–18 tokens per 100 were the cases to catch) and are to be
confirmed on new recordings.

## Markers

The prompts (English, Japanese, Mandarin; `profiles/readable_prompts.json`)
put "no unsupported guesses" before fluency. Unclear spans stay in the source
wording followed by `（※要確認）` — the marker is deliberately identical in all
three languages. Model-placed markers refer to the preceding phrase.
Rule-triggered warnings append the same marker at the end of the affected
chunk and record `annotation_scope=chunk`; they do not claim to locate the
exact error. Even text without a marker is unverified. The raw model output is
kept as `candidate` / `model_candidate`; `text` is the delivered, annotated
version.

## Validation so far

- 2026-09-27: 12B-only, two rounds / 72 fresh FLEURS clips, 540 outputs.
  Japanese and Mandarin prompt changes adopted by per-language rules; English
  prompt unchanged. All three use the strengthened guard. This is an exploratory
  selection panel, not independent proof of general quality.
  See `eval/mmv_12b_polish_20260927.md`.

- 2026-09-26, held-out outputs used to set the thresholds: meeting chunks
  kept as source 14/18 (12B) and 15/18 (26B); read speech 3/36 English.
- 2026-09-26, second meeting (AMI ES2008a, native English) and 36 new clips,
  shipped code: meeting after-guard content loss 0.21 / 0.09 per 100,
  invented 0, error rate within 0.1 pt of Whisper; read speech retention
  3/36 (12B English), 3 / 9→6 / 3 of 36 (26B English / Japanese / Mandarin)
  — above the declared 2/36 bound for 26B; thresholds unchanged, one Japanese
  false-positive class fixed. Report: `eval/mmv_guard_e3_20260926.md`.

## Chunking and models

Sentence endings are preferred when splitting (≤ 1,000 characters); a very
long sentence falls back to the token-safe splitter and can still lose
context. Cross-chunk meaning and names are not resolved. The default model is
the 12B QAT build; `MMV_READABLE_MODEL=gemma4:26b-a4b-it-qat` selects the
digest-pinned 26B-A4B (a mixture-of-experts model, not a dense 26B). A missing
tag or a different digest is a visible error, never a silent substitution.
The exploratory 26B comparison does not justify changing the default.

## Rollback

Untick the checkbox (or launch without `MMV_FORMAT_MODE`). The default path and
its validator are untouched by this mode; the cloud engine is a separate,
explicitly confirmed path and does not acquire this mode's behaviour. The
published quality measurements for the default engine do not validate this
mode; its own measurement is `eval/mmv_readable_v2_20260926.md`.
