"""
Test cases for the embedded C port (embedded/sdv_defences.c), generated from emulator runs.

Each case is the stream of sensor and radar frames the perception ECU received in one emulated run (plus the watchdog ticks),
quantised to millimetres and mm/s as an MCU would hold them, together with what the emulator's own (floating-point) perception
decided. `integer_reference` is a line-by-line Python mirror of the C code: it lets the port be checked without a compiler, and
the C binary must agree with it exactly.

Codes: 0 no trigger, 1 sensor, 2 radar, 3 disagreement, 4 watchdog.
"""
import dataclasses
import random

import numpy as np

from sdv.attacks.library import make_attack
from sdv.runner import execute
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import RADAR_ID, SENSOR_ID, ChainParams

POLICY_CODE = {"none": 0, "radar_or": 1, "disagree_brake": 2}
SOURCE_CODE = {None: 0, "sensor": 1, "radar": 2, "disagreement": 3, "watchdog": 4}
CHECK_US = 5000
WATCHDOG_US = 30000
TTC_MS = 2000
TOL_MM = 3000
FRESH_US = 30000

CONFIGS = [("none", False), ("radar_or", False), ("disagree_brake", False),
           ("none", True), ("radar_or", True), ("disagree_brake", True)]
ATTACK_MIX = [(None, {}), ("masquerade", {}), ("dual_masquerade", {}), ("dual_masquerade", {"holds_key": True}),
              ("sensor_drift_spoof", {}), ("selective_suppression", {}), ("gateway_delay", {}),
              ("dos_flood", {"segment": "safety"}), ("jitter_injection", {}), ("dos_flood", {})]


def _quantise(value):
    return 0 if value is None else int(round(value * 1000))


def frame_events(chain, mitigation: str, auth: bool):
    """Frames the perception ECU received, in order, as ('F', channel, t_us, dist_mm, speed_mms, obstacle, mac_ok)."""
    out = []
    for f in chain.bus.log:
        if f.can_id not in (SENSOR_ID, RADAR_ID):
            continue
        channel = 0 if f.can_id == SENSOR_ID else 1
        forged = bool(f.data.get("forged")) and not f.data.get("holds_key")
        out.append(("F", channel, int(f.t_rx_us), _quantise(f.data.get("distance_m")),
                    _quantise(f.data.get("speed_ms")), int(bool(f.data.get("obstacle"))), 0 if forged else 1))
    # watchdog ticks start CHECK_US after the first accepted frame the chain actually looks at
    ticks = []
    if auth:
        first = next((e[2] for e in out if e[6] == 1 and not (e[1] == 1 and mitigation == "none")), None)
        if first is not None and out:
            end = out[-1][2] + 100000
            t = first + CHECK_US
            while t <= end:
                ticks.append(("T", t))
                t += CHECK_US
    merged = sorted(out + ticks, key=lambda e: (e[2] if e[0] == "F" else e[1], 0 if e[0] == "T" else 1))
    return merged


def integer_reference(policy: int, auth: bool, events):
    """Python mirror of embedded/sdv_defences.c. Returns (code, t_us or -1, rejected)."""
    last_us, last_mm, have = [0, 0], [0, 0], [False, False]
    detected = armed = False
    last_valid = 0
    rejected = 0
    for e in events:
        if e[0] == "F":
            _, ch, now, d, v, obstacle, mac_ok = e
            if ch == 1 and policy == 0:
                continue
            if auth:
                if not mac_ok:
                    rejected += 1
                    continue
                last_valid, armed = now, True
            if not obstacle or detected:
                continue
            last_us[ch], last_mm[ch], have[ch] = now, d, True
            if v > 0 and d * 1000 <= TTC_MS * v:
                return (1 if ch == 0 else 2), now, rejected
            if policy == 2 and have[0] and have[1] and (now - last_us[0]) <= FRESH_US and (now - last_us[1]) <= FRESH_US \
                    and abs(last_mm[0] - last_mm[1]) > TOL_MM:
                return 3, now, rejected
        else:
            now = e[1]
            if armed and not detected and (now - last_valid) > WATCHDOG_US:
                return 4, now, rejected
    return 0, -1, rejected


