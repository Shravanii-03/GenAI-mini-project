"""Retrieval evaluation: Recall@k and MRR over a labelled query set."""
import json
from pathlib import Path

import config

QUERIES_PATH = config.project_root() / "datasets" / "benchmark" / "retrieval_queries.json"


def load_queries(path=None):
    return json.loads(Path(path or QUERIES_PATH).read_text(encoding="utf-8"))


def evaluate(retriever, queries, ks=(1, 3, 5), max_k=None):
    """Per-query reciprocal rank and hits@k; returns aggregate plus per-query rows."""
    max_k = max_k or max(ks)
    rows = []
    for q in queries:
        retrieved = [d.id for d in retriever.retrieve(q["query"], q["kind"], k=max_k)]
        gold = set(q["gold"])
        rank = next((i + 1 for i, doc_id in enumerate(retrieved) if doc_id in gold), None)
        rows.append({"id": q["id"], "kind": q["kind"], "style": q["style"], "rank": rank,
                     "rr": 1.0 / rank if rank else 0.0, **{f"hit@{k}": bool(rank and rank <= k) for k in ks}})
    return summarise(rows, ks), rows


def summarise(rows, ks=(1, 3, 5)):
    n = len(rows)
    out = {"n": n, "mrr": sum(r["rr"] for r in rows) / n if n else float("nan")}
    for k in ks:
        out[f"recall@{k}"] = sum(r[f"hit@{k}"] for r in rows) / n if n else float("nan")
    return out
