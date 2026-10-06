"""Generate (and cache) LLM starting points for every attack family and mode.

    python experiments/make_llm_priors.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.attacks.library import ATTACKS
from sdv.search.llm_prior import CACHE_PATH, get_prior

if __name__ == "__main__":
    for mode in ("hazard", "stealth"):
        for family in ATTACKS:
            prior = get_prior(family, mode)
            print(f"{mode:<8} {family:<24} {len(prior)} proposals")
    print(f"cache: {CACHE_PATH}")
