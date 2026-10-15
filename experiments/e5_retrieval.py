"""
E5: retrieval quality over the knowledge base, with chance baselines.

With 8-26 documents per corpus, "return k arbitrary documents" already scores well, so
every Recall@k is shown next to the expected chance value min(k, N)/N for that corpus.
Retrievers: legacy TF-IDF (the original), BM25, and dense/hybrid when `fastembed` is
installed.

    python experiments/e5_retrieval.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.metrics.stats import bootstrap_ci
from sdv.rag.eval import evaluate, load_queries
from sdv.rag.kb import load_corpora, load_real_vss
from sdv.rag.retrievers import BM25Retriever, DenseRetriever, HybridRetriever, LegacyTfidf


def chance_recall(queries, corpora, k):
    return sum(min(k, len(corpora[q["kind"]])) / len(corpora[q["kind"]]) for q in queries) / len(queries)


def chance_mrr(queries, corpora):
    """Expected reciprocal rank of a single gold document under a random ordering."""
    total = 0.0
    for q in queries:
        n = len(corpora[q["kind"]])
        total += sum(1.0 / r for r in range(1, n + 1)) / n
    return total / len(queries)


def build_retrievers(corpora, with_dense, generic_legacy=False):
    retrievers = [LegacyTfidf(corpora, generic=generic_legacy), BM25Retriever(corpora)]
    if with_dense:
        try:
            retrievers += [DenseRetriever(corpora), HybridRetriever(corpora)]
        except RuntimeError as error:
            print(f"(dense and hybrid skipped: {error})")
    return retrievers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dense", action="store_true", help="also evaluate dense and hybrid retrievers")
    ap.add_argument("--real-vss", action="store_true",
                    help="VSS queries run against the 1382 real VSS v6.1 signals (only queries whose gold exists there)")
    args = ap.parse_args()
    corpora = load_corpora()
    queries = load_queries()
    if args.real_vss:
        corpora["vss"] = load_real_vss()
        real_ids = {d.id for d in corpora["vss"]}
        queries = [q for q in queries if q["kind"] == "vss" and q["gold"][0] in real_ids]
    print("corpus sizes:", {k: len(v) for k, v in corpora.items()})
    retrievers = build_retrievers(corpora, args.dense, generic_legacy=args.real_vss)

    for label, subset in (("all queries", queries),
                          ("keyword queries", [q for q in queries if q["style"] == "keyword"]),
                          ("paraphrase queries", [q for q in queries if q["style"] == "paraphrase"])):
        print(f"\n{label} (n={len(subset)})")
        print(f"{'retriever':<14}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'MRR':>7}   MRR 95% CI")
        for r in retrievers:
            agg, rows = evaluate(r, subset)
            lo, hi = bootstrap_ci([x["rr"] for x in rows], stat=lambda v: sum(v) / len(v))
            print(f"{r.name:<14}{agg['recall@1']:>7.2f}{agg['recall@3']:>7.2f}{agg['recall@5']:>7.2f}"
                  f"{agg['mrr']:>7.2f}   [{lo:.2f}, {hi:.2f}]")
        print(f"{'chance':<14}{chance_recall(subset, corpora, 1):>7.2f}{chance_recall(subset, corpora, 3):>7.2f}"
              f"{chance_recall(subset, corpora, 5):>7.2f}{chance_mrr(subset, corpora):>7.2f}")

    print("\nby corpus, paraphrase queries only: MRR (chance in brackets)")
    para = [q for q in queries if q["style"] == "paraphrase"]
    print(f"{'corpus':<8}{'size':>6}" + "".join(f"{r.name:>16}" for r in retrievers))
    for kind in corpora:
        sub = [q for q in para if q["kind"] == kind]
        if not sub:
            continue
        line = f"{kind:<8}{len(corpora[kind]):>6}"
        for r in retrievers:
            line += f"{evaluate(r, sub)[0]['mrr']:>8.2f} ({chance_mrr(sub, corpora):.2f})"
        print(line)


if __name__ == "__main__":
    main()
