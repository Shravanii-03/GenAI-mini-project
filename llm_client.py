"""
LLM Client — Groq (free tier)
Get an API key at: https://console.groq.com and put it in .env as GROQ_API_KEY.

The client is created lazily, so importing this module never fails when the
key is missing (CI jobs and tests that do not call the LLM keep working).
"""
import os

from dotenv import load_dotenv

import config

load_dotenv()

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        from groq import Groq
        _client = Groq(api_key=api_key)
    return _client


def query_llm(prompt: str, temperature: float = None, model: str = None,
              max_tokens: int = None, **extra) -> str:
    """Send prompt to the LLM (default: the model in config.yaml) and return the text."""
    if temperature is None:
        temperature = config.get("llm.temperature_default", 0.7)
    response = _get_client().chat.completions.create(
        model=model or config.get("llm.model"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens or config.get("llm.max_tokens"),
        temperature=temperature,
        **extra,
    )
    return response.choices[0].message.content or ""