def generate_cases(n: int = 120, seed: int = 0):
    """Emulator runs over a mix of defence configurations and attacks; returns a list of case dictionaries."""
    rng = np.random.default_rng(seed)
    cases = []
    for i in range(n):
        mitigation, auth = CONFIGS[i % len(CONFIGS)]
        family, extra = ATTACK_MIX[(i // len(CONFIGS)) % len(ATTACK_MIX)]
        scenario = random_tight_scenario(random.Random(seed * 1000 + i))
        chain_params = dataclasses.replace(ChainParams.from_config(), radar=True, mitigation=mitigation, auth=auth)
        attacks = []
        if family:
            problem = AttackSearchProblem(family, scenario)
            attacks = [make_attack(family, **{**problem.decode(rng.random(problem.dim)), **extra})]
        result, chain = execute(scenario, seed * 100_000 + i, chain_params, attacks=attacks)
        events = frame_events(chain, mitigation, auth)
        code = SOURCE_CODE[chain.trigger_source]
        trigger_us = int(chain.timeline["sensor_rx"]) if chain.trigger_source else -1
        if trigger_us >= 0:                                     # nothing after the trigger can matter
            events = [e for e in events if (e[2] if e[0] == "F" else e[1]) <= trigger_us + 1000]
        cases.append({"name": f"c{i:03d}_{family or 'benign'}_{mitigation}_{'auth' if auth else 'plain'}",
                      "policy": POLICY_CODE[mitigation], "auth": int(auth), "events": events,
                      "emulator": {"code": code, "t_us": trigger_us, "collision": bool(result.outcome.collision)}})
    return cases


def to_text(cases) -> str:
    lines = []
    for c in cases:
        lines.append(f"CASE {c['name']} {c['policy']} {c['auth']}")
        for e in c["events"]:
            lines.append("F " + " ".join(str(x) for x in e[1:]) if e[0] == "F" else f"T {e[1]}")
        lines.append("END")
    return "\n".join(lines) + "\n"


def expected(cases) -> dict:
    out = {}
    for c in cases:
        code, t_us, rejected = integer_reference(c["policy"], bool(c["auth"]), c["events"])
        out[c["name"]] = {"reference": {"code": code, "t_us": t_us, "rejected": rejected}, "emulator": c["emulator"],
                          "intent": c.get("intent")}
    return out


def synthetic_cases():
    """Hand-built edge cases. `intent` is what the DESIGN says should happen, independent of any implementation."""
    def F(ch, t, d, v, obs=1, mac=1):
        return ("F", ch, t, d, v, obs, mac)

    far, near, v = 60000, 10000, 16667
    cases = [
        ("disagreement_triggers", 2, 0, [F(0, 1000, far, v), F(1, 1005, far - 10000, v)], (3, 1005)),
        ("disagreement_needs_the_policy", 1, 0, [F(0, 1000, far, v), F(1, 1005, far - 10000, v)], (0, -1)),
        ("disagreement_needs_fresh_data", 2, 0, [F(0, 1000, far, v), F(1, 41000, far - 10000, v)], (0, -1)),
        ("disagreement_below_tolerance", 2, 0, [F(0, 1000, far, v), F(1, 1005, far - 2000, v)], (0, -1)),
        ("radar_ignored_by_the_baseline_policy", 0, 0, [F(1, 1000, near, v)], (0, -1)),
        ("radar_triggers_under_failover", 1, 0, [F(1, 1000, near, v)], (2, 1000)),
        ("sensor_triggers", 0, 0, [F(0, 1000, near, v)], (1, 1000)),
        ("forged_frame_is_used_without_auth", 0, 0, [F(0, 1000, near, v, mac=0)], (1, 1000)),
        ("forged_frame_is_rejected_with_auth", 0, 1, [F(0, 1000, near, v, mac=0)], (0, -1)),
        ("exactly_at_the_ttc_threshold_triggers", 0, 0, [F(0, 1000, 33334, v)], (1, 1000)),
        ("one_millimetre_above_does_not", 0, 0, [F(0, 1000, 33335, v)], (0, -1)),
        ("zero_speed_never_triggers", 0, 0, [F(0, 1000, 0, 0)], (0, -1)),
        ("no_obstacle_no_trigger", 0, 0, [F(0, 1000, near, v, obs=0)], (0, -1)),
        ("watchdog_silence_exactly_at_the_limit_is_tolerated", 0, 1,
         [F(0, 1000, far, v), ("T", 6000), ("T", 11000), ("T", 16000), ("T", 21000), ("T", 26000), ("T", 31000)], (0, -1)),
        ("watchdog_fires_just_after_the_limit", 0, 1,
         [F(0, 1000, far, v), ("T", 6000), ("T", 11000), ("T", 16000), ("T", 21000), ("T", 26000), ("T", 31000),
          ("T", 36000)], (4, 36000)),
        ("watchdog_stays_quiet_while_frames_arrive", 0, 1,
         [F(0, 1000, far, v), ("T", 6000), F(0, 11000, far, v), ("T", 16000), F(0, 21000, far, v), ("T", 26000),
          F(0, 31000, far, v), ("T", 36000)], (0, -1)),
        ("watchdog_needs_auth", 0, 0, [F(0, 1000, far, v), ("T", 100000)], (0, -1)),
        ("forged_frames_do_not_feed_the_watchdog", 0, 1,
         [F(0, 1000, far, v), F(0, 8000, far, v, mac=0), F(0, 16000, far, v, mac=0), ("T", 36000)], (4, 36000)),
    ]
    return [{"name": f"s_{name}", "policy": policy, "auth": auth, "events": events,
             "emulator": None, "intent": {"code": intent[0], "t_us": intent[1]}} for name, policy, auth, events, intent in cases]


def all_cases(n_emulator: int = 120, seed: int = 0):
    return generate_cases(n_emulator, seed) + synthetic_cases()
