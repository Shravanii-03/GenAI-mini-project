"""
E8: do the emulation findings show up on REAL attacks? (ROAD dataset, Oak Ridge National Laboratory)

  * learn what normal looks like from some normal captures (never from attacks)
  * keep only rules that raise (almost) no false alarms on held-out normal captures, including
    real-road driving (selection never sees an attack, so attack results are out-of-sample)
  * then replay the attack captures and measure whether and how fast each detector family fires

Detector families (all semantics-free; ROAD signals are anonymised):
  rate   frame-rate / timing IDS on arbitration IDs
  range  a signal leaves the interval seen in normal driving
  jump   a signal changes by more than ever seen in one step
  pair   two signals that move together in normal driving disagree (redundancy cross-check)

Masquerade captures replace genuine frames, so the frame rate is unchanged; fabrication captures
add frames. The raw logs of the fabrication variants are used for the rate IDS only.

    python experiments/e8_road_validation.py            # needs ROAD (see sdv/realdata/road.py)
"""
import argparse
import collections
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.realdata import road
from sdv.realdata.detectors import RateIDS, learn_jumps, learn_pairs, learn_ranges

TRAIN = ["ambient_dyno_drive_basic_short", "ambient_dyno_drive_extended_long", "ambient_dyno_drive_extended_short",
         "ambient_dyno_drive_radio_infotainment", "ambient_dyno_drive_winter",
         "ambient_dyno_idle_radio_infotainment", "ambient_dyno_drive_basic_long"]
VALID = ["ambient_dyno_drive_benign_anomaly", "ambient_dyno_reverse",
         "ambient_highway_street_driving_diagnostics", "ambient_highway_street_driving_long"]
EXCLUDED = ["ambient_dyno_exercise_all_bits"]       # deliberately toggles every bit: not normal behaviour
DEADLINES_MS = (100, 250, 500, 1000)


def family_of(name):
    for key in ("correlated_signal", "max_speedometer", "max_engine_coolant", "reverse_light_off",
                "reverse_light_on", "accelerator_attack_drive", "accelerator_attack_reverse", "fuzzing"):
        if name.startswith(key):
            return key
    return name


def log(msg):
    print(msg, flush=True)


