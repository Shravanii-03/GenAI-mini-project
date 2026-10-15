"""
Scenario Generator — GenAI + Controlled Simulation (FIXED)

Fixes:
✔ Adds controlled delay variation (normal / edge / stress)
✔ Prevents identical delays → fixes "risk always same"
✔ Adds fallback generator (no crashes)
✔ Uses RAG grounding for realism
✔ Ensures valid scenario structure ALWAYS
"""

import json
import random
from rag_engine import rag_enriched_query
from prompt_templates import get_scenario_generation_prompt


# =========================
# DELAY GENERATION LOGIC
# =========================

def generate_delay(max_delay, scenario_type):

    if scenario_type == "normal":
        return random.randint(int(0.7 * max_delay), int(1.0 * max_delay))

    elif scenario_type == "edge":
        return random.randint(int(0.9 * max_delay), int(1.2 * max_delay))

    elif scenario_type == "stress":
        return random.randint(int(1.1 * max_delay), int(1.5 * max_delay))

    return max_delay


# =========================
# FALLBACK SCENARIO
# =========================

def fallback_scenario(parsed, scenario_type):

    max_delay = parsed.get("max_delay_ms", 100)
    delay = generate_delay(max_delay, scenario_type)

    return {
        "type": scenario_type,
        "actual_delay_ms": delay,
        "parameters": {
            "road_condition": random.choice(["dry", "wet", "icy"]),
            "ecu_cpu_load_pct": random.randint(30, 90)
        },
        "event_chain_timing": [
            {"step": "sensor", "time_ms": int(delay * 0.2)},
            {"step": "perception", "time_ms": int(delay * 0.3)},
            {"step": "decision", "time_ms": int(delay * 0.2)},
            {"step": "actuator", "time_ms": int(delay * 0.3)}
        ]
    }


# =========================
# MAIN GENERATION FUNCTION
# =========================

def generate_scenario(parsed: dict, scenario_type: str, memory: list) -> dict:

    prompt = get_scenario_generation_prompt(parsed, scenario_type, memory)

    try:
        # 🔥 RAG-powered generation
        response = rag_enriched_query(prompt, parsed.get("event", ""))

        start = response.find("{")
        end = response.rfind("}") + 1
        scenario = json.loads(response[start:end])

        # =========================
        # VALIDATION + FIXES
        # =========================

        max_delay = parsed.get("max_delay_ms", 100)

        # Fix missing delay
        if "actual_delay_ms" not in scenario:
            scenario["actual_delay_ms"] = generate_delay(max_delay, scenario_type)

        # Prevent constant values
        if scenario["actual_delay_ms"] == max_delay:
            scenario["actual_delay_ms"] = generate_delay(max_delay, scenario_type)

        # Ensure type exists
        scenario["type"] = scenario_type

        # Ensure parameters exist
        if "parameters" not in scenario:
            scenario["parameters"] = {}

        scenario["parameters"].setdefault(
            "road_condition",
            random.choice(["dry", "wet", "icy"])
        )

        scenario["parameters"].setdefault(
            "ecu_cpu_load_pct",
            random.randint(30, 90)
        )

        return scenario

    except Exception as e:

        print(f"[ScenarioGenerator] fallback used ({scenario_type}): {e}")

        return fallback_scenario(parsed, scenario_type)


# =========================
# GENERATE ALL SCENARIOS
# =========================

def generate_all_scenarios(parsed: dict, memory: list) -> list:

    scenarios = []

    for scenario_type in ["normal", "edge", "stress"]:

        print(f"        [{scenario_type.upper()}] generating...")

        scenario = generate_scenario(parsed, scenario_type, memory)

        scenarios.append(scenario)

    return scenarios


# =========================
# TEST
# =========================

if __name__ == "__main__":

    parsed = {
        "event": "brake",
        "max_delay_ms": 100
    }

    scenarios = generate_all_scenarios(parsed, [])

    print("\n=== GENERATED SCENARIOS ===\n")

    for s in scenarios:
        print(json.dumps(s, indent=2))