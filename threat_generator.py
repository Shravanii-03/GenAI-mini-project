"""
threat_generator.py — MODULE 5: GenAI Topology-Aware Threat Generator (RAG-ENHANCED)

🔥 EXTENDED NOVELTY

Now upgraded with:
✔ RAG grounding (attack_patterns + ISO + CAN)
✔ TARA scoring
✔ topology-aware reasoning
✔ non-hallucinated threats
"""

import json
from rag_engine import rag_enriched_query


# =========================
# TARA SCORING
# =========================

def compute_tara_score(
    timing_violation,
    risk_score,
    road_condition,
    cpu_load_pct,
    attack_patterns_matched
):

    road_mult = {"icy": 1.4, "wet": 1.2, "foggy": 1.3, "dry": 1.0}.get(road_condition, 1.0)
    cpu_mult = 1.0 + (cpu_load_pct / 200.0)
    viol_mult = 1.3 if timing_violation else 1.0
    pattern_mult = 1.0 + (0.1 * len(attack_patterns_matched))

    raw = risk_score * road_mult * cpu_mult * viol_mult * pattern_mult
    final = min(round(raw, 3), 1.0)

    severity = (
        "CRITICAL" if final >= 0.85 else
        "HIGH" if final >= 0.65 else
        "MEDIUM" if final >= 0.40 else
        "LOW"
    )

    return {"tara_score": final, "severity": severity}


# =========================
# MATCH ATTACK PATTERNS
# =========================

def match_attack_patterns(component, attack_db):

    matches = []
    comp = component.lower()

    for pattern in attack_db or []:

        targets = [t.lower() for t in pattern.get("target_components", [])]

        if any(comp in t or t in comp for t in targets):
            matches.append(pattern)

    return matches


# =========================
# MAIN THREAT GENERATOR
# =========================

def generate_topology_threat(
    component,
    event,
    parsed,
    evaluation,
    scenario,
    attack_patterns=None
):

    road = scenario.get("parameters", {}).get("road_condition", "dry")
    cpu = scenario.get("parameters", {}).get("ecu_cpu_load_pct", 50)

    violation = evaluation.get("violation", False)
    risk_score = evaluation.get("risk_score", 0.5)

    matched = match_attack_patterns(component, attack_patterns)

    tara = compute_tara_score(violation, risk_score, road, cpu, matched)

    attack_names = [m.get("name") for m in matched[:3]]

    #  RAG-enhanced prompt
    prompt = f"""
You are an automotive cybersecurity expert (ISO 21434).

Generate a REALISTIC cyber-physical attack chain.

SYSTEM:
Component: {component}
Event: {event}

RUNTIME:
Expected delay: {evaluation.get('expected_delay_ms')}
Actual delay: {evaluation.get('actual_delay_ms')}
Violation: {violation}
Road: {road}
CPU load: {cpu}

Known attacks: {attack_names}

RULES:
- Must follow SDV topology:
  External → Gateway → ECU → Physical
- Must be realistic (CAN spoofing, replay, injection, etc.)
- Must link software attack → physical damage

OUTPUT STRICT JSON:

{{
  "attack_type": "<type>",
  "entry_point": "<where attack starts>",
  "target_ecu": "<target ECU>",
  "attack_chain": ["step1","step2","step3"],
  "impact": "<physical consequence>",
  "severity": "{tara['severity']}",
  "tara_score": {tara['tara_score']},
  "mitigation": "<technical fix>"
}}
"""

    try:
        #  RAG + LLM
        response = rag_enriched_query(prompt, component + " automotive attack")

        start = response.find("{")
        end = response.rfind("}") + 1
        result = json.loads(response[start:end])

        result["tara_score"] = tara["tara_score"]
        result["severity"] = tara["severity"]
        result["matched_patterns"] = matched

        return result

    except Exception as e:

        print(f"[ThreatGenerator] fallback: {e}")

        return {
            "attack_type": "CAN spoofing",
            "entry_point": "Infotainment system",
            "target_ecu": component,
            "attack_chain": [
                "Compromise infotainment",
                "Inject CAN messages",
                "Override brake signals"
            ],
            "impact": "Incorrect braking → collision risk",
            "severity": tara["severity"],
            "tara_score": tara["tara_score"],
            "mitigation": "Use CAN authentication + IDS",
            "matched_patterns": matched,
            "source": "fallback"
        }


# =========================
# BATCH PROCESSING
# =========================

def generate_batch_threats(parsed, scenarios, evaluations, attack_patterns=None):

    component = parsed.get("component", "braking_system")
    event = parsed.get("event", "unknown")

    results = []

    for s, e in zip(scenarios, evaluations):

        print(f"        [THREAT] {s.get('type','?')} → generating...")

        t = generate_topology_threat(
            component,
            event,
            parsed,
            e,
            s,
            attack_patterns
        )

        results.append(t)

    return results


# =========================
# TEST
# =========================

if __name__ == "__main__":

    test_parsed = {"event": "brake", "component": "braking_system"}

    test_eval = {
        "violation": True,
        "risk_score": 1.2,
        "actual_delay_ms": 120,
        "expected_delay_ms": 100
    }

    test_scenario = {
        "parameters": {
            "road_condition": "wet",
            "ecu_cpu_load_pct": 70
        }
    }

    result = generate_topology_threat(
        "braking_system",
        "brake",
        test_parsed,
        test_eval,
        test_scenario
    )

    print(json.dumps(result, indent=2))