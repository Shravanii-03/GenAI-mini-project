"""
E16: embedded feasibility of the perception-side defences (embedded/sdv_defences.c).

Generates test cases from emulator runs (and hand-built edge cases), writes them to embedded/cases/, checks the integer port in
Python against the emulator's floating-point decisions, then - if a C compiler is available - compiles the C code, replays
every case and checks that the C binary agrees EXACTLY with the integer reference.

    python experiments/e16_embedded_feasibility.py                 # generate, check in Python, compile if possible
    python embedded/verify.py                                      # on any machine with a C compiler (e.g. Colab)

NOT a measurement on a microcontroller. Footprints are from a host build; timings are host timings.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.embedded_check.cases import all_cases, expected, to_text

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "embedded" / "cases"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120, help="emulator-generated cases")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    cases = all_cases(args.n, args.seed)
    exp = expected(cases)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cases.txt").write_text(to_text(cases), encoding="utf-8")
    (OUT / "expected.json").write_text(json.dumps(exp, indent=1), encoding="utf-8")
    size_kb = (OUT / "cases.txt").stat().st_size / 1024
    print(f"wrote {len(cases)} cases to {OUT} ({size_kb:.0f} KB)")

    emu = [(n, e) for n, e in exp.items() if e["emulator"] is not None]
    same = sum((e["reference"]["code"], e["reference"]["t_us"]) == (e["emulator"]["code"], e["emulator"]["t_us"]) for _, e in emu)
    intent = [(n, e) for n, e in exp.items() if e["intent"] is not None]
    ok = sum((e["reference"]["code"], e["reference"]["t_us"]) == (e["intent"]["code"], e["intent"]["t_us"]) for _, e in intent)
    sources = {}
    for _, e in emu:
        sources[e["emulator"]["code"]] = sources.get(e["emulator"]["code"], 0) + 1
    print(f"integer reference vs the emulator's floating-point decision: {same}/{len(emu)} identical "
          f"(trigger sources in these runs, 1 sensor / 2 radar / 4 watchdog: {sources})")
    print(f"integer reference vs the design intent on hand-built edge cases: {ok}/{len(intent)}")

    sys.path.insert(0, str(ROOT / "embedded"))
    import verify
    print("\n--- C compilation and replay ---")
    code = verify.main()
    if code == 2:
        print("\nThe C compile-and-replay step is pending: run `python embedded/verify.py` on a machine with a C compiler "
              "(docs/EMBEDDED.md explains how, including on Colab).")
    return 0 if code in (0, 2) else code


if __name__ == "__main__":
    raise SystemExit(main())
