"""
Red/blue loop machinery.

  deployed monitor   fused(deadline, frequency IDS, plausibility) plus any accepted rules
  red sampling       attack parameters drawn by Latin hypercube from each family's bounds,
                     scenarios from the tight-scenario generator
  missed hazard      the attack causes a collision that the benign run does not, and the
                     deployed monitor gives no in-time alarm  ->  a "case" for the blue team

The "evading-hazard volume" of a family is the share of its sampled parameter space that
yields a missed hazard; it is the number the loop tries to drive to zero.
"""
import dataclasses
import random

from sdv.attacks.library import ALL_ATTACKS, make_attack
from sdv.blue.rules import RuleMonitor
from sdv.blue.verify import case_outcome
from sdv.monitors.monitors import (
    DeadlineMonitor, FrequencyIDS, FusedMonitor, PlausibilityMonitor, observe,
)
from sdv.runner import execute
from sdv.search.problem import random_tight_scenario
from sdv.search.sampling import latin_hypercube
from sdv.system.brake_chain import ChainParams


def radar_params() -> ChainParams:
    return dataclasses.replace(ChainParams.from_config(), radar=True)


def benign_runs(n: int, seed0: int, params: ChainParams = None):
    """Bus-visible observations of benign runs over random tight scenarios."""
    params = params or radar_params()
    out = []
    for i in range(n):
        scenario = random_tight_scenario(random.Random(seed0 + i))
        out.append(observe(execute(scenario, seed0 + i, params=params)[1]))
    return out


def base_monitors(train_obs):
    deadline, freq, plaus = DeadlineMonitor(), FrequencyIDS(), PlausibilityMonitor()
    for m in (deadline, freq):
        m.train(train_obs)
    return [deadline, freq, plaus]


def deployed(base, rules):
    return FusedMonitor(list(base) + [RuleMonitor(r) for r in rules], name="deployed")


def known_ids_of(observations):
    return sorted({f.can_id for frames, _ in observations for f in frames})


def collect_cases(monitor, families, n_per_family: int, rng: random.Random, params: ChainParams = None):
    """Red team: sample attacks, return (all hazard cases, missed cases, per-family statistics)."""
    params = params or radar_params()
    hazards, stats = [], {}
    for family in families:
        cls = ALL_ATTACKS[family]
        hazard_n = 0
        for i, theta in enumerate(latin_hypercube(cls.PARAM_BOUNDS, n_per_family, rng)):
            if family == "jitter_injection":
                theta["seed"] = i
            scenario, seed = random_tight_scenario(rng), rng.randrange(10 ** 9)
            benign, _ = execute(scenario, seed, params=params)
            attack = make_attack(family, **theta)
            result, chain = execute(scenario, seed, params=params, attacks=[attack])
            if not (result.outcome.collision and not benign.outcome.collision
                    and result.latest_safe_latency_ms > 0):
                continue
            hazard_n += 1
            frames, ctx = observe(chain)
            start, end = chain.attack_windows[0][1], chain.attack_windows[0][2]
            hazards.append({"family": family, "theta": theta, "scenario": scenario.model_dump(), "seed": seed,
                            "frames": frames, "ctx": ctx, "result": result, "start_us": start,
                            "window_us": (start, end), "base_alarm": monitor.first_alarm_us(frames, ctx)})
        stats[family] = {"sampled": n_per_family, "hazards": hazard_n}
    missed = [c for c in hazards if not case_outcome(c, c["base_alarm"])[1]]
    for family in stats:
        stats[family]["missed"] = sum(c["family"] == family for c in missed)
    return hazards, missed, stats


def timely_rate(cases):
    """Share of hazard cases flagged in time by the alarms stored in base_alarm."""
    if not cases:
        return float("nan")
    return sum(case_outcome(c, c["base_alarm"])[1] for c in cases) / len(cases)


def refresh_alarms(cases, monitor):
    for c in cases:
        c["base_alarm"] = monitor.first_alarm_us(c["frames"], c["ctx"])
