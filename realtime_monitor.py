"""
realtime_monitor.py — REAL-TIME SDV SAFETY MONITOR
====================================================
✔ 50ms tick loop — vehicle simulator → attack injector → validation → GenAI
✔ RAG context fed into every LLM call (not just retrieved and ignored)
✔ GenAI triggered ONLY on violation or attack (not every tick)
✔ Memory + RL updated after each violation
✔ Saves ONE rolling output file (live_latest.json) + one per violation
✔ outputs/ directory auto-created
✔ Clean console output — not spammy

Run:
    python realtime_monitor.py
    python realtime_monitor.py --requirement "Brake within 100ms if obstacle detected"
"""

import os
import time
import json
import argparse
from datetime import datetime

from parser import parse_requirement
from timing_extractor import extract_timing_from_requirement
from reasoning_engine import evaluate_scenario, generate_threat_reasoning
from rag_engine import get_context_for_llm, load_attack_patterns
from memory import AgentMemory
from simulator_rl import run_simulation
from vehicle_simulator import VehicleSimulator
from attack_injector import inject_attack
from rag_engine import get_iso_rule_for_component

# ── Config ────────────────────────────────────────────────────────────────────
TICK_INTERVAL    = 0.5       # 500ms — 10x slower, RL learns properly
SAVE_LATEST_EVERY = 5        # save live_latest.json every N ticks (for dashboard)
GENAI_COOLDOWN   = 5        # min ticks between GenAI calls (avoid API spam)
MAX_VIOLATION_FILES = 100    # cap violation files so outputs/ doesn't explode


# ── Output dir ────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Console helpers ───────────────────────────────────────────────────────────
def _bar(value, max_val, width=20, fill="█", empty="░"):
    filled = int(width * min(value, max_val) / max_val)
    return fill * filled + empty * (width - filled)

def _print_tick(tick, frame, evaluation, attacked):
    delay  = evaluation["actual_delay_ms"]
    risk   = evaluation["risk_score"]
    sev    = evaluation["severity"]
    phase  = frame.get("driving_phase", "?")
    speed  = frame.get("vehicle_speed", 0)
    limit  = frame.get("brake_asil_limit_ms", 100)
    viol   = " VIOLATION" if evaluation["violation"] else " OK"
    atk    = f" | ⚡{frame.get('attack',{}).get('type','').upper()}" if attacked else ""

    color_sev = {"CRITICAL":"🔴","HIGH":"🟠","MEDIUM":"🟡","LOW":"🟢"}.get(sev,"⚪")

    print(
        f"[{tick:5d}] {phase:<22} "
        f"spd={speed:5.1f}km/h  "
        f"delay={delay:4d}ms/{limit}ms {_bar(delay,limit,10)}  "
        f"risk={risk:.3f} {color_sev}{sev:<8} "
        f"{viol}{atk}"
    )


