# UI / UX update — v0.2.5, 2026-09-26

Base: v0.2.4. Released as v0.2.5 after an independent adversarial code review (privacy, consent, concurrency); the v0.3/v0.3b formatter experiments remain on HOLD and are not part of this release.

- A light desktop workspace puts input controls, progress, original text and result together. Extra options use a separate dialog; transcript, review and notes remain available.
- Added UTF-8 text export, Ctrl+O / Ctrl+S, elapsed time and explicit local/cloud state.
- Worker callbacks enter a bounded main-thread queue. Settings are captured before work starts. One worker owns Whisper release and subsequent formatting; stop preserves completed segments and cannot start a competing formatting task.
- GPU availability uses actual free memory. Model calls remain blocking within their worker; stop takes effect at the next completed transcription segment.
- Static landing page has responsive layout, navigation, desktop preview and install-command copy. It remains a guide, not a browser transcription service.

## Verification

19 unit tests passed (10 desktop lifecycle/layout tests, 9 existing formatter tests).
A real 5.88-second English FLEURS clip ran through Whisper large-v3-turbo on CPU, the real adapter with a local HTTP formatter fixture, and UTF-8 export. Runtime: 26.83 s; 997 UI timer callbacks; largest observed timer gap 108 ms; no UI callback errors. This is one responsiveness smoke test, not a speed or model-quality benchmark. No GPU was used and no inference server was restarted.

Browser checks at 1440 × 900 and 390 × 844 found no horizontal page overflow; all three page images loaded; no console errors. The copy button entered its success state; browser clipboard content could not be confirmed through the tool.

## Integration with Claude

This build does not modify voice_mmv.py, model prompts or profiles. The v0.3b experiment (scaffold strip, sentence-aware chunking, Whisper `condition_on_previous_text=False`) was evaluated separately and put on HOLD: it raised WER on the new held-out meeting by 41.75 points, so none of it is included here.
