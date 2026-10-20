"""K5 ranking boundary v1: immutable candidates in, a permutation out.

The host owns source permission, eligibility, project diversity and citations.
Only trusted in-process adapters are accepted here. StoredRanking interprets
verified finite programs; this is not a Python plugin loader.
"""
from types import MappingProxyType
import time


class LexicalV1:
    protocol = 1
    module_id = 'lexical-v1'

    @staticmethod
    def order(rows, words):
        return sorted(range(len(rows)), key=lambda i: (-rows[i]['score'], rows[i]['path'], rows[i]['start_line']))


class CoverageV2:
    """Development candidate only; no production default is changed."""
    protocol = 1
    module_id = 'coverage-v2'

    @staticmethod
    def order(rows, words):
        return sorted(range(len(rows)), key=lambda i: (
            -sum(w in rows[i]['text'] or w in rows[i]['heading'] for w in words),
            -rows[i]['score'], rows[i]['path'], rows[i]['start_line']))


def lexical_score(text, heading, words):
    return sum(min(text.count(w), 2)+2*(w in heading) for w in words)


def rank(rows, words, adapter=None):
    """Validate complete eligible-candidate permutation; failures use v1.

    Candidate functions receive immutable scalar-only views. They cannot add a
    source, change excerpts, remove a candidate or mutate the caller's records.
    """
    snapshot = tuple(MappingProxyType(dict(row)) for row in rows)
    words = tuple(words)
    baseline = LexicalV1.order(snapshot, words)
    selected = adapter if adapter is not None else LexicalV1()
    started = time.perf_counter()
    metadata = {'protocol': 1, 'requested': getattr(selected, 'requested_id', getattr(selected, 'module_id', 'unknown')),
                'used': 'lexical-v1', 'fallback': False, 'candidates': len(rows)}
    try:
        if selected.protocol != 1: raise ValueError('protocol')
        result = baseline if type(selected) is LexicalV1 else selected.order(snapshot, words)
        if (not isinstance(result, (list, tuple)) or len(result) != len(rows)
                or any(type(i) is not int for i in result) or sorted(result) != list(range(len(rows)))):
            raise ValueError('permutation')
        metadata['used'] = selected.module_id
    except Exception as exc:
        result = baseline
        metadata.update(fallback=True, reason=type(exc).__name__)
    metadata['elapsed_seconds'] = round(time.perf_counter()-started, 6)
    return list(result), metadata
