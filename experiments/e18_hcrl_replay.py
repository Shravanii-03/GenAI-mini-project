"""
E18: a second real vehicle (HCRL Car-Hacking, Song, Woo and Kim 2020) against the flood model and the silence watchdog.

  (a) The 300 real DoS bursts (ID 0x000): how long do the normal frames go missing, and how does that compare with the
      response-time bound computed from THIS vehicle's own measured periodic traffic plus a flood stream (documented rate
      0.3 ms; the slower rate the logger recorded, 0.5 ms; and a saturating flood, one frame right after another)?
  (b) Silence-watchdog false triggers on this vehicle's attack-free driving (learn on the first half, test on the second), and
      how fast the silence of a DoS burst is noticed.
  (c) Injection attacks (fuzzy, RPM spoofing, gear spoofing): is the genuine stream of the spoofed ID worse off than the other
      IDs while the injection runs?
  (d) Data quality: what the captures can and cannot support.

    python experiments/e18_hcrl_replay.py            # needs HCRL (see sdv/realdata/hcrl.py)

What limits every number here: the captures were made with a logger that loses frames when the bus is busy (the DoS file logs
about 430 injected frames/s against 3,300/s documented, and the injection files contain recording pauses of several seconds),
so a long silence can be bus starvation or logger loss and the data cannot tell them apart. The bit rate (500 kbit/s) is
assumed. Authentication is idealised as in E15. One vehicle.
"""
import os
import sys
import time
from contextlib import contextmanager

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.analysis import bounds
from sdv.realdata import hcrl, road
from sdv.realdata.watchdog import SilenceWatchdog

FLOOD_ID = 0
DOCUMENTED_GAP_S = 0.0003
BURST_GAP_S = 0.5
SPOOFED = {"rpm": 0x316, "gear": 0x43F}


def measured_traffic(normal):
    """Per-ID period, worst observed gap, jitter and DLC from attack-free driving: the vehicle's own background model."""
    out = {}
    for can_id in np.unique(normal.ids):
        sel = normal.ids == can_id
        t = normal.t[sel]
        if len(t) < 100:
            continue
        gaps = np.diff(t)
        median = float(np.median(gaps))
        out[int(can_id)] = {"period_s": median, "max_gap_s": float(gaps.max()),
                            "jitter_s": max(0.0, float(np.percentile(gaps, 99)) - median),
                            "dlc": int(np.bincount(normal.dlc[sel]).argmax())}
    return out


@contextmanager
def background_of(traffic):
    """Run the response-time analysis over the measured vehicle instead of the catalogue."""
    saved = bounds._background
    bounds._background = lambda: [bounds.Stream(i, v["period_s"] * 1e6, bounds._c_us(v["dlc"]), v["jitter_s"] * 1e6)
                                  for i, v in traffic.items()]
    try:
        yield
    finally:
        bounds._background = saved


def worst_gap_overlapping(t_ids, s, e):
    """Longest gap between consecutive frames (of one ID) that overlaps the window [s, e]; None if too few frames."""
    k0 = max(int(np.searchsorted(t_ids, s)) - 1, 0)
    k1 = min(int(np.searchsorted(t_ids, e)) + 1, len(t_ids))
    seg = t_ids[k0:k1]
    return float(np.diff(seg).max()) if len(seg) > 1 else None


def flood_bound_ms(can_id, traffic, flood_gap_s, burst_s):
    n = int(burst_s / flood_gap_s) + 1
    flood = bounds.Stream(FLOOD_ID, flood_gap_s * 1e6, bounds._c_us(8), 0.0, n)
    with background_of(traffic):
        r_us = bounds.response_time_us(can_id, extra=[flood], dlc=traffic[can_id]["dlc"])
    return r_us / 1000.0


