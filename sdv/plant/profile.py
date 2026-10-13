"""
Calibrated plant profiles: braking parameters measured elsewhere (for example in CARLA) fed into the whole pipeline.

A profile is a small JSON file:

    {"name": "...", "decel_ms2": 5.31, "brake_ramp_ms": 50, "source": "...", "notes": "..."}

`apply_profile` overrides the plant section of the configuration for the duration of a `with` block and restores it
afterwards, so a profile never leaks into another run. The evidence bundle stores the profile it was built under and the
auditor re-applies it, so a bundle built for a calibrated plant audits against that plant, not the default one.
"""
import contextlib
import json
from pathlib import Path

import config

REQUIRED = ("name", "decel_ms2", "brake_ramp_ms")


def load_profile(path) -> dict:
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_profile(profile)


def validate_profile(profile: dict) -> dict:
    missing = [k for k in REQUIRED if k not in profile]
    if missing:
        raise ValueError(f"plant profile is missing {missing}")
    if not 1.0 <= float(profile["decel_ms2"]) <= 12.0:
        raise ValueError(f"decel_ms2={profile['decel_ms2']} is outside the range of any road vehicle (1-12 m/s^2)")
    if not 0.0 <= float(profile["brake_ramp_ms"]) <= 1000.0:
        raise ValueError(f"brake_ramp_ms={profile['brake_ramp_ms']} is outside 0-1000 ms")
    return dict(profile)


def profile_from_carla_fits(fits: dict, speed_kmh: int = 60, name: str = "carla", source: str = "") -> dict:
    """Profile from the fits dictionary written by experiments/e13_carla_plant.py (keys are speeds in km/h)."""
    key = str(speed_kmh)
    fit = fits.get(key) or fits.get(speed_kmh)
    if fit is None:
        raise KeyError(f"no fit for {speed_kmh} km/h; available: {sorted(fits)}")
    return validate_profile({"name": name, "decel_ms2": round(float(fit["decel"]), 2),
                             "brake_ramp_ms": round(1000 * float(fit["ramp_s"])), "source": source,
                             "notes": f"fitted at {speed_kmh} km/h"})


def main(argv=None):
    """python -m sdv.plant.profile --from-carla outputs/e13_carla.json --speed 60 --out profiles/carla.json"""
    import argparse
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--from-carla", required=True, help="JSON written by experiments/e13_carla_plant.py")
    ap.add_argument("--speed", type=int, default=60, help="which fitted speed (km/h) to use")
    ap.add_argument("--name", default="carla")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    data = json.loads(Path(args.from_carla).read_text(encoding="utf-8"))
    profile = profile_from_carla_fits(data["fits"], args.speed, args.name, source=str(args.from_carla))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(json.dumps(profile, indent=2))
    return 0


@contextlib.contextmanager
def apply_profile(profile):
    """Override the dry-road braking parameters while the block runs; None means the configured defaults."""
    if profile is None:
        yield
        return
    profile = validate_profile(profile)
    plant = config._load().setdefault("plant", {})
    friction = plant.setdefault("friction", {})
    saved = (friction.get("dry", "unset"), plant.get("brake_ramp_ms", "unset"))
    friction["dry"] = float(profile["decel_ms2"]) / float(config.get("plant.gravity", 9.81))
    plant["brake_ramp_ms"] = float(profile["brake_ramp_ms"])
    try:
        yield
    finally:
        for key, value, target in (("dry", saved[0], friction), ("brake_ramp_ms", saved[1], plant)):
            if value == "unset":
                target.pop(key, None)
            else:
                target[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
