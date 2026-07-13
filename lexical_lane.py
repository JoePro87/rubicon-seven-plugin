"""Lexical (BM25) lane — RAG hardening sprint Task 4. Leaf module — NEVER imports server.

A sparse lexical index sitting alongside the vector (embedding) lane over the
SAME tiered-history corpus. Exact-token matches (names, jargon) that embed
poorly still surface, because they win on lexical overlap. The two lanes are
merged by Reciprocal Rank Fusion (RRF) — rank-only, no score normalization, so
it doesn't matter that BM25 scores and cosine/L2 distances live on unrelated
scales.

Everything here is pure/deterministic and takes plain data in (ids, document
strings, metadata dicts, a ChromaDB-collection-shaped object for the lazy
index build) — no server.py import, no MCP/tool decorators, no I/O beyond the
`collection` object handed to it by the caller.
"""

import math
import re
from typing import Callable, Optional

try:
    from rank_bm25 import BM25Okapi as _BM25Backend
    _USING_RANK_BM25 = True
except Exception:  # pragma: no cover - only exercised when rank_bm25 isn't installed
    _USING_RANK_BM25 = False

    class _BM25Backend:
        """Minimal Okapi BM25 fallback (k1=1.5, b=0.75), used only if the
        `rank_bm25` package isn't importable. Matches rank_bm25.BM25Okapi's
        `get_scores(query_tokens) -> list[float]` contract so callers never
        need to know which backend is active.
        """

        def __init__(self, corpus, k1: float = 1.5, b: float = 0.75):
            self.corpus = corpus
            self.k1 = k1
            self.b = b
            self.doc_lens = [len(doc) for doc in corpus]
            self.avgdl = (sum(self.doc_lens) / len(corpus)) if corpus else 0.0
            self.doc_freqs = []
            df = {}
            for doc in corpus:
                freqs = {}
                for term in doc:
                    freqs[term] = freqs.get(term, 0) + 1
                self.doc_freqs.append(freqs)
                for term in freqs:
                    df[term] = df.get(term, 0) + 1
            n = len(corpus)
            self.idf = {
                term: math.log((n - freq + 0.5) / (freq + 0.5) + 1)
                for term, freq in df.items()
            }

        def get_scores(self, query):
            scores = [0.0] * len(self.corpus)
            for term in query:
                idf = self.idf.get(term)
                if idf is None:
                    continue
                for i, freqs in enumerate(self.doc_freqs):
                    freq = freqs.get(term)
                    if not freq:
                        continue
                    dl = self.doc_lens[i]
                    norm = (1 - self.b + self.b * dl / self.avgdl) if self.avgdl else 1.0
                    denom = freq + self.k1 * norm
                    scores[i] += idf * (freq * (self.k1 + 1)) / denom
            return scores


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: Optional[str]) -> list[str]:
    """Lowercase word/number tokenizer. Deliberately simple (no stemming/stopwords —
    BM25's own IDF term already downweights common words)."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


class LexicalIndex:
    """A built BM25 index over a parallel (ids, documents, metadatas) corpus."""

    __slots__ = ("ids", "documents", "metadatas", "_bm25")

    def __init__(self, ids: list, documents: list[str], metadatas: list[dict], bm25):
        self.ids = ids
        self.documents = documents
        self.metadatas = metadatas
        self._bm25 = bm25

    @property
    def is_empty(self) -> bool:
        return self._bm25 is None or not self.documents


def build_index(ids: list, documents: list[str], metadatas: list[dict]) -> LexicalIndex:
    """Build a LexicalIndex from a (ids, documents, metadatas) triple, e.g. the
    shape returned by `collection.get(include=["documents", "metadatas"])`."""
    documents = list(documents or [])
    metadatas = list(metadatas or [])
    ids = list(ids or [])
    if not documents:
        return LexicalIndex(ids=ids, documents=documents, metadatas=metadatas, bm25=None)
    tokenized_corpus = [tokenize(doc) for doc in documents]
    bm25 = _BM25Backend(tokenized_corpus)
    return LexicalIndex(ids=ids, documents=documents, metadatas=metadatas, bm25=bm25)


# Lazy per-process cache, keyed by collection name. Rebuilt whenever the live
# collection's doc count changes (cheap staleness check — no persisted cache
# in v1, per spec). Not thread-safe by design (matches the rest of this
# codebase's lazy-singleton pattern); fine for a single-process MCP server.
_PROCESS_CACHE: dict = {}


def get_or_build_index(collection, cache: Optional[dict] = None) -> LexicalIndex:
    """Return the cached LexicalIndex for `collection`, rebuilding it if the
    collection's doc count has changed since the last build (or if this is the
    first call this process). Raises on any failure — callers own fail-open
    (catch, log, fall back to vector-only); this function does not swallow
    errors itself so a genuine bug isn't silently hidden.
    """
    cache = _PROCESS_CACHE if cache is None else cache
    name = getattr(collection, "name", None) or repr(collection)
    current_count = collection.count()
    entry = cache.get(name)
    if entry is not None and current_count is not None and entry.get("count") == current_count:
        return entry["index"]

    data = collection.get(include=["documents", "metadatas"])
    ids = data.get("ids") or []
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []
    index = build_index(ids, documents, metadatas)
    cache[name] = {"index": index, "count": current_count}
    return index


def search(index: Optional[LexicalIndex], query: str, top_k: int = 20,
           filter_fn: Optional[Callable[[dict], bool]] = None) -> list[tuple]:
    """BM25-rank `index`'s corpus against `query`, best match first.

    Returns a list of (doc, meta, score) tuples (score: higher = better),
    zero-score docs (no token overlap at all) excluded, optionally restricted
    to metas passing `filter_fn` (mirrors whatever tier/day/arc/character
    filter the caller's vector-lane query used, applied post-hoc since BM25
    scores over the whole corpus in one pass).
    """
    if index is None or index.is_empty:
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    scores = index._bm25.get_scores(query_tokens)
    hits = []
    for doc, meta, score in zip(index.documents, index.metadatas, scores):
        if score <= 0:
            continue
        if filter_fn is not None and not filter_fn(meta):
            continue
        hits.append((doc, meta, float(score)))
    hits.sort(key=lambda h: h[2], reverse=True)
    return hits[:top_k]


def reciprocal_rank_fusion(rank_lists: list[list], k: int = 60) -> list[tuple]:
    """Standard Reciprocal Rank Fusion, rank-only (no score normalization).

    Each list in `rank_lists` is a ranking (best match first) over some key
    (e.g. document text). score(key) = sum over lists containing key of
    1 / (k + rank), rank counted from 1. Returns (key, fused_score) sorted
    descending by fused_score. Pure function — no I/O, fully deterministic.
    """
    scores: dict = {}
    for rank_list in rank_lists:
        for rank, key in enumerate(rank_list, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def fuse_lexical_into_vector(vector_results: list[tuple], lexical_hits: list[tuple],
                              weak_match_dist: float, k: int = 60,
                              max_results: int = 20) -> list[tuple]:
    """Fuse a vector-lane result list with a lexical-lane result list by RRF,
    returning (doc, meta, dist) tuples in fused order — the same shape the
    vector lane already produces, so downstream re-rank steps (keyword boost,
    recency) work unmodified.

    Fusion identity is the document TEXT (both lanes read the same collection,
    so identical text ~= identical chunk; a first-pass simplification — see
    Task 4 report). Docs present in the vector lane keep their real distance
    (so the existing strong-match recency bypass still works for them). Docs
    surfaced ONLY by the lexical lane (i.e. the vector lane missed them
    entirely — the whole point of this lane) get `weak_match_dist` as a
    baseline distance: the collection's own WEAK_MATCH threshold, already the
    codebase's definition of "boundary, worth surfacing" — not a real
    similarity score, just a fair starting point for the re-rank steps that
    run after fusion.
    """
    if not vector_results and not lexical_hits:
        return []

    vector_keys = [doc for doc, _meta, _dist in vector_results]
    lexical_keys = [doc for doc, _meta, _score in lexical_hits]
    fused = reciprocal_rank_fusion([vector_keys, lexical_keys], k=k)

    vector_lookup = {doc: (doc, meta, dist) for doc, meta, dist in vector_results}
    lexical_lookup = {doc: (doc, meta) for doc, meta, _score in lexical_hits}

    out = []
    for key, _score in fused:
        if key in vector_lookup:
            out.append(vector_lookup[key])
        elif key in lexical_lookup:
            doc, meta = lexical_lookup[key]
            out.append((doc, meta, weak_match_dist))
        if len(out) >= max_results:
            break
    return out
