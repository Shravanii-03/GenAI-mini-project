"""Scoring of extracted specifications against the gold benchmark."""
import json
from pathlib import Path

import config
from sdv.metrics.stats import wilson_interval
from sdv.spec import stl
from sdv.spec.validator import normalise_can_id

BENCH_PATH = config.project_root() / "datasets" / "benchmark" / "timing_requirements_bench.json"


def load_benchmark(path=None):
    return json.loads(Path(path or BENCH_PATH).read_text(encoding="utf-8"))


def deadline_matches(pred, gold, rel_tol: float = 0.005) -> bool:
    if gold is None or pred is None:
        return gold is None and pred is None
    return abs(pred - gold) <= max(rel_tol * gold, 1e-6)


def score(gold: dict, spec, ids: dict) -> dict:
    """spec is a dict (TimingSpec fields) or None when nothing parseable was produced."""
    parsed = spec is not None
    spec = spec or {}
    pred_vss = set(spec.get("vss_signals") or [])
    pred_can = {normalise_can_id(c) for c in spec.get("can_ids") or []}
    gold_vss, gold_can = set(gold["vss_signals"]), set(gold["can_ids"])
    deadline_ok = parsed and deadline_matches(spec.get("deadline_ms"), gold["deadline_ms"])
    unresolved_ok = parsed and bool(spec.get("unresolved")) == gold["unresolved"]
    component_ok = parsed and spec.get("component") == gold["component"]
    formula_ok = False
    if parsed:
        formula = spec.get("formula")
        if spec.get("deadline_ms") is None:
            formula_ok = not formula
        else:
            try:
                formula_ok = abs(stl.parse(formula).hi_ms - spec["deadline_ms"]) < 1e-6
            except stl.STLSyntaxError:
                formula_ok = False
    return {
        "id": gold["id"], "tag": gold["tags"][0], "parsed": parsed,
        "deadline_ok": deadline_ok, "unresolved_ok": unresolved_ok, "component_ok": component_ok,
        "exact": bool(deadline_ok and unresolved_ok and component_ok), "formula_ok": formula_ok,
        "vss_tp": len(pred_vss & gold_vss), "vss_fp": len(pred_vss - gold_vss), "vss_fn": len(gold_vss - pred_vss),
        "can_tp": len(pred_can & gold_can), "can_fp": len(pred_can - gold_can), "can_fn": len(gold_can - pred_can),
        "invalid_vss": len(pred_vss - ids["vss"]), "invalid_can": len(pred_can - ids["can"]),
        "predicted_vss": len(pred_vss), "predicted_can": len(pred_can),
    }


def f1(tp, fp, fn):
    return 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else float("nan")


def aggregate(rows):
    n = len(rows)
    out = {"n": n}
    for key in ("parsed", "deadline_ok", "unresolved_ok", "component_ok", "exact", "formula_ok"):
        hits = sum(bool(r[key]) for r in rows)
        out[key] = hits / n if n else float("nan")
        out[key + "_ci"] = wilson_interval(hits, n)
    for kind in ("vss", "can"):
        tp, fp, fn = (sum(r[f"{kind}_{s}"] for r in rows) for s in ("tp", "fp", "fn"))
        out[f"{kind}_f1"] = f1(tp, fp, fn)
        out[f"invalid_{kind}"] = sum(r[f"invalid_{kind}"] for r in rows)
        out[f"predicted_{kind}"] = sum(r[f"predicted_{kind}"] for r in rows)
    return out
