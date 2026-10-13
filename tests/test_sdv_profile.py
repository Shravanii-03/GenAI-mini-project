"""
tests/test_sdv_profile.py — calibrated plant profiles.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import config
from sdv.plant.longitudinal import decel_for_road, latest_safe_latency_ms, ramp_seconds
from sdv.plant.profile import apply_profile, load_profile, main, profile_from_carla_fits, validate_profile
from sdv.schemas import Scenario

PROFILE = {"name": "test", "decel_ms2": 5.0, "brake_ramp_ms": 80}
SCEN = Scenario(v0_kmh=60, d0_m=30, cpu_load=0.3)


class TestValidation:

    def test_required_fields(self):
        with pytest.raises(ValueError):
            validate_profile({"name": "x", "decel_ms2": 5.0})

    def test_implausible_braking_is_rejected(self):
        with pytest.raises(ValueError):
            validate_profile({"name": "x", "decel_ms2": 28.0, "brake_ramp_ms": 50})     # the teleport-start artefact
        with pytest.raises(ValueError):
            validate_profile({"name": "x", "decel_ms2": 5.0, "brake_ramp_ms": 5000})

    def test_load_from_file(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text(json.dumps(PROFILE))
        assert load_profile(path)["decel_ms2"] == 5.0


class TestApply:

    def test_overrides_and_restores_the_plant(self):
        before = (decel_for_road("dry"), ramp_seconds(), latest_safe_latency_ms(SCEN))
        with apply_profile(PROFILE):
            assert decel_for_road("dry") == pytest.approx(5.0)
            assert ramp_seconds() == pytest.approx(0.08)
            assert latest_safe_latency_ms(SCEN) < before[2]          # weaker brakes: less time to react
        assert (decel_for_road("dry"), ramp_seconds(), latest_safe_latency_ms(SCEN)) == pytest.approx(before)

    def test_restores_even_when_the_block_raises(self):
        before = decel_for_road("dry")
        with pytest.raises(RuntimeError):
            with apply_profile(PROFILE):
                raise RuntimeError("boom")
        assert decel_for_road("dry") == pytest.approx(before)

    def test_none_changes_nothing(self):
        before = decel_for_road("dry")
        with apply_profile(None):
            assert decel_for_road("dry") == pytest.approx(before)

    def test_other_roads_are_untouched(self):
        wet = decel_for_road("wet")
        with apply_profile(PROFILE):
            assert decel_for_road("wet") == pytest.approx(wet)

    def test_config_is_left_exactly_as_it_was(self):
        snapshot = json.dumps(config._load().get("plant"), sort_keys=True)
        with apply_profile(PROFILE):
            pass
        assert json.dumps(config._load().get("plant"), sort_keys=True) == snapshot


class TestFromCarla:

    FITS = {"40": {"decel": 4.86, "ramp_s": 0.07}, "60": {"decel": 5.31, "ramp_s": 0.05}}

    def test_profile_from_fits(self):
        p = profile_from_carla_fits(self.FITS, 60, "carla")
        assert p["decel_ms2"] == 5.31 and p["brake_ramp_ms"] == 50

    def test_missing_speed_is_an_error(self):
        with pytest.raises(KeyError):
            profile_from_carla_fits(self.FITS, 90)

    def test_command_line_writes_a_profile(self, tmp_path, capsys):
        src = tmp_path / "e13.json"
        src.write_text(json.dumps({"fits": self.FITS}))
        out = tmp_path / "profiles" / "p.json"
        assert main(["--from-carla", str(src), "--speed", "40", "--out", str(out)]) == 0
        assert json.loads(out.read_text())["decel_ms2"] == 4.86