def part_a(dos, traffic):
    bursts = hcrl.bursts(dos, BURST_GAP_S)
    longest = max(e - s for s, e in bursts)
    print(f"\n(a) {len(bursts)} real DoS bursts (ID 0x000): {np.median([e - s for s, e in bursts]):.2f} s median, "
          f"{longest:.2f} s longest, one every {np.median(np.diff([s for s, _ in bursts])):.1f} s; {int((dos.labels == 1).sum())} flood frames logged")
    inj = dos.t[dos.labels == 1]
    logged = sum(((inj >= s) & (inj <= e)).sum() for s, e in bursts) / sum(e - s for s, e in bursts)
    load = sum(hcrl.frame_time_s(v["dlc"]) / v["period_s"] for v in traffic.values())
    print(f"    logged flood rate {logged:.0f} frames/s against {1 / DOCUMENTED_GAP_S:.0f}/s documented: the logger kept about "
          f"{100 * logged * DOCUMENTED_GAP_S:.0f}% of it")
    print(f"    this vehicle's own traffic loads the bus to {load:.2f} (worst-case stuffing, 500 kbit/s assumed)")
    sat_gap = bounds._c_us(8) / 1e6
    print(f"\n    {'ID':>6}{'period':>8}{'longest silence':>17}{'bound 0.5 ms':>14}{'bound 0.3 ms':>14}{'bound saturating':>18}")
    rows = []
    for can_id, v in sorted(traffic.items()):
        t_ids = dos.t[(dos.ids == can_id) & (dos.labels == 0)]
        if len(t_ids) < 50 or can_id == FLOOD_ID:
            continue
        gaps = [g for g in (worst_gap_overlapping(t_ids, s, e) for s, e in bursts) if g is not None]
        if not gaps:
            continue
        slack = 1000 * (v["max_gap_s"] - hcrl.frame_time_s(v["dlc"]))      # a normal gap already contains some jitter
        b = [flood_bound_ms(can_id, traffic, g, longest) + slack for g in (0.0005, DOCUMENTED_GAP_S, sat_gap)]
        rows.append((can_id, v["period_s"], max(gaps) * 1000, *b))
        print(f"    {hex(can_id):>6}{v['period_s'] * 1000:>6.0f}ms{max(gaps) * 1000:>14.0f} ms"
              f"{b[0]:>11.0f} ms{b[1]:>11.0f} ms{b[2]:>15.0f} ms")
    over = {name: sum(r[2] > r[3 + i] for r in rows) for i, name in enumerate(("0.5 ms", "0.3 ms", "saturating"))}
    print(f"\n    IDs whose longest silence exceeds the bound: {over['0.5 ms']}/{len(rows)} at 0.5 ms, {over['0.3 ms']}/{len(rows)} at "
          f"0.3 ms, {over['saturating']}/{len(rows)} for a saturating flood (bound is then about the burst length, {longest * 1000:.0f} ms)")
    tens = [r for r in rows if r[1] <= 0.0105]
    print(f"    the 10 ms IDs go silent for {np.median([r[2] for r in tens]):.0f} ms (median over IDs), up to {max(r[2] for r in tens):.0f} ms; "
          f"about {np.median([r[2] for r in tens]) / 100:.0f} times a 100 ms brake deadline (median)")
    print("    reading: a periodic 0.3 ms flood would delay the highest-priority IDs by only tens of ms, so the capture is NOT\n"
          "    consistent with that model; it is consistent with a saturating flood, and also with the logger losing frames.\n"
          "    The data cannot separate the two, so it does not validate the flood bound; it does show a flood on a shared bus\n"
          "    removing 10 ms control traffic for seconds at a time inside a burst, far beyond a 100 ms deadline.")
    return rows, over


