"""
config.py — loads config.yaml once and exposes it with safe defaults.

Usage:
    from config import get
    model = get("llm.model")
"""
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent
_CONFIG_PATH = _ROOT / "config.yaml"

_DEFAULTS = {
    "llm": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 1024,
        "temperature_default": 0.7,
    },
    "rag": {"top_k": 3, "knowledge_base_path": "Knowledge_base/"},
}

_cache = None


def _load() -> dict:
    global _cache
    if _cache is None:
        data = {}
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        _cache = data
    return _cache


def get(dotted_key: str, default=None):
    """Look up 'a.b.c' in config.yaml, falling back to built-in defaults."""
    for source in (_load(), _DEFAULTS):
        node = source
        for part in dotted_key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        if node is not None:
            return node
    return default


def project_root() -> Path:
    return _ROOT
