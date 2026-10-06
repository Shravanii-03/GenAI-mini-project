"""
Evidence bundle: requirement -> spec -> violating trace -> threat -> mitigation.

Every link stores what is needed to *re-run* it (scenario, seed, attack parameters, the
calibration seeds of the monitors, the accepted rule) together with the numbers recorded the
first time. `sdv.evidence.audit` recomputes them, so the bundle is machine-checked evidence,
not a narrative. It is a consistency check on an emulated system, not a certified safety case.
"""
import json

from sdv.attacks.library import ALL_ATTACKS
from sdv.rag.kb import load_corpora
from sdv.rag.retrievers import BM25Retriever
from sdv.spec import stl

BUNDLE_VERSION = 1


def kb_pattern_for(family: str, retriever=None):
    """Attack pattern from the knowledge base that best matches an attack family (retrieval)."""
    retriever = retriever or BM25Retriever()
    cls = ALL_ATTACKS[family]
    doc = retriever.retrieve(f"{family.replace('_', ' ')} {cls.__doc__ or ''}", "attack", 1)[0]
    raw = next(p for p in json.load(open(_attack_file(), encoding="utf-8"))["attack_patterns"] if p["id"] == doc.id)
    keep = ("id", "name", "severity", "likelihood", "tara_risk_score", "iso_reference", "mitigation")
    return {k: raw[k] for k in keep}


def _attack_file():
    from sdv.rag.kb import _kb_dir
    return _kb_dir() / "attack_patterns.json"


def build_bundle(requirement: dict, spec: dict, case: dict, rule_verdict: dict, calibration: dict,
                 residual: dict = None, retriever=None) -> dict:
    """Assemble the bundle from a missed-hazard case and the verified rule that now covers it.

    requirement  {"id", "text", "method"}; spec  extracted dict (deadline_ms, formula, ...);
    case         a blue-team case (family, theta, scenario, seed, result);
    rule_verdict verify_rule output; calibration {"train_seed0","n_train","benign_seed0","n_benign","fpr_cap"}.
    """
    result = case["result"]
    robustness = stl.parse(spec["formula"]).robustness(result.e2e_latency_ms)
    family = case["family"]
    return {
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


def kb_ids_by_kind():
    return {k: {d.id for d in docs} for k, docs in load_corpora().items()}
