"""
tests/test_sdv_llm_prior.py — LLM prior parsing, caching and prompt grounding (no API calls).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from sdv.attacks.library import ATTACKS
from sdv.search.llm_prior import LLMGuidedBO, build_prompt, get_prior, parse_proposals, to_unit

FAMILY = "gateway_delay"


def fake_llm_factory(calls):
    def fake(prompt, temperature=0.7):
        calls.append(prompt)
        return ('Here you go:\n[{"delay_ms": 120, "duration_ms": 400, "start_offset_ms": -50},'
                ' {"delay_ms": 9999, "duration_ms": -5, "start_offset_ms": 0}, "junk",'
                ' {"delay_ms": "fast"}]')
    return fake


class TestPrompt:

    def test_prompt_lists_every_parameter_with_its_bounds(self):
        p = build_prompt(FAMILY, "hazard", 8)
        for key, (lo, hi) in ATTACKS[FAMILY].PARAM_BOUNDS.items():
            assert key in p and str(lo) in p and str(hi) in p

    def test_prompt_is_grounded_in_retrieved_attack_patterns(self):
        assert "knowledge base" in build_prompt(FAMILY, "hazard", 8)
        assert "(none)" not in build_prompt("dos_flood", "hazard", 8)

    def test_only_stealth_mode_mentions_the_monitors(self):
        assert "monitors" in build_prompt(FAMILY, "stealth", 8)
        assert "monitors check" not in build_prompt(FAMILY, "hazard", 8)


class TestParsing:

    def test_proposals_are_clipped_to_bounds_and_junk_is_ignored(self):
        props = parse_proposals(fake_llm_factory([])("x"), FAMILY)
        assert len(props) == 3
        bounds = ATTACKS[FAMILY].PARAM_BOUNDS
        for p in props:
            for key, (lo, hi) in bounds.items():
                assert lo <= p[key] <= hi
        assert props[1]["delay_ms"] == bounds["delay_ms"][1]
        assert props[2]["duration_ms"] == sum(bounds["duration_ms"]) / 2   # unusable value -> midpoint

    def test_garbage_replies_give_no_proposals(self):
        assert parse_proposals("I cannot help", FAMILY) == []
        assert parse_proposals("[not json", FAMILY) == []

    def test_unit_conversion_round_trips_the_bounds(self):
        bounds = ATTACKS[FAMILY].PARAM_BOUNDS
        low = to_unit({k: lo for k, (lo, hi) in bounds.items()}, FAMILY)
        high = to_unit({k: hi for k, (lo, hi) in bounds.items()}, FAMILY)
        assert np.allclose(low, 0) and np.allclose(high, 1)


class TestCache:

    def test_second_call_uses_the_cache_not_the_llm(self, tmp_path):
        calls = []
        path = tmp_path / "cache.json"
        a = get_prior(FAMILY, "hazard", llm=fake_llm_factory(calls), cache_path=path)
        b = get_prior(FAMILY, "hazard", llm=fake_llm_factory(calls), cache_path=path)
        assert len(calls) == 1
        assert all(np.allclose(x, y) for x, y in zip(a, b))
        assert json.loads(path.read_text())

    def test_modes_are_cached_separately(self, tmp_path):
        calls = []
        path = tmp_path / "cache.json"
        get_prior(FAMILY, "hazard", llm=fake_llm_factory(calls), cache_path=path)
        get_prior(FAMILY, "stealth", llm=fake_llm_factory(calls), cache_path=path)
        assert len(calls) == 2

    def test_prior_points_are_in_the_unit_cube(self, tmp_path):
        prior = get_prior(FAMILY, "hazard", llm=fake_llm_factory([]), cache_path=tmp_path / "c.json")
        assert all(((p >= 0) & (p <= 1)).all() for p in prior)


class TestRefusals:

    def test_refusals_are_retried_and_never_cached(self, tmp_path):
        calls, path = [], tmp_path / "c.json"

        def refusing(prompt, temperature=0.7):
            calls.append(1)
            return "I'm sorry, but I can't help with that."

        assert get_prior(FAMILY, "stealth", llm=refusing, cache_path=path, attempts=3) == []
        assert len(calls) == 3
        assert not path.exists() or not json.loads(path.read_text())

    def test_a_later_success_after_a_refusal_is_used(self, tmp_path):
        replies = iter(["I can't help with that.",
                        '[{"delay_ms": 50, "duration_ms": 300, "start_offset_ms": 0}]'])
        prior = get_prior(FAMILY, "hazard", llm=lambda p, temperature=0.7: next(replies),
                          cache_path=tmp_path / "c.json")
        assert len(prior) == 1


class TestLLMGuidedBO:

    def test_it_starts_from_the_prior_points(self):
        prior = [np.array([0.9, 0.1, 0.2]), np.array([0.3, 0.3, 0.3])]
        bo = LLMGuidedBO(3, np.random.default_rng(0), prior=prior)
        assert np.allclose(bo.ask(), prior[0]) and np.allclose(bo.ask(), prior[1])

    def test_an_empty_prior_is_rejected(self):
        with pytest.raises(ValueError):
            LLMGuidedBO(3, np.random.default_rng(0), prior=[])
