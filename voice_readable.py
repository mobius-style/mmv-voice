"""Task-scoped MMV editing: one generation, source-linked review, no QA routing.

Diagnostics flag some changes; they do NOT certify semantic fidelity.
"""
import copy
import difflib
import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path
from voice_mmv import MMVFormatter, MODEL, numbers, local_endpoint, split_source

PROFILE_PATH = Path(__file__).resolve().parent / 'profiles/mmv_readable_12b_qat.json'
PROMPT_PATH = PROFILE_PATH.with_name('readable_prompts.json')
PROMPTS = json.loads(PROMPT_PATH.read_text(encoding='utf-8'))
# Narrow lexicon (v0.2.8 review): single-character Chinese and bare Japanese adjective
# negations flagged almost every ordinary edit, so the chunk-level warning carried no information.
# Only the COUNT of negation / uncertainty expressions is compared, so an equivalent
# negation form or a reordered clause is not a change, while dropping or adding a
# negation is. Bare adjective endings (e.g. "few", "wasteful") are deliberately not matched.
SIGNALS = {
    'negation_changed': re.compile(r"\b(?:not|never|no|cannot|can't|don't|isn't|haven't|won't|wasn't|didn't)\b"
                                   r"|ません|ではない|じゃない|できない|しない|わからない|未定|不是|没有|不能|不会|不要|不可", re.I),
    'uncertainty_changed': re.compile(r'\b(?:probably|perhaps|maybe|might|could|unless)\b'
                                      r'|たぶん|多分|見込み|かもしれ|大概|可能性|也许|如果|只有', re.I),
}
RULES = ('numeric_expression_changed', *SIGNALS)

# ---- Readable postcondition (v0.2.10): a bounded-edit contract enforced in code ----
# A draft may re-punctuate, fix grammar, drop fillers/repeats and resolve explicit self-corrections.
# It may NOT (a) change the multiset of numerals, (b) drop more than OMIT_MAX_PER100 content tokens per
# 100 source tokens (or more than OMIT_MAX_ABS in short chunks), (c) introduce content the source does not
# contain: English content words outside a small function-word list, Japanese kanji, Mandarin characters
# outside a small function-character list. Violations retain the source chunk with a visible reason.
# Thresholds were set on the 2026-09-26 held-out outputs (read speech: <=1 omitted token per chunk;
# meeting drafts that lost 4-18 tokens per 100 were the failures to catch) and are validated on new data.
OMIT_MAX_PER100 = 3.0
OMIT_MAX_ABS = 1
OMIT_MAX_CAP = 15          # never more than this many content tokens, however long the chunk
# Fillers are removed from the SOURCE before counting omissions. Only unambiguous ones: words that
# can carry content (right, like, so, mean, know; the Japanese and Chinese demonstratives) are deliberately NOT here,
# so dropping them counts as an omission. English filler phrases are removed as phrases.
FILLERS = {
    'en': {'um', 'uh', 'er', 'ah', 'hmm', 'mm', 'mhm', 'okay', 'ok', 'yeah', 'yep', 'well', 'actually', 'basically'},
    'en_phrases': (('you', 'know'), ('i', 'mean'), ('sort', 'of'), ('kind', 'of')),
    'ja': ('えーと', 'えっと', 'ええと', 'えー', 'あのー', 'なんていうか', 'なんか', 'うーん', 'えっ', 'まあ'),   # not あの / ええ (content)
    'zh': ('那个', '嗯', '呃', '啊', '哦'),
}
# Guard-side negation counts (broader than the marker lexicon on purpose: a count change here only ever
# retains the source, so a Japanese adjective ending in -nai or a Chinese idiom containing bu costs at most a retention).
GUARD_NEGATION = {
    'en': re.compile(r"\b(?:not|never|no|nothing|nobody|none|cannot|can't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|won't|haven't|hasn't|without)\b", re.I),
    'ja': re.compile(r'ません|なかった|ない|ではなく|じゃなく|未定'),
    'zh': re.compile(r'[不没无非未]'),
}
# Japanese kana-only content: an added kana run that cannot be built from grammatical fragments is content
# (e.g. the kana words for 'all', 'always', 'more'). Fragments: particles, auxiliaries, common connectives and demonstrative pronouns.
KANA_FUNCTION = ('ます', 'ました', 'ません', 'ませんでした', 'です', 'でした', 'でしょう', 'だろう', 'ている', 'ています', 'ていた', 'てある', 'ておく',
                 'ください', 'こと', 'もの', 'ため', 'ように', 'ような', 'など', 'また', 'そして', 'しかし', 'ただし', 'ので', 'から', 'まで', 'より',
                 'について', 'という', 'といった', 'これ', 'それ', 'あれ', 'この', 'その', 'ここ', 'そこ', 'それで', 'それから', 'つまり', 'なお',
                 'について', 'による', 'によって', 'として', 'とか', 'たり', 'ながら', 'けれど', 'けど', 'のに', 'なら', 'たら', 'れば', 'ても', 'でも',
                 'ない', 'なかった', 'ず', 'ぬ', 'う', 'よう', 'そう', 'らしい', 'みたい', 'はず', 'わけ', 'べき', 'かも', 'しれ', 'ませ', 'ん',
                 'うち', 'なか', 'ほう', 'ところ', 'とき', 'あと', 'まえ', 'ほか', 'おり', 'さい', 'ごと', 'たび', 'あいだ', 'とおり', 'まま', 'ぐらい', 'くらい', 'ほど', 'だけ', 'しか', 'ばかり', 'すら', 'さえ')