def part_b(normal, dos):
    half = normal.t[-1] / 2
    first, second = normal.t <= half, normal.t > half
    held = normal.duration - half
    print(f"\n(b) watchdog learned {len(SilenceWatchdog().learn([(normal.t[first], normal.ids[first])]).period)} periodic IDs "
          f"from {half:.0f} s of attack-free driving; tested on the next {held:.0f} s")
    print(f"    {'k':>4}{'false events':>14}{'events/h':>10}{'95% upper bound/h':>20}")
    result = {}
    for k in (2.0, 3.0, 5.0, 10.0):
        w = SilenceWatchdog(k=k, min_s=0.03).learn([(normal.t[first], normal.ids[first])])
        n = len(road.merge_events(w.alarms(normal.t[second], normal.ids[second])))
        upper = (3.0 if n == 0 else n + 1.96 * np.sqrt(n) + 1.0) / (held / 3600)           # rule of three when nothing is seen
        result[k] = (n, upper)
        print(f"    {k:>4.0f}{n:>14}{n / (held / 3600):>10.1f}{upper:>20.0f}")
    print("    (253 s is short: zero events cannot rule out a few per hour; ROAD gave about 6/h over a longer real-road drive)")
    wd = SilenceWatchdog(k=3.0, min_s=0.03).learn([(normal.t, normal.ids)])
    bursts = hcrl.bursts(dos, BURST_GAP_S)
    legit = dos.labels == 0
    alarms = wd.alarms(dos.t[legit], dos.ids[legit])
    delays = []
    for s, e in bursts:
        a = alarms[(alarms >= s) & (alarms <= e)]
        delays.append(float(a.min() - s) * 1000 if len(a) else None)
    hit = [d for d in delays if d is not None]
    print(f"    DoS bursts noticed by silence (k = 3): {len(hit)}/{len(delays)}; delay after the burst began: median {np.median(hit):.0f} ms, "
          f"95th percentile {np.percentile(hit, 95):.0f} ms, max {max(hit):.0f} ms (logger loss makes the silence start earlier than the bus would)")
    return result, delays


def clean_windows(cap, margin_s=1.0):
    """Stretches between injection bursts, at least margin_s away from any burst and not spanning a recording pause."""
    bursts = hcrl.bursts(cap, BURST_GAP_S)
    cuts = cap.t[1:][np.diff(cap.t) > 1.0]
    edges = [(-np.inf, bursts[0][0])] + [(e, s2) for (_, e), (s2, _) in zip(bursts, bursts[1:])] + [(bursts[-1][1], np.inf)]
    out = []
    for lo, hi in edges:
        lo, hi = max(lo + margin_s, cap.t[0]), min(hi - margin_s, cap.t[-1])
        if hi - lo > 0.2 and not any(lo < c < hi for c in cuts):
            out.append((lo, hi))
    return out


def part_b2(normal, dos):
    """After a flood ends, how long until the normal stream is back? Windows start 1 s after the burst ends."""
    wd = SilenceWatchdog(k=3.0, min_s=0.03).learn([(normal.t, normal.ids)])
    g = dos.labels == 0
    t, ids = dos.t[g], dos.ids[g]
    ends = np.array([e for _, e in hcrl.bursts(dos, BURST_GAP_S)])
    wins = clean_windows(dos)
    after = []
    for lo, hi in wins:
        sel = (t >= lo) & (t <= hi)
        a = wd.alarms(t[sel], ids[sel])
        if len(a):
            after.append(float(a.max() - ends[ends <= a.max()].max()))
    print(f"\n(b2) recovery after a flood: in {len(after)} of {len(wins)} windows 1-2 s after a burst ended, the watchdog (k = 3) still "
          f"sees a silence ({100 * len(after) / len(wins):.0f}%), the last one {np.median(after):.1f} s after the burst on median "
          f"(max {max(after):.1f} s)")
    print("    so the stretches between bursts are not clean normal driving, and no false-trigger rate is taken from the attack files;\n"
          "    the false-trigger estimate in (b) uses the attack-free file only")
    return after


