"""
Evidence bundle: requirement -> spec -> violating trace -> threat -> mitigation.

Every link stores what is needed to *re-run* it (scenario, seed, attack parameters, the
calibration seeds of the monitors, the accepted rule) together with the numbers recorded the
first time. `sdv.evidence.audit` recomputes them, so the bundle is machine-checked evidence,
not a narrative. It is a consistency check on an emulated system, not a certified safety case.
"""
import json

from sdv.attacks.library import ALL_ATTACKS, KB_PATTERN_FOR
from sdv.rag.kb import load_corpora
from sdv.rag.retrievers import BM25Retriever
from sdv.spec import stl

BUNDLE_VERSION = 2


def _kb_attack_patterns():
    return {p["id"]: p for p in json.load(open(_attack_file(), encoding="utf-8"))["attack_patterns"]}


def kb_pattern_for(family: str, retriever=None):
    """The declared knowledge-base pattern for an attack family, plus what retrieval would suggest.

    The declared mapping (KB_PATTERN_FOR) is what the bundle cites; the retrieval suggestion is
    recorded next to it so a disagreement is visible instead of silently wrong.
    """
    raw = _kb_attack_patterns()[KB_PATTERN_FOR[family]]
    keep = ("id", "name", "severity", "likelihood", "tara_risk_score", "iso_reference", "mitigation")
    pattern = {k: raw[k] for k in keep}
    retriever = retriever or BM25Retriever()
    cls = ALL_ATTACKS[family]
    top = retriever.retrieve(f"{family.replace('_', ' ')} {cls.__doc__ or ''}", "attack", 1)[0]
    pattern["retrieval_suggestion"] = {"id": top.id, "name": top.title, "agrees": top.id == raw["id"]}
    return pattern


def _attack_file():
    from sdv.rag.kb import _kb_dir
    return _kb_dir() / "attack_patterns.json"


DEFENCE_CONFIGS = {
    "radar_or": {"mitigation": "radar_or"},
    "+guard": {"mitigation": "radar_or", "gateway_guard": True},
    "+auth": {"mitigation": "radar_or", "auth": True},
    "+guard+auth": {"mitigation": "radar_or", "gateway_guard": True, "auth": True},
}


def defence_params(name: str):
    """Chain parameters for one defence configuration (see sdv/system/brake_chain.py)."""
    import dataclasses
    from sdv.blue.loop import radar_params
    return dataclasses.replace(radar_params(), **DEFENCE_CONFIGS[name])


def failover_params():
    """Perception with the redundant radar and OR-voting."""
    return defence_params("radar_or")


def config_record(case: dict, name: str) -> dict:
    """Re-simulate the case under one defence configuration, with the analytic bound and the point of no return."""
    from sdv.analysis.bounds import latency_bound_ms
    from sdv.attacks.library import make_attack
    from sdv.runner import execute
    from sdv.schemas import Scenario
    scenario = Scenario(**case["scenario"])
    params = defence_params(name)
    result, _ = execute(scenario, case["seed"], params=params,
                        attacks=[make_attack(case["family"], **case["theta"])])
    bound = latency_bound_ms(scenario, make_attack(case["family"], **case["theta"]), params).total_ms
    return {"policy": name, "e2e_latency_ms": result.e2e_latency_ms,
            "collision": result.outcome.collision, "effective": not result.outcome.collision,
            "latency_bound_ms": bound, "latest_safe_latency_ms": result.latest_safe_latency_ms,
            "bound_proves_safe": bound <= result.latest_safe_latency_ms}


def failover_record(case: dict) -> dict:
    return config_record(case, "radar_or")


def defence_records(case: dict) -> dict:
    return {name: config_record(case, name) for name in DEFENCE_CONFIGS}


def build_bundle(requirement: dict, spec: dict, case: dict, rule_verdict: dict, calibration: dict,
                 residual: dict = None, retriever=None, with_failover: bool = False,
                 with_defences: bool = False) -> dict:
    """Assemble the bundle from a missed-hazard case and the verified rule that now covers it.

    requirement  {"id", "text", "method"}; spec  extracted dict (deadline_ms, formula, ...);
    case         a blue-team case (family, theta, scenario, seed, result);
    rule_verdict verify_rule output; calibration {"train_seed0","n_train","benign_seed0","n_benign","fpr_cap"}.
    """
    result = case["result"]
    robustness = stl.parse(spec["formula"]).robustness(result.e2e_latency_ms)
    family = case["family"]
    bundle = {
        "version": BUNDLE_VERSION,
        "requirement": requirement,
        "spec": {k: spec.get(k) for k in ("deadline_ms", "formula", "trigger", "response", "component")},
        "violation": {
            "scenario": case["scenario"], "seed": case["seed"], "radar": True,
            "attack": {"family": family, "params": case["theta"]},
            "recorded": {"e2e_latency_ms": result.e2e_latency_ms, "robustness_ms": robustness,
                         "collision": result.outcome.collision,
                         "latest_safe_latency_ms": result.latest_safe_latency_ms},
        },
        "threat": {"family": family, "capability": ALL_ATTACKS[family].capability,
                   "kb_pattern": kb_pattern_for(family, retriever)},
        "mitigation": {"rule": rule_verdict["rule"],
                       "verification": {"fpr": rule_verdict["fpr"], "fpr_cap": calibration["fpr_cap"],
                                        "new_timely": rule_verdict["new_timely"]}},
        "calibration": calibration,
        "residual_risk": residual or {},
    }
    if with_failover:
        bundle["failover"] = failover_record(case)
    if with_defences:
        bundle["defences"] = defence_records(case)
    return bundle


def kb_ids_by_kind():
    return {k: {d.id for d in docs} for k, docs in load_corpora().items()}