KANA_PARTICLES = set('のはがをにでとへもやかなねよさしてたつだまいうれらせこそどばずきくけげぐっゃゅょー')
_KANA_RUN = re.compile(r'[\u3040-\u30ff\u30fc]{2,}')


def _kana_run_is_functional(run):
    i = 0
    while i < len(run):
        step = 0
        for frag in sorted(KANA_FUNCTION, key=len, reverse=True):
            if run.startswith(frag, i): step = len(frag); break
        if not step and run[i] in KANA_PARTICLES: step = 1
        if not step: return False
        i += step
    return True
EN_FUNCTION = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am', 'to', 'of', 'and', 'or', 'but', 'that',
               'which', 'who', 'it', "it's", 'its', 'we', 'i', 'you', 'they', 'he', 'she', 'in', 'on', 'at', 'for', 'with', 'this',
               'these', 'those', 'there', 'here', 'has', 'have', 'had', 'do', 'does', 'did', 'so', 'then', 'than', 'as', 'by',
               'from', 'into', 'about', 'if', 'when', 'while', 'because', 'also', 'very', 'will', 'would', 'can', 'could', 'should'}
ZH_FUNCTION = set('的了是在和与及而并也都就这那个们把被让给对为于所以之其一着过吗呢吧')
_EN_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_KANJI = re.compile(r'[\u4e00-\u9fff]')
_KANA = re.compile(r'[\u3040-\u30ff]')


def _lang_key(lang):
    lang = (lang or 'ja').lower()
    return 'ja' if lang.startswith('ja') else 'zh' if lang.startswith(('zh', 'cmn')) else 'en'


def _content_tokens(text, key):
    import unicodedata
    text = text.replace('（※要確認）', '')
    if key == 'en':
        return _EN_WORD.findall(text.lower())
    # every punctuation / symbol / separator character is ignored, whatever the script
    return [c for c in text if not c.isspace() and unicodedata.category(c)[0] not in 'PZS']


def _without_fillers(tokens, key):
    if key == 'en':
        out, i = [], 0
        while i < len(tokens):
            if any(tuple(tokens[i:i + len(p)]) == p for p in FILLERS['en_phrases']):
                i += 2; continue
            if tokens[i] not in FILLERS['en']: out.append(tokens[i])
            i += 1
        return out
    s = ''.join(tokens)
    for f in FILLERS[key]:
        s = s.replace(f, '')
    return list(s)