def fa_events(rule_or_ids, cap):
    alarms = rule_or_ids.alarms(cap.t, cap.ids) if isinstance(rule_or_ids, RateIDS) else rule_or_ids.alarms(cap)
    return road.merge_events(alarms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fa-per-hour", type=float, default=2.0,
                    help="false-alarm budget for the frame-rate IDS tuning (events/hour on held-out normal data)")
    ap.add_argument("--valid-seconds", type=float, default=1800, help="cap on the long road validation capture")
    ap.add_argument("--cache", default=None)
    args = ap.parse_args()
    if not road.available():
        print("ROAD data not found; set ROAD_DIR (see sdv/realdata/road.py).")
        return 1
    cache = args.cache or str(road.road_dir().parent.parent / "cache")
    start = time.time()

    log("loading normal captures ...")
    train = [road.load_signal_csv(road.signal_path("ambient", n), cache) for n in TRAIN]
    valid = [road.load_signal_csv(road.signal_path("ambient", n), cache, max_seconds=args.valid_seconds)
             for n in VALID]
    log(f"  train {sum(c.duration for c in train):.0f}s in {len(train)} captures; "
        f"validation {sum(c.duration for c in valid):.0f}s in {len(valid)} captures "
        f"({sum(c.duration for c in valid if 'highway' in c.name):.0f}s on a real road); {time.time() - start:.0f}s")

    log("learning candidate rules from the training captures ...")
    candidates = {"range": learn_ranges(train), "jump": learn_jumps(train),
                  "pair": learn_pairs(train, r_min=0.999)}
    rate = RateIDS().learn([(c.t, c.ids) for c in train])
    log("  candidates: " + ", ".join(f"{k} {len(v)}" for k, v in candidates.items())
        + f", rate IDS on {len(rate.period)} periodic IDs; {time.time() - start:.0f}s")

    valid_hours = sum(c.duration for c in valid) / 3600
    budget = max(1, int(args.fa_per_hour * valid_hours))
    log(f"selecting signal rules with ZERO false alarms on the held-out normal captures ({valid_hours:.2f} h) ...")
    accepted = {}
    for family, rules in candidates.items():
        accepted[family] = [r for r in rules if sum(len(fa_events(r, c)) for c in valid) == 0]

    # Fair baseline: tune the frame-rate IDS (most sensitive setting within the false-alarm budget)
    tuned = None
    for gap_ratio in (3.0, 4.0, 6.0, 10.0, 20.0, 50.0):
        for short_ratio in (0.5, 0.4, 0.3, 0.2, 0.1, 0.05):
            rate.short_ratio, rate.gap_ratio = short_ratio, gap_ratio
            if sum(len(fa_events(rate, c)) for c in valid) <= budget:
                tuned = (short_ratio, gap_ratio)
                break
        if tuned:
            break
    if tuned is None:
        rate.short_ratio, rate.gap_ratio = 0.05, 50.0
    rate_fa = sum(len(fa_events(rate, c)) for c in valid)
    log("  accepted: " + ", ".join(f"{k} {len(accepted[k])}/{len(candidates[k])}" for k in candidates)
        + f"; rate IDS tuned to short<{rate.short_ratio}x, gap>{rate.gap_ratio}x period: "
        f"{rate_fa} false-alarm event(s) on validation ({rate_fa / valid_hours:.1f}/h)")
    fused_fa = sum(len(road.merge_events(np.concatenate(
        [r.alarms(c) for fam in accepted for r in accepted[fam]] + [np.empty(0)]))) for c in valid)
    log(f"  fused (all accepted signal rules) false-alarm events on validation: {fused_fa} "
        f"({fused_fa / valid_hours:.2f}/h)")

    meta = road.attack_metadata()
    rows = []
    for name, info in sorted(meta.items()):
        path = road.signal_path("attacks", name)
        if not path.exists() or not info.get("injection_interval"):
            if path.exists():
                log(f"  skipped {name}: injection started before the capture, no onset time")
            continue
        cap = road.load_signal_csv(path, cache)
        t0, t1 = info["injection_interval"]
        out = {"name": name, "family": family_of(name), "masq": name.endswith("_masquerade"), "start": t0}
        for fam in candidates:
            alarms = np.concatenate([r.alarms(cap) for r in accepted[fam]] + [np.empty(0)])
            out[fam] = alarms
        out["rate"] = rate.alarms(cap.t, cap.ids)
        out["fused_signal"] = np.concatenate([out[f] for f in candidates])
        rows.append(out)
    log(f"replayed {len(rows)} attack captures; {time.time() - start:.0f}s")

    def first_delay(alarms, t0):
        late = alarms[alarms >= t0 - 1e-9]
        return float(late.min() - t0) * 1000 if len(late) else None

    detectors = ["rate", "range", "jump", "pair", "fused_signal"]
    print("\nDetection delay after injection start, per attack family "
          "(masquerade captures: frames are replaced, so the frame rate is unchanged)")
    print(f"{'attack family':<28}{'n':>3}" + "".join(f"{d:>20}" for d in detectors))
    by_family = collections.defaultdict(list)
    for r in rows:
        by_family[r["family"]].append(r)
    for fam, group in sorted(by_family.items()):
        line = f"{fam:<28}{len(group):>3}"
        for d in detectors:
            delays = [first_delay(r[d], r["start"]) for r in group]
            hit = [x for x in delays if x is not None]
            med = f"{statistics.median(hit):.0f}ms" if hit else "-"
            line += f"{len(hit)}/{len(group)} med {med:>8}".rjust(20)
        print(line)

    print("\nShare of attack captures detected within a deadline (all families pooled)")
    print(f"{'detector':<16}" + "".join(f"{f'<= {d} ms':>11}" for d in DEADLINES_MS) + f"{'ever':>9}")
    for d in detectors:
        delays = [first_delay(r[d], r["start"]) for r in rows]
        line = f"{d:<16}"
        for dl in DEADLINES_MS:
            line += f"{sum(x is not None and x <= dl for x in delays) / len(rows):>11.2f}"
        line += f"{sum(x is not None for x in delays) / len(rows):>9.2f}"
        print(line)

    print("\nFalse alarms inside the attack captures before the injection starts (normal portion, events)")
    pre = {d: sum(len(road.merge_events(r[d][r[d] < r["start"]])) for r in rows) for d in detectors}
    secs = sum(r["start"] for r in rows)
    print("  " + ", ".join(f"{d} {n}" for d, n in pre.items()) + f"   over {secs:.0f}s of normal driving")

    print("\nFabrication variants (extra frames injected), raw logs, rate IDS only")
    fab = []
    for name, info in sorted(meta.items()):
        if name.endswith("_masquerade") or "fuzzing" in name or "accelerator" in name \
                or not info.get("injection_interval"):
            continue
        p = road.raw_path("attacks", name)
        if not p.exists():
            continue
        t, ids = road.load_raw_log(p)
        alarms = rate.alarms(t, ids)
        fab.append((family_of(name), first_delay(alarms, info["injection_interval"][0])))
    for fam in sorted({f for f, _ in fab}):
        d = [x for f, x in fab if f == fam]
        hit = [x for x in d if x is not None]
        print(f"  {fam:<24} detected {len(hit)}/{len(d)}" + (f", median delay {statistics.median(hit):.0f} ms" if hit else ""))
    print(f"\ntotal time {time.time() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
