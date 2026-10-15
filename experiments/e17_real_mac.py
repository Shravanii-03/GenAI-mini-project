"""
E17: what changes when the idealised authentication is replaced by a real truncated HMAC (sdv/security/mac.py)?

Part A  forgery acceptance: forged frames that pass the check, by MAC length, against the theoretical 2**-bits
Part B  hazard volume with authentication + watchdog, by MAC length, for the forging attacks (and the key holder)
Part C  decisions: does the 24-bit real MAC give exactly the same trigger source and outcome as the idealised mode?
Part D  side effect of the freshness counter: attacks that reorder frames also get genuine frames rejected

    python experiments/e17_real_mac.py --samples 150
"""
import argparse
import os
import random
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.attacks.library import make_attack
from sdv.metrics.stats import wilson_interval
from sdv.runner import execute
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import SENSOR_ID, ChainParams

BITS = (4, 8, 16, 24)
VARIANTS = [("masquerade", "masquerade", {}), ("dual_masquerade", "dual_masquerade", {}),
            ("dual_masquerade (holds key)", "dual_masquerade", {"holds_key": True}),
            ("sensor_drift_spoof", "sensor_drift_spoof", {})]


def chain(mode, bits=24, mitigation="radar_or"):
    return replace(ChainParams.from_config(), radar=True, mitigation=mitigation, auth=True, auth_mode=mode, mac_bits=bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=150)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    print("A. forged frames accepted by the receiver (masquerade on the primary sensor, radar_or + auth)")
    print(f"{'MAC bits':>9}{'forged frames':>15}{'accepted':>10}{'rate':>10}{'theory 2^-bits':>16}")
    for bits in BITS:
        accepted = total = 0
        for i in range(args.samples * 3):
            scenario = random_tight_scenario(random.Random(i))
            attack = make_attack("masquerade", bias_m=30.0, phase_shift_ms=0.0, start_offset_ms=0.0, duration_ms=800.0)
            _, c = execute(scenario, i, chain("hmac", bits), attacks=[attack])
            forged = sum(1 for f in c.bus.log if f.can_id == SENSOR_ID and f.data.get("forged"))
            accepted += forged - c.rejected_frames
            total += forged
        print(f"{bits:>9}{total:>15}{accepted:>10}{accepted / total:>10.4%}{2.0 ** -bits:>16.4%}")

    print(f"\nB. attack-induced hazard volume ({args.samples} sampled attacks per variant), radar failover + authentication + watchdog")
    header = f"{'attack variant':<30}{'ideal':>9}" + "".join(f"{'hmac ' + str(b):>10}" for b in BITS)
    print(header)
    same_total = same_ok = 0
    for label, family, extra in VARIANTS:
        hits = {m: 0 for m in ["ideal"] + [f"hmac{b}" for b in BITS]}
        for i in range(args.samples):
            scenario = random_tight_scenario(random.Random(args.seed * 1000 + i))
            problem = AttackSearchProblem(family, scenario)
            params = {**problem.decode(rng.random(problem.dim)), **extra}
            modes = [("ideal", chain("ideal"))] + [(f"hmac{b}", chain("hmac", b)) for b in BITS]
            outcomes = {}
            for name, ch in modes:
                attacked, co = execute(scenario, args.seed * 100_000 + i, ch, attacks=[make_attack(family, **params)])
                clean, _ = execute(scenario, args.seed * 100_000 + i, ch)
                hits[name] += attacked.outcome.collision and not clean.outcome.collision
                outcomes[name] = (attacked.outcome.collision, co.trigger_source)
            same_total += 1
            same_ok += outcomes["ideal"] == outcomes["hmac24"]
        n = args.samples
        print(f"{label:<30}{hits['ideal'] / n:>9.1%}" + "".join(f"{hits[f'hmac{b}'] / n:>10.1%}" for b in BITS))
    print(f"\nC. 24-bit real MAC vs idealised mode: identical outcome and trigger source in {same_ok}/{same_total} attacked runs")

    print("\nD. frame reordering (jitter_injection): genuine frames rejected by the freshness counter")
    rejected = runs = 0
    for i in range(args.samples):
        scenario = random_tight_scenario(random.Random(i))
        attack = make_attack("jitter_injection", delay_ms=60.0, duration_ms=400.0, start_offset_ms=0.0)
        _, c = execute(scenario, i, chain("hmac", 24), attacks=[attack])
        rejected += c.rejected_frames > 0
        runs += 1
    print(f"   runs in which at least one genuine frame was rejected: {rejected}/{runs} "
          f"(95% interval {wilson_interval(rejected, runs)[0]:.0%}-{wilson_interval(rejected, runs)[1]:.0%}); "
          "the idealised mode never rejects them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
