"""
E15: replay the authentication + silence-watchdog defence on REAL attack traffic (ROAD).

  * learn each periodic ID's period from normal driving (never from attacks)
  * false triggers: how often does the watchdog fire on held-out normal driving, including real road? (the availability
    cost of a fail-safe, which the emulator cannot know)
  * detection: on the 13 masquerade captures, frames labelled as injected fail authentication (idealised); how fast does the
    silence on the attacked ID get noticed? Compared with the same watchdog WITHOUT authentication (replacement keeps the
    frame rate, so it is blind) and with E8's semantics-free signal rules (which miss in-range forgeries)

    python experiments/e15_road_defence_replay.py            # needs ROAD (see sdv/realdata/road.py)
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


from e8_road_validation import TRAIN, VALID, family_of
from sdv.realdata import road
from sdv.realdata.watchdog import SilenceWatchdog

KS = (2.0, 3.0, 5.0, 10.0)
MIN_S = 0.03            # the emulator's watchdog floor


def main():
    if not road.available():
        print("ROAD data not found; set ROAD_DIR (see sdv/realdata/road.py).")
        return 1
    start = time.time()
    cache = str(road.road_dir().parent.parent / "cache")
    train = [road.load_signal_csv(road.signal_path("ambient", n), cache) for n in TRAIN]
    valid = [road.load_signal_csv(road.signal_path("ambient", n), cache, max_seconds=1800) for n in VALID]
    hours = sum(c.duration for c in valid) / 3600
    road_s = sum(c.duration for c in valid if "highway" in c.name)
    print(f"learning periods from {sum(c.duration for c in train):.0f} s of normal driving; validation "
          f"{sum(c.duration for c in valid):.0f} s ({road_s:.0f} s on a real road); {time.time() - start:.0f}s")

    meta = road.attack_metadata()
    attacks = []
    for name, info in sorted(meta.items()):
        if not name.endswith("_masquerade") or not info.get("injection_interval"):
            continue
        path = road.signal_path("attacks", name)
        if path.exists():
            attacks.append((name, info["injection_interval"][0], road.load_signal_csv(path, cache)))

    base = SilenceWatchdog(k=3.0, min_s=MIN_S).learn([(c.t, c.ids) for c in train])
    print(f"periodic IDs watched: {len(base.period)}; periods from {min(base.period.values()) * 1000:.0f} ms to "
          f"{max(base.period.values()) * 1000:.0f} ms\n")

    print(f"{'k':>5}{'false events/h (valid.)':>25}{'pre-attack events':>19}{'detected':>10}{'median':>9}{'max':>9}"
          f"{'<=50ms':>8}{'<=100ms':>9}   without authentication")
    rows = {}
    for k in KS:
        wd = SilenceWatchdog(k=k, min_s=MIN_S).learn([(c.t, c.ids) for c in train])
        fa = sum(len(road.merge_events(wd.alarms(c.t, c.ids))) for c in valid)
        delays, blind, pre = [], 0, 0
        for name, t0, cap in attacks:
            accepted = cap.labels == 0                                   # idealised authentication
            alarms = wd.alarms(cap.t, cap.ids, accepted)
            pre += len(road.merge_events(alarms[alarms < t0]))
            late = alarms[alarms >= t0 - 1e-9]
            delays.append(float(late.min() - t0) * 1000 if len(late) else None)
            plain = wd.alarms(cap.t, cap.ids)                            # no authentication: replaced frames look normal
            blind += int(len(plain[plain >= t0 - 1e-9]) == 0)
        hit = [d for d in delays if d is not None]
        rows[k] = (fa / hours, pre, delays)
        print(f"{k:>5.0f}{fa / hours:>25.1f}{pre:>19}{len(hit):>7}/{len(delays)}"
              f"{statistics.median(hit) if hit else float('nan'):>8.0f}ms{max(hit) if hit else float('nan'):>7.0f}ms"
              f"{sum(d <= 50 for d in hit) / len(delays):>8.2f}{sum(d <= 100 for d in hit) / len(delays):>9.2f}"
              f"   {len(delays) - blind}/{len(delays)} detected")

    print("\nDetection delay by attack family, k = 3 (ms after injection start; every masquerade capture)")
    fam = {}
    for (name, t0, cap), d in zip(attacks, rows[3.0][2]):
        fam.setdefault(family_of(name), []).append(d)
    for f, ds in sorted(fam.items()):
        shown = ", ".join("-" if d is None else f"{d:.0f}" for d in ds)
        print(f"  {f:<24}{shown}")

    wd = SilenceWatchdog(k=3.0, min_s=MIN_S).learn([(c.t, c.ids) for c in train])
    print("\nFalse triggers per validation capture at k = 3 (watching all learned IDs)")
    for c in valid:
        n = len(road.merge_events(wd.alarms(c.t, c.ids)))
        print(f"  {c.name:<46}{c.duration:>7.0f} s{n:>6} events{n / (c.duration / 3600):>9.1f}/h")
    print("\nIf the watchdog watched ONLY the sensing IDs of the attacked signals (as the design does), "
          "false triggers in validation:")
    sensing = {i: p_ for i, p_ in wd.period.items() if i in {208, 1760, 1255}}
    only = SilenceWatchdog(k=3.0, min_s=MIN_S)
    only.period = sensing
    fa_only = sum(len(road.merge_events(only.alarms(c.t, c.ids))) for c in valid)
    road_only = [c for c in valid if "highway" in c.name]
    fa_road = sum(len(road.merge_events(only.alarms(c.t, c.ids))) for c in road_only)
    print(f"  IDs {sorted(sensing)}: {fa_only} events in {hours:.2f} h ({fa_only / hours:.1f}/h); "
          f"on the real road alone: {fa_road} in {sum(c.duration for c in road_only) / 3600:.2f} h")
    noisy = []
    for c in valid:
        for can_id in wd.period:
            n = len(wd.alarms(c.t[c.ids == can_id], c.ids[c.ids == can_id]))
            if n:
                noisy.append((hex(can_id), wd.period[can_id] * 1000, n, c.name))
    noisy.sort(key=lambda r: -r[2])
    print("\nIDs behind the false triggers at k = 3 (id, period ms, silent gaps, capture):")
    for row in noisy[:6]:
        print(f"  {row[0]:<8}{row[1]:>7.0f} ms  {row[2]:>4}  {row[3]}")
    if not noisy:
        print("  none")
    print(f"\ntotal time {time.time() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
