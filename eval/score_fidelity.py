#!/usr/bin/env python3
"""mmv-voice fidelity and speaker-attribution scorer (measurement 12) -- no judge model.

Inputs:
  --wisper-json  segment list output by the mmv-voice pipeline
                 [{"start": s, "end": e, "speaker": "A", "text": "...",
                   "text_formatted": "..." (optional)}]
  --reference    human ground-truth CSV (start_sec,end_sec,speaker,text)

Output: CER for raw and formatted text respectively, speaker-attribution accuracy
plus confusion matrix (JSON + stdout). Segments are matched by maximum time overlap.
Japanese is scored with character-based CER.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(ch for ch in s if not ch.isspace()
                   and ch not in "、。,.!?！?「」『』()（）…・-—")


def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0 if not h else 1.0
    sm = difflib.SequenceMatcher(a=r, b=h, autojunk=False)
    match = sum(b.size for b in sm.get_matching_blocks())
    edits = max(len(r), len(h)) - match
    return edits / len(r)


def overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def align(refs: list[dict], hyps: list[dict]) -> list[tuple[dict, dict | None]]:
    out = []
    for r in refs:
        best, best_ov = None, 0.0
        for h in hyps:
            ov = overlap(r["start"], r["end"], h["start"], h["end"])
            if ov > best_ov:
                best, best_ov = h, ov
        out.append((r, best))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wisper-json", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    hyps = json.loads(Path(args.wisper_json).read_text(encoding="utf-8"))
    refs = []
    with open(args.reference, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            refs.append({"start": float(row["start_sec"]),
                         "end": float(row["end_sec"]),
                         "speaker": row["speaker"].strip(),
                         "text": row["text"]})

    pairs = align(refs, hyps)
    raw_cers, fmt_cers = [], []
    spk_total, spk_hit = 0, 0
    confusion: dict[str, dict[str, int]] = {}
    # Speaker symbols are mapped by greedy most-frequent matching (absorbs label
    # differences such as A <-> SPEAKER_00)
    from collections import Counter, defaultdict
    votes: dict[str, Counter] = defaultdict(Counter)
    for r, h in pairs:
        if h and h.get("speaker"):
            votes[r["speaker"]][str(h["speaker"])] += 1
    mapping = {}
    used = set()
    for ref_spk, c in sorted(votes.items(),
                             key=lambda kv: -sum(kv[1].values())):
        for hyp_spk, _ in c.most_common():
            if hyp_spk not in used:
                mapping[ref_spk] = hyp_spk
                used.add(hyp_spk)
                break

    rows = []
    for r, h in pairs:
        if h is None:
            raw_cers.append(1.0)
            fmt_cers.append(1.0)
            rows.append({"ref": r, "matched": False})
            continue
        c_raw = cer(r["text"], h.get("text", ""))
        c_fmt = cer(r["text"], h.get("text_formatted", h.get("text", "")))
        raw_cers.append(c_raw)
        fmt_cers.append(c_fmt)
        if h.get("speaker"):
            spk_total += 1
            hit = mapping.get(r["speaker"]) == str(h["speaker"])
            spk_hit += hit
            confusion.setdefault(r["speaker"], {}).setdefault(
                str(h["speaker"]), 0)
            confusion[r["speaker"]][str(h["speaker"])] += 1
        rows.append({"ref_start": r["start"], "cer_raw": round(c_raw, 3),
                     "cer_formatted": round(c_fmt, 3), "matched": True})

    result = {
        "n_reference_segments": len(refs),
        "cer_raw_mean": round(sum(raw_cers) / len(raw_cers), 4),
        "cer_formatted_mean": round(sum(fmt_cers) / len(fmt_cers), 4),
        "delta_fidelity_pt": round(
            (sum(fmt_cers) - sum(raw_cers)) / len(raw_cers) * 100, 2),
        "speaker_accuracy": round(spk_hit / spk_total, 3) if spk_total else None,
        "speaker_mapping": mapping,
        "confusion": confusion,
        "rows": rows,
    }
    out = args.out or (Path(args.reference).parent /
                       f"results_{datetime.now():%Y%m%dT%H%M%S}.json")
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