# ── Save helpers ──────────────────────────────────────────────────────────────
def _save_latest(tick, frame, evaluation, threat=None):
    """Overwrite a single rolling file — dashboard reads this."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "tick": tick,
        "frame": frame,
        "evaluation": evaluation,
        "threat": threat,
    }
    path = os.path.join(OUTPUT_DIR, "live_latest.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _save_violation(tick, frame, evaluation, threat, viol_count):
    """Save individual violation file — capped at MAX_VIOLATION_FILES."""
    if viol_count > MAX_VIOLATION_FILES:
        return
    ts   = datetime.now().strftime("%H%M%S_%f")[:10]
    path = os.path.join(OUTPUT_DIR, f"live_violation_{ts}.json")
    data = {
        "timestamp": datetime.now().isoformat(),
        "tick": tick,
        "frame": frame,
        "evaluation": evaluation,
        "threat": threat,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"    Saved → {os.path.basename(path)}")


# ── Main ──────────────────────────────────────────────────────────────────────
def run_monitor(requirement: str):

    # ── Step 1: Parse requirement ─────────────────────────────────────────────
    parsed = parse_requirement(requirement)
    timing = extract_timing_from_requirement(requirement)
    parsed["max_delay_ms"] = timing.get("total_latency_ms", 100)

    print("\n" + "═"*60)
    print("  REAL-TIME SDV SAFETY MONITOR")
    print("═"*60)
    print(f"  Requirement  : {requirement}")
    print(f"  Event        : {parsed.get('event','?')}")
    print(f"  Component    : {parsed.get('component','?')}")
    print(f"  Max Delay    : {parsed['max_delay_ms']} ms (ASIL-D)")
    print(f"  ISO Standard : {parsed.get('iso_standard','ISO 26262')}")
    print(f"  Output dir   : {OUTPUT_DIR}")
    print("═"*60 + "\n")

    # ── Step 2: Pre-load RAG context (once, reused every tick) ───────────────
    rag_query   = f"{parsed.get('event','')} {parsed.get('component','')} timing"
    rag_context = get_context_for_llm(rag_query)
    print("  [RAG] Knowledge base loaded:")
    print("  " + "\n  ".join(rag_context.splitlines()[:6]) + "\n")

    # ── Step 3: Init modules ──────────────────────────────────────────────────
    simulator = VehicleSimulator(loop_scenarios=True)
    memory    = AgentMemory()

    tick            = 0
    genai_cooldown  = 0       # ticks since last GenAI call
    violation_count = 0
    attack_count    = 0
    current_delay   = parsed["max_delay_ms"]   # RL starting point

    print(f"  {'TICK':<7} {'PHASE':<22} {'SPEED':<12} {'DELAY':<18} {'RISK':<14} STATUS")
    print("  " + "─"*90)

    try:
        while True:
            tick         += 1
            genai_cooldown = max(0, genai_cooldown - 1)

            # ── 1. Get vehicle frame ──────────────────────────────────────────
            frame = simulator.tick()

            # ── 2. Inject attack ──────────────────────────────────────────────
            frame    = inject_attack(frame)
            attacked = frame.get("attack", {}).get("active", False)
            if attacked:
                attack_count += 1

            # ── 3. Build scenario dict ────────────────────────────────────────
            scenario = {
                "actual_delay_ms":   frame.get("delay_ms", 0),
                "type":              frame.get("mode", "normal"),
                "parameters": {
                    "road_condition":    frame.get("road_condition", "dry"),
                    "ecu_cpu_load_pct":  frame.get("cpu_load", 50),
                },
                "event_chain_timing": frame.get("event_chain", []),
            }

            # ── 4. Fast validation (no LLM, instant) ─────────────────────────
            evaluation = evaluate_scenario(parsed, scenario)

            # Print every tick (compact)
            _print_tick(tick, frame, evaluation, attacked)

            # ── 5. Trigger GenAI only on violation or attack ──────────────────
            threat = None
            should_genai = (
                (evaluation["violation"] or attacked)
                and genai_cooldown == 0
            )

            if should_genai:
                genai_cooldown  = GENAI_COOLDOWN
                violation_count += 1

                print(f"\n  {'─'*55}")
                print(f"    SAFETY EVENT — GenAI reasoning triggered")
                print(f"  {'─'*55}")
                if attacked:
                    atk_info = frame.get("attack", {})
                    print(f"  Attack : {atk_info.get('type','?').upper()} — {atk_info.get('description','')}")
                if evaluation["violation"]:
                   component = parsed.get("component", "").lower()

                   if "brake" in component:
                       component_query = "braking_system"
                   elif "steer" in component:
                       component_query = "steering_ecu"
                   else:
                       component_query = component

                   iso_rule = get_iso_rule_for_component(component_query)

                   if iso_rule:
                        print(f"  ISO    : {iso_rule.get('rule_id')}  ({iso_rule.get('max_latency_ms')}ms)")
                   else:
                       print("  ISO    : ISO 26262 (generic)")
                if evaluation["actual_delay_ms"] > parsed["max_delay_ms"]:
                   print(f"  Delay  : {evaluation['actual_delay_ms']}ms > {parsed['max_delay_ms']}ms limit")
                else:
                   print(f"  Delay  : {evaluation['actual_delay_ms']}ms / {parsed['max_delay_ms']}ms (within limit)")
                print(f"  Risk   : {evaluation['risk_score']} ({evaluation['severity']})")

                #  GenAI threat reasoning — RAG context already in prompt via rag_enriched_query
                threat = generate_threat_reasoning(parsed, scenario, evaluation)

                print(f"\n  🔴 THREAT:")
                print(f"     Severity   : {threat.get('severity','?')}")
                print(f"     Chain      : {' → '.join(threat.get('attack_chain', [])[:4])}")
                print(f"     Mitigation : {threat.get('mitigation','?')}")
                print(f"  {'─'*55}\n")

                # ── 6. Update memory ──────────────────────────────────────────
                memory.store(scenario, evaluation, threat)

                # ── 7. RL update — learn from real violation ──────────────────
                rl_result    = run_simulation({
                    "delay":           evaluation["actual_delay_ms"],
                    "max_delay":       parsed["max_delay_ms"],
                    "road_condition":  frame.get("road_condition", "dry"),
                    "cpu_load":        frame.get("cpu_load", 50),
                    "violation":       evaluation["violation"],
                    "risk_score":      evaluation["risk_score"],
                    "attacked":        attacked,
                })
                current_delay = rl_result["next_delay"]
                # ADD THIS:
                print(f"     RL: action={rl_result['rl_action_ms']:+d}ms  reward={rl_result['rl_reward']:+.2f}  ε={rl_result['rl_epsilon']:.3f}  Q-states={rl_result['rl_q_states']}")

                # Save violation file
                _save_violation(tick, frame, evaluation, threat, violation_count)

            # ── 8. Save rolling latest (dashboard reads this) ─────────────────
            if tick % SAVE_LATEST_EVERY == 0:
                _save_latest(tick, frame, evaluation, threat)

            # ── 9. Print summary every 100 ticks (~5 seconds) ────────────────
            if tick % 100 == 0:
                mem_sum = memory.summary()
                print(f"\n  {'═'*55}")
                print(f"   SUMMARY  tick={tick}  t={tick*0.05:.1f}s")
                print(f"     Violations : {violation_count}")
                print(f"     Attacks    : {attack_count}")
                if mem_sum:
                    print(f"     Avg Risk   : {mem_sum.get('avg_risk_score','?')}")
                    print(f"     Critical   : {mem_sum.get('critical_violations','?')}")
                print(f"  {'═'*55}\n")

            # ── 50ms sleep ────────────────────────────────────────────────────
            time.sleep(TICK_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n  Monitor stopped by user.")
        mem_sum = memory.summary()
        if mem_sum:
            print(f"\n  FINAL SUMMARY:")
            print(f"  Total ticks      : {tick}")
            print(f"  Violations       : {violation_count}")
            print(f"  Attacks          : {attack_count}")
            print(f"  Avg risk         : {mem_sum.get('avg_risk_score','?')}")
            print(f"  Critical events  : {mem_sum.get('critical_violations','?')}")
            print(f"  Output dir       : {OUTPUT_DIR}")


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="SDV Real-Time Safety Monitor")
    ap.add_argument("--requirement", "-r", type=str, default="",
                    help="Safety requirement (skips prompt if provided)")
    args = ap.parse_args()

    req = args.requirement.strip()
    if not req:
        req = input("Enter safety requirement: ").strip()
    if not req:
        req = "Brake within 100ms if obstacle detected"

    run_monitor(req)


if __name__ == "__main__":
    main()