def part_c(normal, caps):
    wd = SilenceWatchdog(k=3.0, min_s=0.03).learn([(normal.t, normal.ids)])
    print("\n(c) injection attacks, k = 3: share of genuine-frame gaps longer than the watchdog threshold, inside the injection bursts")
    print(f"    {'attack':<8}{'injected ID':>12}{'injected':>10}{'bursts':>8}{'spoofed ID':>12}{'other IDs (median)':>20}{'attack-free':>13}")
    out = {}
    base = {}
    for can_id in wd.period:
        t = normal.t[normal.ids == can_id]
        base[can_id] = float((np.diff(t) > wd.threshold(can_id)).mean())
    for name, cap in caps.items():
        bursts = hcrl.bursts(cap, BURST_GAP_S)
        genuine = cap.labels == 0
        share = {}
        for can_id in wd.period:
            t = cap.t[genuine & (cap.ids == can_id)]
            gaps = np.concatenate([np.diff(t[(t >= s) & (t <= e)]) for s, e in bursts]) if bursts else np.empty(0)
            if len(gaps) > 100:
                share[can_id] = float((gaps > wd.threshold(can_id)).mean())
        target = SPOOFED.get(name)
        others = [v for k, v in share.items() if k != target]
        inj_id = hex(target) if target else "random"
        mine = f"{share[target]:.3f}" if target in share else "-"
        out[name] = (share.get(target), float(np.median(others)))
        print(f"    {name:<8}{inj_id:>12}{int((cap.labels == 1).sum()):>10}{len(bursts):>8}{mine:>12}{np.median(others):>20.3f}"
              f"{np.median(list(base.values())):>13.3f}")
    print("    reading: if the spoofed ID were silenced by the injection, its share would stand out from the other IDs; it does not.\n"
          "    But EVERY ID has a far higher share than in attack-free driving, so the genuine stream is degraded by the capture\n"
          "    (logger loss and bus load) and the watchdog's false-trigger rate cannot be measured inside these files.")
    return out


def part_d(caps, dos):
    print("\n(d) data quality: recording pauses longer than 1 s (each file has one, where recordings were joined) and the "
          "genuine-frame rate outside the labelled bursts")
    for name, cap in (("dos", dos), *caps.items()):
        bursts = hcrl.bursts(cap, BURST_GAP_S)
        pauses = int((np.diff(cap.t) > 1.0).sum())
        inb = np.zeros(len(cap.t), bool)
        for s, e in bursts:
            inb |= (cap.t >= s) & (cap.t <= e)
        total = sum(e - s for s, e in bursts)
        gaps = np.diff(cap.t)
        recorded = cap.duration - float(gaps[gaps > 1.0].sum())              # time actually recorded, pauses removed
        rate_out = ((cap.labels == 0) & ~inb).sum() / max(recorded - total, 1e-9)
        print(f"    {name:<6} {recorded:>7.0f} s recorded, {pauses:>3} pause(s) > 1 s (longest {gaps.max():>6.0f} s), "
              f"genuine rate outside bursts {rate_out:>5.0f}/s (attack-free file: 1953/s)")


def main():
    d = hcrl.hcrl_dir()
    need = ["DoS_dataset.csv", "normal_run_data.txt"]
    if not all((d / f).exists() for f in need):
        print("HCRL data not found; set HCRL_DIR (see sdv/realdata/hcrl.py).")
        return 1
    start = time.time()
    cache = d.parent / "cache"
    normal = hcrl.load_cached(d / need[1], cache)
    dos = hcrl.load_cached(d / need[0], cache)
    print(f"attack-free: {len(normal.t)} frames, {normal.duration:.0f} s, {len(np.unique(normal.ids))} IDs; "
          f"DoS capture: {len(dos.t)} frames, {dos.duration:.0f} s")
    traffic = measured_traffic(normal)
    part_a(dos, traffic)
    part_b(normal, dos)
    caps = {label: hcrl.load_cached(d / f, cache)
            for label, f in (("fuzzy", "Fuzzy_dataset.csv"), ("rpm", "RPM_dataset.csv"), ("gear", "gear_dataset.csv"))
            if (d / f).exists()}
    part_b2(normal, dos)
    if caps:
        part_c(normal, caps)
    part_d(caps, dos)
    print(f"\ntotal time {time.time() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
