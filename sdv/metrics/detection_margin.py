"""
Detection margin: does a detector raise its alarm before the hazard becomes unavoidable?

    margin = latest_safe_latency - (time_to_detection + response_time)

All times are relative to the moment the obstacle becomes a threat. The latest safe
latency is the plant's exact point of no return: braking later than that cannot
avoid the collision. margin > 0 means the alarm (plus mitigation) came in time.

F1 and detection rate say whether an attack was noticed; the margin says whether
noticing it mattered.
"""
import math

from sdv.schemas import RunResult


def detection_time_ms(alarm_us, t_appear_us):
    """Alarm time relative to threat onset; +inf if the detector never fired."""
    return math.inf if alarm_us is None else (alarm_us - t_appear_us) / 1000.0


def detection_margin_ms(result: RunResult, alarm_us, t_appear_us, response_ms=0.0):
    """Margin for one run, or None when the hazard is unavoidable even at zero latency."""
    if result.latest_safe_latency_ms < 0:
        return None
    return result.latest_safe_latency_ms - (detection_time_ms(alarm_us, t_appear_us) + response_ms)


def classify_run(alarm_us, attack_start_us):
    """Run-level outcome. An alarm before the attack starts is a false alarm."""
    attacked = attack_start_us is not None
    alarmed = alarm_us is not None
    if attacked:
        if alarmed and alarm_us >= attack_start_us:
            return "TP"
        return "FP" if alarmed else "FN"
    return "FP" if alarmed else "TN"


def f1_from_counts(tp, fp, fn):
    if tp == 0:
        return 0.0
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def summarise(rows):
    """rows: dicts with keys outcome ('TP','FP','FN','TN'), hazard (bool), margin_ms (float|None).

    Returns detection metrics plus the safety-relevant ones: among attack-induced
    hazards, how many were flagged in time, and the median margin.
    """
    counts = {k: sum(r["outcome"] == k for r in rows) for k in ("TP", "FP", "FN", "TN")}
    tp, fp, fn, tn = (counts[k] for k in ("TP", "FP", "FN", "TN"))
    hazard_rows = [r for r in rows if r["hazard"] and r["margin_ms"] is not None]
    timely = [r for r in hazard_rows if r["margin_ms"] > 0]
    finite = sorted(r["margin_ms"] for r in hazard_rows if math.isfinite(r["margin_ms"]))
    return {
        "recall": tp / (tp + fn) if tp + fn else float("nan"),
        "fpr": fp / (fp + tn) if fp + tn else float("nan"),
        "f1": f1_from_counts(tp, fp, fn),
        "hazard_runs": len(hazard_rows),
        "timely_rate": len(timely) / len(hazard_rows) if hazard_rows else float("nan"),
        "median_margin_ms": finite[len(finite) // 2] if finite else float("nan"),
    }