def readable_postcondition(source, candidate, lang='ja'):
    """Return a list of violated rules ([] = the draft stays within the bounded-edit contract)."""
    from collections import Counter
    key = _lang_key(lang)
    violations = []
    if sorted(numbers(source)) != sorted(numbers(candidate.replace('（※要確認）', ''))):
        violations.append('numerals_changed')
    src = _content_tokens(source, key); cand = Counter(_content_tokens(candidate, key))
    omitted = sum((Counter(_without_fillers(src, key)) - cand).values())
    if omitted > min(OMIT_MAX_CAP, max(OMIT_MAX_ABS, OMIT_MAX_PER100 * len(src) / 100.0)):
        violations.append(f'omission_over_limit:{omitted}/{len(src)}')
    # Polarity is content: the number of negation expressions must not change (a dropped "not" is one token
    # and would otherwise slip under the omission allowance; an added Japanese negative ending is kana-only).
    neg = GUARD_NEGATION[key]
    if len(neg.findall(source.lower())) != len(neg.findall(candidate.replace('（※要確認）', '').lower())):
        violations.append('negation_count_changed')
    added = Counter(_content_tokens(candidate, key)) - Counter(src)
    if key == 'en':
        new = [t for t in added.elements() if t not in EN_FUNCTION and t not in FILLERS['en'] and not t.isdigit()]
    elif key == 'ja':
        new = [c for c in added.elements() if _KANJI.match(c)]
        plain_src = source.replace('（※要確認）', '')
        for run in _KANA_RUN.findall(candidate.replace('（※要確認）', '')):
            if run not in plain_src and not _kana_run_is_functional(run):
                new.append(run)
    else:
        new = [c for c in added.elements() if c not in ZH_FUNCTION and not c.isdigit()]
    if new:
        violations.append('content_added:' + ' '.join(sorted(set(new))[:6]))
    return violations


def diagnostics(source, candidate):
    flags = []
    if numbers(source) != numbers(candidate):
        flags.append('numeric_expression_changed')
    for name, pattern in SIGNALS.items():
        if len(pattern.findall(source.lower())) != len(pattern.findall(candidate.lower())):
            flags.append(name)
    return flags


MODEL_DIGESTS = {
    MODEL: '38044be4f923e5a55264ed7df4eaac2676651a905f735197c504045140c02bd3',
    'gemma4:26b-a4b-it-qat': '2dd70431afed94dd3688d790443768c1487ed086b57147ff083851116ae4c4e4',
}


def sentence_chunks(text, limit=1000):
    """Prefer complete sentences; fallback never cuts an ASCII word/number.

    Source is reconstructed exactly. No claim that punctuation always marks
    linguistic sentences (abbreviations and poor ASR punctuation remain limits).
    """
    if limit < 1:
        raise ValueError('limit must be positive')
    boundaries = [m.end() for m in re.finditer(r'[。！？!?][」』”\"]*\s*|\.(?=\s+[A-Z]|\s*$)\s*|\n+', text)]
    chunks = []
    start = 0
    while start < len(text):
        if len(text)-start <= limit:
            chunks.append(text[start:]); break
        ends = [b for b in boundaries if start < b <= start+limit]
        if ends:
            end = ends[-1]
        else:
            # Shared fallback conserves even an oversized single token.
            piece = split_source(text[start:], limit)[0]
            end = start+len(piece)
        chunks.append(text[start:end]); start = end
    assert ''.join(chunks) == text
    return chunks


