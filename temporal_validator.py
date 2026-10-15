"""
temporal_validator.py — MODULE 4: Real-Time Temporal Validator
══════════════════════════════════════════════════════════════════
Detects timing violations by comparing expected vs actual runtime delays.
Fixes the base paper's offline/static limitation — validates at runtime.

Novel: combines per-step chain validation + total latency + GenAI diagnosis.
Paper reference: Functional safety validation (steps 11-12), event chain rules.
"""

import json
from typing import Optional
from llm_client import query_llm


# ──────────────────────────────────────────────────────────────────────
# Risk level thresholds
# ──────────────────────────────────────────────────────────────────────
RISK_CRITICAL  = 1.5   # actual > 150% of max
RISK_HIGH      = 1.1   # actual > 110% of max
RISK_MEDIUM    = 0.9   # actual > 90% of max (approaching limit)
RISK_LOW       = 0.7   # actual < 70% of max


def compute_risk_level(risk_score: float) -> str:
    if risk_score >= RISK_CRITICAL: return "CRITICAL"
    if risk_score >= RISK_HIGH:     return "HIGH"
    if risk_score >= RISK_MEDIUM:   return "MEDIUM"
    return "LOW"


def validate_timing(
    expected_ms: int,
    actual_ms: int,
    event_chain_timing: Optional[list] = None
) -> dict:
    """
    Core temporal validation: compare expected vs actual timing.
    Also validates individual event chain step order and bottleneck.
    
    Returns structured validation result with risk score, violation flag,
    bottleneck step, and per-step analysis.
    """
    violation    = actual_ms > expected_ms
    risk_score   = round(actual_ms / expected_ms, 3) if expected_ms > 0 else 0
    risk_level   = compute_risk_level(risk_score)
    margin_ms    = expected_ms - actual_ms  # positive = safe margin, negative = over

    # Per-step analysis
    step_analysis = []
    bottleneck = None

    if event_chain_timing:
        # Sort by time
        sorted_chain = sorted(event_chain_timing, key=lambda x: x.get("time_ms", 0))
        prev_time = 0
        for step in sorted_chain:
            step_time  = step.get("time_ms", 0)
            step_delta = step_time - prev_time
            step_analysis.append({
                "step":       step.get("step", "unknown"),
                "time_ms":    step_time,
                "delta_ms":   step_delta,
                "cumulative": step_time
            })
            prev_time = step_time

        # Bottleneck = step with highest delta
        if step_analysis:
            bottleneck = max(step_analysis, key=lambda x: x["delta_ms"])

    return {
        "violation":          violation,
        "risk_score":         risk_score,
        "risk_level":         risk_level,
        "actual_ms":          actual_ms,
        "expected_ms":        expected_ms,
        "margin_ms":          margin_ms,
        "bottleneck":         bottleneck,
        "chain_steps":        step_analysis,
        "verdict":            "FAIL" if violation else "PASS"
    }


def validate_event_chain_order(event_chain: list, rules: list) -> list:
    """
    Validate that events in the chain follow ISO 26262 ordering rules.
    Rules format: {"rule": "sense BEFORE decide", "applies_to": [...]}
    
    Returns list of rule violations found.
    """
    violations = []
    chain_names = [e.lower().replace(" ", "_") for e in event_chain]

    for rule in rules:
        rule_text = rule.get("rule", "")

        # Parse "A BEFORE B" rules
        if "BEFORE" in rule_text:
            parts = rule_text.split("BEFORE")
            a = parts[0].strip().lower().replace(" ", "_")
            b = parts[1].strip().lower().replace(" ", "_")

            idx_a = next((i for i, s in enumerate(chain_names) if a in s), None)
            idx_b = next((i for i, s in enumerate(chain_names) if b in s), None)

            if idx_a is not None and idx_b is not None:
                if idx_a >= idx_b:
                    violations.append({
                        "rule_id":   rule.get("rule_id", "unknown"),
                        "rule":      rule_text,
                        "violation": f"'{a}' (pos {idx_a}) is NOT before '{b}' (pos {idx_b})"
                    })

        # Parse "A NOT AFTER B" rules
        elif "NOT AFTER" in rule_text:
            parts = rule_text.split("NOT AFTER")
            a = parts[0].strip().lower().replace(" ", "_")
            b = parts[1].strip().lower().replace(" ", "_")

            idx_a = next((i for i, s in enumerate(chain_names) if a in s), None)
            idx_b = next((i for i, s in enumerate(chain_names) if b in s), None)

            if idx_a is not None and idx_b is not None:
                if idx_a > idx_b:
                    violations.append({
                        "rule_id":   rule.get("rule_id", "unknown"),
                        "rule":      rule_text,
                        "violation": f"'{a}' occurs AFTER '{b}' — ISO violation"
                    })

    return violations


