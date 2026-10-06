"""
Cached, rate-limit-aware LLM calls.

Every reply is stored on disk under a hash of (model, settings, prompt), so an
experiment can be interrupted and resumed, repeated offline, and audited later.
Groq's free tier limits tokens per minute, so rate-limit errors are retried after
the server-suggested wait. Failed calls are never cached.
"""
import hashlib
import json
import random
import re
import time
from pathlib import Path

import config

DEFAULT_CACHE_DIR = config.project_root() / "outputs" / "llm_cache"


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model)


class CachedLLM:
    def __init__(self, model: str, cache_dir=None, temperature: float = 0.0, max_tokens: int = 1500,
                 call=None, max_retries: int = 40, extra: dict = None):
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
        self.extra = dict(extra or {})
        if model.startswith("openai/gpt-oss") and "reasoning_effort" not in self.extra:
            self.extra["reasoning_effort"] = "low"      # reasoning tokens count toward the rate limit
        self.dir = Path(cache_dir or DEFAULT_CACHE_DIR) / _slug(model)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._call = call
        self.max_retries = max_retries
        self.hits = self.misses = 0

    def key(self, prompt: str) -> str:
        payload = json.dumps([self.model, self.temperature, self.extra, prompt])   # max_tokens only caps length
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def _raw_call(self, prompt):
        if self._call is not None:
            return self._call(prompt)
        from llm_client import query_llm
        return query_llm(prompt, temperature=self.temperature, model=self.model,
                         max_tokens=self.max_tokens, **self.extra)

    @staticmethod
    def _retry_after(error) -> float:
        """Seconds the server asks us to wait: Retry-After header, else 'try again in 3.2s' in the message."""
        headers = getattr(getattr(error, "response", None), "headers", None) or {}
        try:
            header = float(headers.get("retry-after", 0))
            if header > 0:
                return header
        except (TypeError, ValueError):
            pass
        match = re.search(r"try again in (\d+(?:\.\d+)?)\s*(ms|s)", str(error))
        if match:
            value = float(match.group(1))
            return value / 1000 if match.group(2) == "ms" else value
        return 0.0

    def __call__(self, prompt: str, temperature=None) -> str:
        path = self.dir / f"{self.key(prompt)}.json"
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["reply"]
        self.misses += 1
        last = None
        for attempt in range(self.max_retries):
            try:
                reply = self._raw_call(prompt)
                path.write_text(json.dumps({"model": self.model, "reply": reply}), encoding="utf-8")
                return reply
            except Exception as error:                      # rate limits, transient server errors
                last = error
                name = type(error).__name__
                if "RateLimit" not in name and "Timeout" not in name and "Connection" not in name \
                        and "InternalServer" not in name:
                    raise
                wait = max(self._retry_after(error), min(8, 0.5 * 2 ** attempt))
                time.sleep(min(65, wait + random.uniform(0.2, 1.5)))   # jitter breaks up worker collisions
        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts: {last}")
