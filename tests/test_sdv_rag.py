"""
tests/test_sdv_rag.py — normalisation, BM25, legacy wrapper, evaluation and query set.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.rag.eval import evaluate, load_queries, summarise
from sdv.rag.kb import KINDS, kb_ids, load_corpora, load_real_vss, split_camel, stem, tokenize
from sdv.rag.retrievers import BM25, BM25Retriever, DenseRetriever, LegacyTfidf


class TestNormalisation:

    def test_camel_case_and_dotted_paths_are_split(self):
        assert split_camel("IsEngaged") == "Is Engaged"
        assert tokenize("Vehicle.ADAS.ABS.IsEngaged", do_stem=False) == ["vehicle", "adas", "abs", "engaged"]

    def test_acronym_boundaries(self):
        assert split_camel("ABSBrakeAssist") == "ABS Brake Assist"

    def test_stopwords_removed_and_light_stemming(self):
        assert tokenize("the brakes are applied") == ["brak", "appli"]
        assert stem("lights") == "light" and stem("glass") == "glass" and stem("is") == "is"

    def test_inflections_of_one_word_share_a_stem(self):
        assert len({stem(w) for w in ("brake", "brakes", "braking", "braked")}) == 1
        assert stem("detected") == stem("detect") == stem("detects")


class TestCorpora:

    def test_all_kinds_are_loaded_with_unique_ids(self):
        c = load_corpora()
        assert set(c) == set(KINDS)
        for docs in c.values():
            assert docs and len({d.id for d in docs}) == len(docs)

    def test_kb_ids_cover_every_document(self):
        ids = kb_ids()
        assert "Vehicle.Speed" in ids["vss"] and "0x1A0" in ids["can"]


class TestBM25:

    def test_rare_terms_outweigh_common_ones(self):
        docs = [["brake", "pedal"], ["brake", "light"], ["steering", "angle"]]
        bm = BM25(docs)
        scores = bm.scores(["steering", "brake"])
        assert scores[2] > scores[0] and scores[0] > 0

    def test_no_overlap_gives_zero(self):
        assert BM25([["a"], ["b"]]).scores(["zzz"]) == [0.0, 0.0]

    def test_retriever_returns_nothing_when_nothing_matches(self):
        assert BM25Retriever().retrieve("zzzz qqqq", "vss", 5) == []

    def test_keyword_query_finds_the_entry(self):
        r = BM25Retriever()
        assert r.retrieve("brake pedal position percentage", "vss", 1)[0].id == "Vehicle.Chassis.Brake.PedalPosition"
        assert r.retrieve("traction control commands", "can", 1)[0].id == "0x700"


class TestLegacy:

    def test_wrapper_returns_documents(self):
        docs = LegacyTfidf().retrieve("emergency brake command", "can", 3)
        assert docs and all(d.kind == "can" for d in docs)

    def test_it_returns_unrelated_documents_when_nothing_matches(self):
        """The original fallback: first k documents, relevant or not."""
        docs = LegacyTfidf().retrieve("zzzz qqqq", "vss", 3)
        assert len(docs) == 3


class TestEvaluation:

    def test_query_set_is_well_formed(self):
        qs = load_queries()
        ids = kb_ids()
        assert len(qs) == 106 and {q["style"] for q in qs} == {"keyword", "paraphrase"}
        assert all(set(q["gold"]) <= ids[q["kind"]] for q in qs)

    def test_perfect_and_empty_retrievers(self):
        qs = [{"id": "q", "kind": "can", "style": "keyword", "query": "x", "gold": ["0x1A0"]}]
        class Perfect:
            def retrieve(self, q, kind, k):
                return [d for d in load_corpora()[kind] if d.id == "0x1A0"]
        class Empty:
            def retrieve(self, q, kind, k):
                return []
        assert evaluate(Perfect(), qs)[0]["mrr"] == 1.0
        agg = evaluate(Empty(), qs)[0]
        assert agg["recall@5"] == 0.0 and agg["mrr"] == 0.0

    def test_mrr_uses_the_first_gold_rank(self):
        rows = [{"rr": 0.5, "hit@1": False, "hit@3": True, "hit@5": True},
                {"rr": 1.0, "hit@1": True, "hit@3": True, "hit@5": True}]
        s = summarise(rows)
        assert s["mrr"] == 0.75 and s["recall@1"] == 0.5

    def test_bm25_is_perfect_on_keyword_queries(self):
        qs = [q for q in load_queries() if q["style"] == "keyword"]
        assert evaluate(BM25Retriever(), qs)[0]["recall@1"] > 0.95


def test_dense_retriever_needs_its_optional_dependency():
    import importlib.util
    if importlib.util.find_spec("fastembed") is not None:
        pytest.skip("fastembed installed; dense retriever covered by the retrieval experiment")
    with pytest.raises(RuntimeError):
        DenseRetriever()


class TestRealVSS:

    def test_the_official_catalogue_is_loaded_and_unique(self):
        docs = load_real_vss()
        assert len(docs) > 1000 and len({d.id for d in docs}) == len(docs)
        assert "Vehicle.Speed" in {d.id for d in docs}

    def test_the_hand_made_kb_is_not_fully_real_vss(self):
        """Documented finding: 10 of the 26 hand-written signal paths are not real VSS paths."""
        real = {d.id for d in load_real_vss()}
        handmade = {d.id for d in load_corpora()["vss"]}
        assert len(handmade - real) == 10 and len(handmade & real) == 16

    def test_generic_legacy_mode_scores_a_custom_corpus_with_the_original_fallback(self):
        corpora = load_corpora()
        corpora["vss"] = load_real_vss()
        legacy = LegacyTfidf(corpora, generic=True)
        assert legacy.retrieve("steering wheel angle", "vss", 3)
        assert len(legacy.retrieve("zzzz qqqq", "vss", 3)) == 3        # unrelated first-k fallback

    def test_bm25_finds_a_named_signal_among_over_a_thousand(self):
        corpora = load_corpora()
        corpora["vss"] = load_real_vss()
        top = BM25Retriever(corpora).retrieve("steering wheel angle", "vss", 5)
        assert any(d.id == "Vehicle.Chassis.SteeringWheel.Angle" for d in top)
