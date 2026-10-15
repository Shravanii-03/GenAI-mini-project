"""
Retrievers over the knowledge-base corpora.

  LegacyTfidf    the original rag_engine.retrieve (TF-IDF, no CamelCase splitting, and a
                 fallback that returns the first k documents when nothing matches)
  BM25Retriever  Okapi BM25 over normalised text; returns nothing when nothing matches
  DenseRetriever optional embedding retriever (needs the `fastembed` package)
  HybridRetriever reciprocal-rank fusion of BM25 and dense rankings

All expose retrieve(query, kind, k) -> list[Doc].
"""
import math
from collections import Counter

from sdv.rag.kb import Doc, load_corpora, tokenize


class BM25:
    def __init__(self, docs_tokens, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(t) for t in docs_tokens]
        self.len = [len(t) for t in docs_tokens]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        df = Counter()
        for counts in self.tf:
            df.update(counts.keys())
        n = len(docs_tokens)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query_tokens):
        out = []
        for counts, length in zip(self.tf, self.len):
            s = 0.0
            for t in query_tokens:
                f = counts.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / (self.avg or 1)))
            out.append(s)
        return out


class BM25Retriever:
    name = "bm25"

    def __init__(self, corpora=None, **bm25_kw):
        self.corpora = corpora or load_corpora()
        self.index = {kind: BM25([tokenize(d.text) for d in docs], **bm25_kw)
                      for kind, docs in self.corpora.items()}

    def rank(self, query: str, kind: str):
        scores = self.index[kind].scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        return [(self.corpora[kind][i], scores[i]) for i in order if scores[i] > 0]

    def retrieve(self, query: str, kind: str, k: int = 5):
        return [d for d, _ in self.rank(query, kind)[:k]]


class LegacyTfidf:
    """The retriever used by the original pipeline, wrapped to return Doc objects."""
    name = "tfidf_legacy"

    _KEY = {"vss": "path", "can": "id", "attack": "id", "rule": "rule_id"}
    _KIND = {"vss": "vss", "can": "can", "attack": "attack", "rule": "iso"}

    def __init__(self, corpora=None, generic: bool = False):
        """generic=True scores the supplied documents with the original TF-IDF formula
        instead of reading the knowledge-base files (needed for a custom corpus)."""
        self.corpora = corpora or load_corpora()
        self.generic = generic
        self.by_id = {kind: {d.id: d for d in docs} for kind, docs in self.corpora.items()}

    def _retrieve_generic(self, query: str, kind: str, k: int):
        import rag_engine
        docs = self.corpora[kind]
        texts = [d.text for d in docs]
        q_tokens = rag_engine._tokenize(query)
        scored = []
        for i, text in enumerate(texts):
            score = rag_engine._tfidf_score(q_tokens, rag_engine._tokenize(text), texts)
            if score > 0:
                scored.append((i, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        picked = [docs[i] for i, _ in scored[:k]]
        return picked or docs[:k]                      # the original fallback: first k documents

    def retrieve(self, query: str, kind: str, k: int = 5):
        if self.generic:
            return self._retrieve_generic(query, kind, k)
        import rag_engine
        items = rag_engine.retrieve(query, self._KIND[kind], top_k=k)
        docs = []
        for item in items:
            doc = self.by_id[kind].get(item.get(self._KEY[kind]))
            if doc is not None:
                docs.append(doc)
        return docs


class DenseRetriever:
    name = "dense"

    def __init__(self, corpora=None, model_name: str = "BAAI/bge-small-en-v1.5"):
        try:
            from fastembed import TextEmbedding
        except ImportError as error:
            raise RuntimeError("DenseRetriever needs the 'fastembed' package") from error
        self.corpora = corpora or load_corpora()
        self.model = TextEmbedding(model_name=model_name)
        self.vectors = {}
        for kind, docs in self.corpora.items():
            self.vectors[kind] = self._normalise(list(self.model.embed([d.title + " " + d.text for d in docs])))

    @staticmethod
    def _normalise(vectors):
        import numpy as np
        m = np.array(vectors, dtype=float)
        return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)

    def rank(self, query: str, kind: str):
        q = self._normalise(list(self.model.embed([query])))[0]
        scores = self.vectors[kind] @ q
        order = scores.argsort()[::-1]
        return [(self.corpora[kind][int(i)], float(scores[i])) for i in order]

    def retrieve(self, query: str, kind: str, k: int = 5):
        return [d for d, _ in self.rank(query, kind)[:k]]


class HybridRetriever:
    """Reciprocal-rank fusion (k=60) of BM25 and dense rankings."""
    name = "hybrid"

    def __init__(self, corpora=None, rrf_k: int = 60):
        self.bm25 = BM25Retriever(corpora)
        self.dense = DenseRetriever(corpora)
        self.rrf_k = rrf_k

    def retrieve(self, query: str, kind: str, k: int = 5):
        fused = {}
        for ranking in (self.bm25.rank(query, kind), self.dense.rank(query, kind)):
            for position, (doc, _) in enumerate(ranking):
                fused[doc] = fused.get(doc, 0.0) + 1.0 / (self.rrf_k + position + 1)
        return [d for d, _ in sorted(fused.items(), key=lambda kv: -kv[1])[:k]]


__all__ = ["BM25", "BM25Retriever", "LegacyTfidf", "DenseRetriever", "HybridRetriever", "Doc"]
