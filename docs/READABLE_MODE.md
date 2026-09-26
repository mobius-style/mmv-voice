# Readable draft mode — contract (opt-in since v0.2.8)

Readable draft mode is **off by default**. The default local engine remains
the punctuation-only formatter with the lexical/numeric preservation check.
Readable mode is selected per job with the checkbox *Readable draft instead of
punctuation only* in "Optional steps" (`MMV_FORMAT_MODE=readable` only
pre-selects it). It is a draft generator, not a verbatim transcript and not a
semantic-fidelity certificate. The original recognition text is kept alongside
the candidate and a diff in the Review tab.

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
