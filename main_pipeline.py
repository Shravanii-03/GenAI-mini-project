import time
import json
from datetime import datetime

from parser import parse_requirement
from timing_extractor import extract_timing_from_requirement
from reasoning_engine import evaluate_scenario, generate_threat_reasoning
from rag_engine import load_attack_patterns

from vehicle_simulator import VehicleSimulator
from attack_injector import inject_attack


# =========================
# CONFIG
# =========================

TICK_INTERVAL = 0.05  # 50 ms


# =========================
# MAIN LOOP
# =========================

def run_realtime_pipeline(requirement):

    print("\n══════════════════════════════════════")
    print(" REAL-TIME SDV SAFETY SYSTEM STARTED")
    print("══════════════════════════════════════\n")

    # -------------------------
    # STEP 1: Parse + timing
    # -------------------------

    parsed = parse_requirement(requirement)
    timing = extract_timing_from_requirement(requirement)

    parsed["max_delay_ms"] = timing.get("total_latency_ms", 100)

    print(f"Parsed Event       : {parsed['event']}")
    print(f"Max Allowed Delay  : {parsed['max_delay_ms']} ms\n")

    # -------------------------
    # STEP 2: Init simulator
    # -------------------------

    simulator = VehicleSimulator()
    attack_patterns = load_attack_patterns()

    iteration = 0

    # -------------------------
    # STEP 3: REAL-TIME LOOP
    # -------------------------

    while True:

        iteration += 1

        # 🔹 simulate vehicle state
        frame = simulator.generate_frame()

        # 🔹 inject attack randomly
        frame = inject_attack(frame)

        # 🔹 build scenario for evaluation
        scenario = {
            "actual_delay_ms": frame.get("delay_ms", 0),
            "type": frame.get("mode", "normal"),
            "parameters": {
                "road_condition": frame.get("road_condition", "dry"),
                "ecu_cpu_load_pct": frame.get("cpu_load", 50)
            },
            "event_chain_timing": frame.get("event_chain", [])
        }

        # -------------------------
        # STEP 4: FAST VALIDATION
        # -------------------------

        evaluation = evaluate_scenario(parsed, scenario)

        print(f"[Tick {iteration}] Delay={evaluation['actual_delay_ms']} ms | Risk={evaluation['risk_score']} | {evaluation['severity']}")

        # -------------------------
        # STEP 5: TRIGGER GENAI ONLY IF NEEDED
        # -------------------------

        if evaluation["violation"] or evaluation["risk_score"] > 1.1:

            print("\n⚠️  SAFETY VIOLATION DETECTED → RUNNING GENAI\n")

            threat = generate_threat_reasoning(parsed, scenario, evaluation)

            print("🔴 THREAT DETECTED:")
            print(json.dumps(threat, indent=2))

            # save output
            save_event_output(frame, evaluation, threat)

        # -------------------------
        # sleep for next tick
        # -------------------------

        time.sleep(TICK_INTERVAL)


# =========================
# SAVE OUTPUT
# =========================

def save_event_output(frame, evaluation, threat):

    output = {
        "timestamp": datetime.now().isoformat(),
        "frame": frame,
        "evaluation": evaluation,
        "threat": threat
    }

    filename = f"outputs/live_event_{int(time.time())}.json"

    with open(filename, "w") as f:
        json.dump(output, f, indent=2)

    print(f" Saved → {filename}\n")


# =========================
# ENTRY
# =========================

def main():

    requirement = input("Enter requirement: ").strip()

    if not requirement:
        requirement = "Brake within 100ms if obstacle detected"

    run_realtime_pipeline(requirement)


if __name__ == "__main__":
    main()