class ReadableFormatter(MMVFormatter):
    mode = 'readable'
    split_text = staticmethod(sentence_chunks)

    def __init__(self, call_adapter, endpoint=None, model=MODEL):
        # Reuse endpoint policy and evaluated model identity, not the QA prompts.
        self.call_adapter = call_adapter
        endpoint = local_endpoint(endpoint)
        if model not in MODEL_DIGESTS:
            raise ValueError('Unsupported readable model')
        path = PROFILE_PATH if model == MODEL else PROFILE_PATH.with_name('mmv_readable_26b_qat.json')
        self.profile = json.loads(path.read_text(encoding='utf-8'))
        if self.profile.get('model_id') != model or self.profile.get('backend') != 'ollama':
            raise ValueError('Readable profile model/backend mismatch')
        if any(self.profile.get(k) is not False for k in
               ('route_transformer', 'post_validator', 'force_reanchor_v2')):
            raise ValueError('Readable profile must explicitly disable QA routing/rewrites')
        self.profile['endpoint'] = endpoint
        self.profile_path = str(path.resolve())
        self.profile_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def check_ready(self):
        with urllib.request.urlopen(self.profile['endpoint']+'/api/tags', timeout=5) as response:
            tags = json.load(response)['models']
        model = self.profile['model_id']
        found = next((m for m in tags if m['name'] == model), None)
        if found is None or found.get('digest') != MODEL_DIGESTS[model]:
            raise RuntimeError('Measured readable model digest required: '+model)
        return found

    def format_chunk(self, source, lang='ja'):
        row = dict(source=source, candidate='', text=source, status='source_retained',
                   accepted=False, reason='not_called', seconds=0., mode=self.mode,
                   human_verified=False, semantic_verified=False, needs_review=True,
                   review_flags=[], diagnostic_rule_count=len(RULES),
                   profile_path=self.profile_path, profile_sha256=self.profile_sha256,
                   resolved_endpoint=self.profile['endpoint'],
                   diff='')
        if not source.strip():
            row.update(status='unchanged', accepted=True, reason='whitespace_only', needs_review=False)
            return row
        if len(source) > 1000:
            row['reason'] = 'unsplittable_token_too_long'
            return row
        lang = (lang or 'ja').split('-')[0].split('_')[0]
        instruction = PROMPTS.get(lang, PROMPTS['en'])
        row['prompt_sha256'] = hashlib.sha256(instruction.encode()).hexdigest()
        start = time.monotonic()
        try:
            res = self.call_adapter(instruction + json.dumps({'transcript': source}, ensure_ascii=False),
                                    copy.deepcopy(self.profile))
            candidate = (res.text or '').strip()
            row.update(candidate=candidate, tokens_in=res.tokens_in, tokens_out=res.tokens_out)
            if res.error:
                row['reason'] = 'backend_error: ' + str(res.error)
            elif not candidate:
                row['reason'] = 'empty_output'
            elif (res.tokens_out or 0) >= self.profile['max_tokens']:
                row['reason'] = 'possible_output_truncation'
            elif candidate.startswith(('Correction of the premise:', '前提の確認です：')) and not source.strip().startswith(('Correction of the premise:', '前提の確認です：')):
                row['reason'] = 'unexpected_wrapper_preamble'
            else:
                flags = diagnostics(source, candidate)
                violations = readable_postcondition(source, candidate, lang)
                model_marked = candidate.count('（※要確認）') > source.count('（※要確認）')
                # A rule cannot locate the precise semantic span: mark this chunk.
                if flags:
                    candidate += '\n（※要確認）'
                row['annotation_scope'] = '+'.join(s for s, on in (('chunk', bool(flags)), ('model_marked_spans', model_marked)) if on) or 'none'
                row['review_marker_count'] = candidate.count('（※要確認）') - source.count('（※要確認）')
                row['model_candidate'] = row['candidate']
                row['diff'] = '\n'.join(difflib.unified_diff(source.splitlines(), row['candidate'].splitlines(),
                                                             fromfile='source', tofile='draft', lineterm=''))
                row['guard_violations'] = violations
                if violations:
                    # Outside the bounded-edit contract: keep the source chunk, show why and what the model wrote.
                    row.update(text=source, accepted=False, status='source_retained',
                               reason='readable_guard: ' + '; '.join(violations), review_flags=flags)
                else:
                    lead = source[:len(source)-len(source.lstrip())]
                    tail = source[len(source.rstrip()):]
                    row.update(text=lead+candidate+tail, accepted=True,
                               status='unchanged' if candidate == source.strip() else 'formatted',
                               reason='draft_for_review', review_flags=flags)
        except Exception as exc:
            row['reason'] = f'backend_error: {type(exc).__name__}: {exc}'
        row['seconds'] = time.monotonic()-start
        return row

    def format(self, source, lang='ja', progress_cb=None):
        text, rows = super().format(source, lang, progress_cb)
        # Startup/model errors use the shared fallback path: keep provenance there too.
        for row in rows:
            row.setdefault('mode', self.mode)
            row.setdefault('human_verified', False)
            row.setdefault('semantic_verified', False)
            row.setdefault('needs_review', True)
            row.setdefault('review_flags', [])
            row.setdefault('diagnostic_rule_count', len(RULES))
            row.setdefault('profile_path', self.profile_path)
            row.setdefault('profile_sha256', self.profile_sha256)
        return text, rows
