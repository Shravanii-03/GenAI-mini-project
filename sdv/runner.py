"""Run one emulated braking scenario end to end and return a typed RunResult."""
from sdv.plant.longitudinal import latest_safe_latency_ms, simulate_braking
from sdv.schemas import RunResult, Scenario
from sdv.system.brake_chain import BrakeChain, ChainParams

_STAGES = [
    ("sampling", None, "sensor_enq"),
    ("sensor_bus", "sensor_enq", "sensor_rx"),
    ("perception", "sensor_rx", "detect_enq"),
    ("detect_bus", "detect_enq", "detect_rx"),
    ("decision", "detect_rx", "cmd_enq"),
    ("cmd_bus", "cmd_enq", "cmd_rx"),
    ("actuator", "cmd_rx", "brake_onset"),
]


def execute(scenario: Scenario, seed: int, params: ChainParams = None,
            attacks=(), background: bool = True):
    """Run one scenario and return (RunResult, chain) so callers can inspect the bus log."""
    chain = BrakeChain(scenario, seed, params, attacks=attacks, background=background)
    timeline_us = chain.run()
    t0 = chain.t_appear_us

    timeline_ms = {k: (v - t0) / 1000.0 for k, v in timeline_us.items()}
    stage_ms = {}
    for name, start, end in _STAGES:
        if end in timeline_us and (start is None or start in timeline_us):
            begin = t0 if start is None else timeline_us[start]
            stage_ms[name] = (timeline_us[end] - begin) / 1000.0

    braked = chain.brake_onset_us is not None
    latency_ms = (chain.brake_onset_us - t0) / 1000.0 if braked else None
    outcome = simulate_braking(scenario, None if latency_ms is None else latency_ms / 1000.0)
    safe_ms = latest_safe_latency_ms(scenario)

    result = RunResult(
        seed=seed,
        scenario=scenario,
        braked=braked,
        e2e_latency_ms=latency_ms,
        timeline_ms=timeline_ms,
        stage_ms=stage_ms,
        outcome=outcome,
        latest_safe_latency_ms=safe_ms,
        margin_ms=None if latency_ms is None else safe_ms - latency_ms,
        attacks=[{"name": a.name, **a.params()} for a in chain.attacks],
        attack_windows_ms=[
            {"name": n, "start_ms": (s_ - t0) / 1000.0, "end_ms": (e_ - t0) / 1000.0}
            for n, s_, e_ in chain.attack_windows
        ],
    )
    return result, chain


def run_once(scenario: Scenario, seed: int, params: ChainParams = None,
             attacks=(), background: bool = True) -> RunResult:
    return execute(scenario, seed, params, attacks, background)[0]
