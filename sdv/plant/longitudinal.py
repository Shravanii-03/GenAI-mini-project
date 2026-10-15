"""
Longitudinal braking plant.

An obstacle becomes detectable d0 metres ahead of an ego vehicle travelling at
v0. The vehicle keeps its speed until the brake command takes effect (the
end-to-end latency), then brake force ramps up linearly to mu*g over ramp_s.

Because the model is closed-form, the "point of no return" is exact: the largest
latency for which a collision is still avoidable. This gives every run a
physically grounded hazard outcome instead of only a threshold comparison.
"""
import math

import config
from sdv.schemas import PlantOutcome, Scenario

_DEFAULT_FRICTION = {"dry": 0.8, "wet": 0.5, "icy": 0.25}


def decel_for_road(road: str) -> float:
    mu = config.get(f"plant.friction.{road}", _DEFAULT_FRICTION[road])
    return mu * config.get("plant.gravity", 9.81)


def ramp_seconds() -> float:
    return config.get("plant.brake_ramp_ms", 50) / 1000.0


def braking_distance(v0: float, decel: float, ramp_s: float) -> float:
    """Distance travelled from brake onset until standstill (ramp then constant decel)."""
    if ramp_s <= 0:
        return v0 * v0 / (2 * decel)
    if v0 <= decel * ramp_s / 2:
        # Vehicle stops before the ramp completes.
        s = math.sqrt(2 * ramp_s * v0 / decel)
        return v0 * s - decel * s ** 3 / (6 * ramp_s)
    v1 = v0 - decel * ramp_s / 2
    ramp_distance = v0 * ramp_s - decel * ramp_s ** 2 / 6
    return ramp_distance + v1 * v1 / (2 * decel)


def latest_safe_latency_s(v0: float, d0: float, decel: float, ramp_s: float) -> float:
    """Point of no return. Negative means a collision is unavoidable even at zero latency."""
    return (d0 - braking_distance(v0, decel, ramp_s)) / v0


def _impact_speed(v0: float, d0: float, latency_s: float, decel: float, ramp_s: float) -> float:
    x = v0 * latency_s
    if x >= d0:
        return v0
    v, t, dt = v0, 0.0, 0.0005
    while v > 0:
        a = decel if ramp_s <= 0 else decel * min(1.0, t / ramp_s)
        v_new = max(0.0, v - a * dt)
        x += (v + v_new) / 2 * dt
        t += dt
        v = v_new
        if x >= d0:
            return v
    return 0.0


def simulate_braking(scenario: Scenario, latency_s) -> PlantOutcome:
    """Outcome when the brake takes effect latency_s after the obstacle appears.

    latency_s=None (or inf) means the vehicle never brakes.
    """
    v0 = scenario.v0_kmh / 3.6
    d0 = scenario.d0_m
    decel = decel_for_road(scenario.road)
    ramp_s = ramp_seconds()

    if latency_s is None or math.isinf(latency_s):
        return PlantOutcome(collision=True, impact_speed_ms=v0, stop_distance_m=d0, min_gap_m=0.0)

    stop_distance = v0 * latency_s + braking_distance(v0, decel, ramp_s)
    if stop_distance > d0:
        return PlantOutcome(
            collision=True,
            impact_speed_ms=_impact_speed(v0, d0, latency_s, decel, ramp_s),
            stop_distance_m=d0,
            min_gap_m=0.0,
        )
    return PlantOutcome(
        collision=False,
        impact_speed_ms=0.0,
        stop_distance_m=stop_distance,
        min_gap_m=d0 - stop_distance,
    )


def latest_safe_latency_ms(scenario: Scenario) -> float:
    return 1000.0 * latest_safe_latency_s(
        scenario.v0_kmh / 3.6, scenario.d0_m,
        decel_for_road(scenario.road), ramp_seconds(),
    )
