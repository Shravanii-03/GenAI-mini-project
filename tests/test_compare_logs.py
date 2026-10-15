"""
tests/test_compare_logs.py — comparing two reproduction logs ignores run times and reports real differences.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experiments"))

import compare_logs

OLD = """\
==============================================================================
=== E1 detector comparison
==============================================================================
monitor recall
fused 0.90
--- E1 detector comparison: ok in 53s

==============================================================================
=== E9 radar failover
==============================================================================
masquerade 42.9% -> 0.0%
total time 409s
--- E9 radar failover: ok in 409s
"""


def test_run_times_are_ignored():
    new = OLD.replace("ok in 53s", "ok in 110s").replace("total time 409s", "total time 999s").replace("ok in 409s", "ok in 1s")
    report = compare_logs.compare(OLD, new)
    assert not report["different"] and len(report["identical"]) == 2


def test_a_changed_number_is_reported():
    new = OLD.replace("fused 0.90", "fused 0.91")
    report = compare_logs.compare(OLD, new)
    assert list(report["different"]) == ["E1 detector comparison"]
    assert any("0.91" in line for line in report["different"]["E1 detector comparison"])


def test_missing_and_extra_steps_are_listed_but_do_not_count_as_differences():
    new = OLD.split("==============================================================================\n=== E9")[0] \
        + "=== E14 new step\nrow\n"
    report = compare_logs.compare(OLD, new)
    assert report["only_old"] == ["E9 radar failover"] and report["only_new"] == ["E14 new step"]
    assert not report["different"]


def test_command_line_exit_codes(tmp_path):
    a, b, c = tmp_path / "a.log", tmp_path / "b.log", tmp_path / "c.log"
    a.write_text(OLD)
    b.write_text(OLD.replace("ok in 53s", "ok in 7s"))
    c.write_text(OLD.replace("0.90", "0.80"))
    assert compare_logs.main([str(a), str(b)]) == 0
    assert compare_logs.main([str(a), str(c)]) == 1
    assert compare_logs.main([str(a)]) == 2
