"""
Agent 1: Safety Reasoning Agent (FIXED VERSION)
"""

import json
from parser import parse_requirement
from scenario_generator import generate_all_scenarios
from reasoning_engine import (
    evaluate_all_scenarios,
    generate_all_threats,
    generate_explanation,
    decide_next_action
)
from memory import AgentMemory

# 🔥 NEW IMPORT
from timing_extractor import extract_timing_from_requirement
MAX_ITERATIONS = 3


def print_header(title: str, width: int = 60):
    print(f"\n{'═'*width}")
    print(f"  {title}")
    print(f"{'═'*width}")


def print_section(step: str, title: str):
    print(f"\n{'─'*55}")
    print(f"  {step}  {title}")
    print(f"{'─'*55}")


def run_agent(requirement: str) -> dict:
    memory = AgentMemory()

    print_header(" Agent 1 — SDV Safety Reasoning Agent")
    print(f"  Requirement : {requirement}")

    # ─────────────────────────────────────────────
    # STEP 1 — PARSE + TIMING EXTRACTION (FIXED)
    # ─────────────────────────────────────────────
    print_section(" STEP 1:", "Temporal Intelligence — Parsing Requirement (GenAI)")

    # 1. Parse structure
    parsed = parse_requirement(requirement)

    # 2. Extract timing (NEW)
    
    timing = extract_timing_from_requirement(requirement)

    # 3. Inject timing into parsed (CRITICAL FIX)
    parsed["max_delay_ms"] = timing.get("total_latency_ms", 100)

    # PRINT
    print(f"  Event        : {parsed.get('event')}")
    print(f"  Max Delay    : {parsed.get('max_delay_ms')} ms")
    print(f"  Trigger      : {parsed.get('trigger')}")
    print(f"  Component    : {parsed.get('component')}")
    print(f"  ISO Standard : {parsed.get('iso_standard')}")
    print(f"  Event Chain  : {' → '.join(parsed.get('event_chain', []))}")

    all_scenarios = []
    all_evaluations = []
    all_threats = []
    iteration_logs = []

    # ─────────────────────────────────────────────
    # AGENT LOOP
    # ─────────────────────────────────────────────
    for iteration in range(1, MAX_ITERATIONS + 1):

        print(f"   AGENTIC LOOP — Iteration {iteration} / {MAX_ITERATIONS}")

        # STEP 2 — SCENARIOS
        print_section(" STEP 2:", "Real-Time Scenario Generation (GenAI)")
        scenarios = generate_all_scenarios(parsed, memory.get_history())

        if not scenarios:
            print("    No scenarios generated.")
            continue

        # STEP 3 — VALIDATION
        print_section(" STEP 3:", "Real-Time Validation — Expected vs Actual Delay")

        evaluations = evaluate_all_scenarios(parsed, scenarios)

        for s, e in zip(scenarios, evaluations):
            status = "VIOLATION" if e["violation"] else "PASS"

            print(
                f"  [{s['type'].upper():6}] "
                f"{e['actual_delay_ms']}ms / {e['expected_delay_ms']}ms "
                f"risk={e['risk_score']} → {status}"
            )

        # STEP 4 — THREATS
        print_section(" STEP 4:", "GenAI Threat Reasoning")

        threats = generate_all_threats(parsed, scenarios, evaluations)

        for s, t in zip(scenarios, threats):
            print(f"  [{s['type']}] severity={t.get('severity')}")

        # MEMORY
        memory.store_batch(scenarios, evaluations, threats)

        all_scenarios.extend(scenarios)
        all_evaluations.extend(evaluations)
        all_threats.extend(threats)

        # STEP 5 — NEXT ACTION
        print_section(" STEP 5:", "Agent Decision")

        next_action = decide_next_action(
            parsed,
            evaluations,
            threats,
            memory.get_history()
        )

        print(f"   Next Action: {next_action.get('next_action')}")

        iteration_logs.append({
            "iteration": iteration,
            "next_action": next_action
        })

        if not next_action.get("should_continue", True):
            break

    # STEP 6 — EXPLANATION
    print_section(" STEP 6:", "Final Explanation")

    explanation = generate_explanation(
        parsed,
        all_scenarios,
        all_evaluations,
        all_threats,
        memory.get_history()
    )

    print(f"\n   {explanation}")

    # FINAL OUTPUT
    output = {
        "requirement": requirement,
        "max_delay_ms": parsed.get("max_delay_ms"),
        "event_chain": parsed.get("event_chain"),
        "scenarios": all_scenarios,
        "evaluations": all_evaluations,
        "threats": all_threats,
        "explanation": explanation
    }

    print_header(" FINAL OUTPUT")
    print(json.dumps(output, indent=2))

    return output


if __name__ == "__main__":
    req = input("Enter requirement: ").strip()
    if not req:
        req = "Brake within 100ms if obstacle detected"

    run_agent(req)