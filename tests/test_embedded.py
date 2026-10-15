"""
tests/test_embedded.py — the embedded C port: reference checks in Python, plus compile-and-replay when a compiler exists.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "embedded"))

import pytest

import verify
from sdv.embedded_check.cases import (
    all_cases, expected, generate_cases, integer_reference, synthetic_cases, to_text,
)


@pytest.fixture(scope="module")
def small():
    return generate_cases(30, seed=2)


def test_static_constraints_hold():
    assert verify.static_checks() == []


def test_the_c_source_has_no_loops():
    code = (ROOT / "embedded" / "sdv_defences.c").read_text(encoding="utf-8")
    assert " for (" not in code and "while (" not in code and "for(" not in code


def test_hand_built_edge_cases_match_the_design_intent():
    for case in synthetic_cases():
        code, t_us, _ = integer_reference(case["policy"], bool(case["auth"]), case["events"])
        assert (code, t_us) == (case["intent"]["code"], case["intent"]["t_us"]), case["name"]


def test_integer_port_reproduces_the_emulator_decision(small):
    for case in small:
        code, t_us, _ = integer_reference(case["policy"], bool(case["auth"]), case["events"])
        assert (code, t_us) == (case["emulator"]["code"], case["emulator"]["t_us"]), case["name"]


def test_cases_cover_all_trigger_sources_between_emulator_and_edge_cases():
    codes = {c["emulator"]["code"] for c in generate_cases(60, seed=0)} | \
            {c["intent"]["code"] for c in synthetic_cases()}
    assert codes == {0, 1, 2, 3, 4}


def test_case_generation_is_deterministic():
    assert to_text(generate_cases(12, seed=1)) == to_text(generate_cases(12, seed=1))


def test_text_format_is_parseable_and_complete(small):
    text = to_text(small)
    assert text.count("CASE ") == len(small) == text.count("END\n")
    assert all(line[0] in "CFTE" for line in text.splitlines())


def test_committed_cases_are_consistent_with_the_reference():
    cases_file = ROOT / "embedded" / "cases" / "cases.txt"
    exp_file = ROOT / "embedded" / "cases" / "expected.json"
    if not cases_file.exists():
        pytest.skip("run experiments/e16_embedded_feasibility.py to generate the cases")
    exp = json.loads(exp_file.read_text(encoding="utf-8"))
    assert cases_file.read_text(encoding="utf-8").count("CASE ") == len(exp)
    regenerated = expected(all_cases(120, 0))
    assert regenerated == exp


@pytest.mark.skipif(verify.find_compiler() is None, reason="no C compiler on this machine")
def test_compiled_port_matches_the_reference_exactly():
    result = subprocess.run([sys.executable, str(ROOT / "embedded" / "verify.py")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-1500:]
    assert "RESULT: PASS" in result.stdout