def llm_diagnose_violation(
    actual_ms: int,
    expected_ms: int,
    event_chain: list,
    context: dict
) -> str:
    """
    Use GenAI to generate a human-readable diagnosis of a timing violation.
    Includes root cause analysis and recommendation.
    """
    prompt = f"""
You are an automotive functional safety engineer.
A timing violation has been detected in an SDV safety system.

Timing:
- Expected max latency: {expected_ms} ms
- Actual latency: {actual_ms} ms
- Overshoot: {actual_ms - expected_ms} ms ({round((actual_ms/expected_ms - 1)*100, 1)}% over)

Event chain: {' → '.join(event_chain)}

Context:
- Component: {context.get('component', 'unknown')}
- Road condition: {context.get('road_condition', 'unknown')}
- ECU CPU load: {context.get('ecu_cpu_load_pct', 'unknown')}%
- Risk level: {context.get('risk_level', 'unknown')}

Provide a concise technical diagnosis (3 sentences max):
1. Most likely root cause of the timing violation
2. Safety consequence if this occurs in production
3. One specific technical fix

Plain text only. No markdown.
"""
    return query_llm(prompt, temperature=0.3)


def validate_runtime_trace(trace: dict, iso_rules: list = None) -> dict:
    """
    Validate a full runtime trace (from datasets/runtime_traces/).
    Used for scenario-based testing against pre-recorded traces.
    """
    actual  = trace.get("actual_delays", {}).get("total_ms", 0)
    expected_breakdown = trace.get("expected_delays", {})
    expected = expected_breakdown.get("total_ms", 100)
    chain_timing = trace.get("event_chain_timing", [])
    event_chain  = trace.get("events", [])

    # Core timing validation
    result = validate_timing(expected, actual, chain_timing)
    result["scenario_id"]   = trace.get("scenario_id")
    result["scenario_name"] = trace.get("name")

    # Event chain order validation
    if iso_rules:
        order_violations = validate_event_chain_order(event_chain, iso_rules)
        result["chain_order_violations"] = order_violations
    else:
        result["chain_order_violations"] = []

    return result


# ──────────────────────────────────────────────────────────────────────
# CLI test
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test with scenario trace
    import os, sys

    trace_path = "datasets/runtime_traces/scenario_1_trace.json"
    if len(sys.argv) > 1:
        trace_path = sys.argv[1]

    if os.path.exists(trace_path):
        with open(trace_path) as f:
            trace = json.load(f)
        print(f"\n[TemporalValidator] Validating: {trace_path}")
        result = validate_runtime_trace(trace)
        print(json.dumps(result, indent=2))
    else:
        # Quick inline test
        print("[TemporalValidator] Quick test:")
        result = validate_timing(100, 145, [
            {"step": "sense",   "time_ms": 12},
            {"step": "detect",  "time_ms": 55},
            {"step": "decide",  "time_ms": 95},
            {"step": "actuate", "time_ms": 145},
        ])
        print(json.dumps(result, indent=2))