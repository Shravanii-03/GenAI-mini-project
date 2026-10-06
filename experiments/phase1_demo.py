"""
Phase 1 demo: latency emerges from the emulated chain and maps to a hazard.

    python experiments/phase1_demo.py
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.runner import run_once
from sdv.schemas import Scenario

N = 300
LIMIT_MS = 100.0   # assumed requirement, not an ISO quotation


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def latency_by_load():
    print(f"\n1) End-to-end latency vs ECU CPU load ({N} seeded runs each)")
    print(f"{'load':>5} {'mean':>7} {'p95':>7} {'max':>7} {'>100ms':>8}   dominant stage")
    for load in (0.1, 0.3, 0.5, 0.7, 0.9):
        runs = [run_once(Scenario(cpu_load=load), seed=i) for i in range(N)]
        lat = [r.e2e_latency_ms for r in runs]
        stage_means = {
            k: statistics.mean(r.stage_ms[k] for r in runs) for k in runs[0].stage_ms
        }
        top = max(stage_means, key=stage_means.get)
        over = sum(x > LIMIT_MS for x in lat) / N
        print(f"{load:>5.1f} {statistics.mean(lat):>7.1f} {pct(lat, .95):>7.1f} "
              f"{max(lat):>7.1f} {over:>7.0%}   {top} ({stage_means[top]:.0f} ms)")


def hazard_vs_distance():
    print(f"\n2) Same latency, different obstacle distance (60 km/h, dry, load 0.7)")
    print(f"{'d0 (m)':>7} {'safe limit':>11} {'mean lat':>9} {'collisions':>11}")
    for d0 in (19.0, 19.5, 20.0, 20.5, 21.0, 22.0):
        s = Scenario(v0_kmh=60, d0_m=d0, cpu_load=0.7)
        runs = [run_once(s, seed=i) for i in range(N)]
        hit = sum(r.outcome.collision for r in runs) / N
        print(f"{d0:>7.1f} {runs[0].latest_safe_latency_ms:>9.0f}ms "
              f"{statistics.mean(r.e2e_latency_ms for r in runs):>7.0f}ms {hit:>10.0%}")


def one_run():
    r = run_once(Scenario(v0_kmh=60, d0_m=26, cpu_load=0.7), seed=1)
    print("\n3) One run, stage breakdown (ms)")
    for k, v in r.stage_ms.items():
        print(f"   {k:<11} {v:6.2f}")
    print(f"   {'TOTAL':<11} {r.e2e_latency_ms:6.2f}   point of no return: {r.latest_safe_latency_ms:.1f} ms"
          f"   margin: {r.margin_ms:+.1f} ms   collision: {r.outcome.collision}")


if __name__ == "__main__":
    latency_by_load()
    hazard_vs_distance()
    one_run()
