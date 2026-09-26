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
                model_marked = candidate.count('（※要確認）') > source.count('（※要確認）')
                # A rule cannot locate the precise semantic span: mark this chunk.
                if flags:
                    candidate += '\n（※要確認）'
                row['annotation_scope'] = '+'.join(s for s, on in (('chunk', bool(flags)), ('model_marked_spans', model_marked)) if on) or 'none'
                row['review_marker_count'] = candidate.count('（※要確認）') - source.count('（※要確認）')
                row['model_candidate'] = row['candidate']
                row['diff'] = '\n'.join(difflib.unified_diff(source.splitlines(), candidate.splitlines(),
                                                             fromfile='source', tofile='draft', lineterm=''))
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
