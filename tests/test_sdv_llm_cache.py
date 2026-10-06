"""
tests/test_sdv_llm_cache.py — disk cache, retries and cache keys (no API calls).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.llm.cached import CachedLLM


class RateLimitError(Exception):
    pass


class BadRequest(Exception):
    pass


def make(tmp_path, call, **kw):
    return CachedLLM("openai/gpt-oss-120b", cache_dir=tmp_path, call=call, **kw)


def test_second_identical_call_is_served_from_disk(tmp_path):
    calls = []
    llm = make(tmp_path, lambda p: calls.append(p) or "answer")
    assert llm("hello") == "answer" and llm("hello") == "answer"
    assert len(calls) == 1 and llm.hits == 1 and llm.misses == 1


def test_cache_survives_a_new_instance(tmp_path):
    make(tmp_path, lambda p: "first")("q")
    assert make(tmp_path, lambda p: "should not run")("q") == "first"


def test_different_prompts_models_and_settings_do_not_collide(tmp_path):
    a = make(tmp_path, lambda p: "x")
    b = CachedLLM("openai/gpt-oss-20b", cache_dir=tmp_path, call=lambda p: "x")
    c = make(tmp_path, lambda p: "x", temperature=0.7)
    assert len({a.key("p"), a.key("q"), b.key("p"), c.key("p")}) == 4


def test_rate_limits_are_retried_then_succeed(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    attempts = []

    def flaky(prompt):
        attempts.append(1)
        if len(attempts) < 3:
            raise RateLimitError("429")
        return "ok"

    assert make(tmp_path, flaky)("q") == "ok" and len(attempts) == 3


def test_failures_are_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    llm = make(tmp_path, lambda p: (_ for _ in ()).throw(RateLimitError("429")), max_retries=2)
    with pytest.raises(RuntimeError):
        llm("q")
    assert not list(llm.dir.glob("*.json"))


def test_non_transient_errors_are_raised_immediately(tmp_path):
    attempts = []

    def bad(prompt):
        attempts.append(1)
        raise BadRequest("invalid model")

    with pytest.raises(BadRequest):
        make(tmp_path, bad)("q")
    assert len(attempts) == 1


def test_reasoning_effort_is_set_for_gpt_oss_only(tmp_path):
    assert make(tmp_path, lambda p: "x").extra["reasoning_effort"] == "low"
    assert "reasoning_effort" not in CachedLLM("qwen/qwen3.8-27b", cache_dir=tmp_path, call=lambda p: "x").extra


def test_the_servers_suggested_wait_is_parsed_from_the_message():
    class E(Exception):
        pass
    assert CachedLLM._retry_after(E("429 ... Please try again in 3.21s. Need more tokens?")) == pytest.approx(3.21)
    assert CachedLLM._retry_after(E("Please try again in 250ms")) == pytest.approx(0.25)
    assert CachedLLM._retry_after(E("unrelated")) == 0.0


def test_the_wait_honours_the_server_hint_and_is_jittered(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    attempts = []

    def flaky(prompt):
        attempts.append(1)
        if len(attempts) < 3:
            raise RateLimitError("429 Please try again in 12s")
        return "ok"

    assert make(tmp_path, flaky)("q") == "ok"
    assert all(12 <= s <= 14 for s in sleeps) and len(sleeps) == 2


def test_default_retry_budget_is_large_enough_for_contended_workers(tmp_path):
    assert make(tmp_path, lambda p: "x").max_retries >= 30


def test_offline_mode_serves_the_cache_and_never_calls_the_api(tmp_path):
    from sdv.llm.cached import CacheMiss
    calls = []
    make(tmp_path, lambda p: calls.append(p) or "cached answer")("seen")
    offline = CachedLLM("openai/gpt-oss-120b", cache_dir=tmp_path, call=lambda p: calls.append(p) or "new",
                        offline=True)
    assert offline("seen") == "cached answer"
    with pytest.raises(CacheMiss):
        offline("never asked")
    assert len(calls) == 1
