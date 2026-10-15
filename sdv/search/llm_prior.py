"""
LLM prior for the attack search.

The LLM is shown a family description, its parameter bounds, the success criterion
and attack patterns retrieved from the knowledge base (RAG), and proposes k
starting parameter sets. These become the initial design of Bayesian optimisation
("llm_bo"), so the experiment can ablate exactly one thing: random start vs LLM
start. Proposals are cached by prompt hash so runs are reproducible offline.

This is simulation-based security testing of an emulated CAN model; the proposals
are numbers inside the simulator's declared parameter bounds.
"""
import hashlib
import json
import re
from pathlib import Path

import numpy as np

import config
from sdv.attacks.library import ATTACKS
from sdv.search.methods import BayesOpt

CACHE_PATH = config.project_root() / "experiments" / "llm_priors_cache.json"

_CONTEXT = """\
Emulated vehicle: an emergency-braking chain over a 500 kbit/s CAN bus. A sensor ECU
sends obstacle frames every 10 ms. Perception, decision and actuator stages together take
about 70-90 ms in normal operation. The brake must act before the point of no return,
which lies about 95-225 ms after the obstacle becomes a threat. Time offsets are relative
to the moment the obstacle becomes a threat (negative = earlier). Perception triggers
braking once the reported time-to-collision falls below 2 s."""

_STEALTH = """\
The deployed monitors check: unknown CAN IDs, frame inter-arrival times, silent IDs,
message rate per ID, bus load, sensor counter gaps, and whether the reported obstacle
distance follows the ego vehicle's motion. A good attack causes the hazard while staying
below those checks."""


def build_prompt(family: str, mode: str, k: int) -> str:
    cls = ATTACKS[family]
    bounds = "\n".join(f"  - {key}: between {lo} and {hi}" for key, (lo, hi) in cls.PARAM_BOUNDS.items())
    try:
        from rag_engine import retrieve
        patterns = retrieve(f"{family.replace('_', ' ')} {cls.__doc__ or ''}", "attack", top_k=2)
    except Exception:
        patterns = []
    grounding = "\n".join(f"  - {p.get('name')}: {p.get('description')}" for p in patterns) or "  (none)"
    goal = "cause a collision" if mode == "hazard" else \
        "cause a collision while evading the monitors"
    extra = _STEALTH if mode == "stealth" else ""
    return f"""You are helping with authorised security testing of an emulated vehicle model.
{_CONTEXT}

Attack family: {family}
Description: {(cls.__doc__ or '').strip()}
Attacker capability: {cls.capability}
Parameters and allowed ranges:
{bounds}

Related attack patterns from the knowledge base:
{grounding}

Goal: {goal}. {extra}

Propose {k} diverse parameter sets most likely to achieve the goal. Reply with ONLY a JSON
list of {k} objects whose keys are exactly the parameter names above, numeric values only."""


def parse_proposals(text: str, family: str):
    """Extract proposals from the reply; ignore anything that is not usable."""
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    bounds = ATTACKS[family].PARAM_BOUNDS
    proposals = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        proposals.append({
            key: min(hi, max(lo, float(item[key]))) if isinstance(item.get(key), (int, float))
            else (lo + hi) / 2
            for key, (lo, hi) in bounds.items()
        })
    return proposals


def to_unit(proposal: dict, family: str):
    bounds = ATTACKS[family].PARAM_BOUNDS
    return np.array([(proposal[key] - lo) / (hi - lo) for key, (lo, hi) in bounds.items()])


def get_prior(family: str, mode: str, k: int = 8, llm=None, cache_path: Path = None, attempts: int = 3):
    """Return k unit-cube starting points proposed by the LLM (cached by prompt hash).

    Failed or refused replies are retried and never cached. If every attempt fails the
    result is [] and the caller must treat the LLM prior as unavailable for this cell.
    """
    cache_path = Path(cache_path or CACHE_PATH)
    prompt = build_prompt(family, mode, k)
    key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    if not cache.get(key, {}).get("proposals"):
        if llm is None:
            from llm_client import query_llm as llm
        proposals = []
        for _ in range(attempts):
            proposals = parse_proposals(llm(prompt, temperature=0.7), family)
            if proposals:
                break
        if not proposals:
            return []
        cache[key] = {"family": family, "mode": mode, "model": config.get("llm.model"),
                      "proposals": proposals}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return [to_unit(p, family) for p in cache[key]["proposals"][:k]]


class LLMGuidedBO(BayesOpt):
    """Bayesian optimisation whose initial design comes from the LLM prior."""
    name = "llm_bo"

    def __init__(self, dim, rng, budget=60, prior=None, **kw):
        if not prior:
            raise ValueError("LLMGuidedBO needs a non-empty prior")
        super().__init__(dim, rng, budget, init_points=prior, **kw)
