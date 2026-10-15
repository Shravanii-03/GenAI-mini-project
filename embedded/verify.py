"""
verify.py - compile the embedded C port, replay the recorded cases and check it against the reference.

Standard library only, so it runs on any machine that has a C compiler (for example a Colab runtime):

    python3 embedded/verify.py                # uses embedded/cases/cases.txt and expected.json
    CC=clang python3 embedded/verify.py       # choose a compiler

Checks
  1. the module compiles cleanly with -std=c99 -Wall -Wextra -Wpedantic -Werror
  2. static: no floating point, no dynamic allocation, no libc calls in the module
  3. the compiled port makes EXACTLY the same decision as the integer reference on every case (code, time, rejected frames)
  4. hand-built edge cases match the design intent
  5. agreement with the emulator's own floating-point decisions (differences can only come from rounding to mm)
Reports code size, state size and a host timing (the host figure says nothing about an MCU).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORBIDDEN = re.compile(r"\b(float|double|malloc|calloc|realloc|free|printf|fprintf|sprintf|memcpy|memset|strlen|math\.h|stdlib\.h|stdio\.h)\b")


def find_compiler():
    if os.environ.get("CC"):
        return os.environ["CC"].split()
    for name in ("gcc", "cc", "clang", "tcc"):
        if shutil.which(name):
            return [name]
    try:
        subprocess.run([sys.executable, "-m", "ziglang", "version"], capture_output=True, check=True)
        return [sys.executable, "-m", "ziglang", "cc"]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def static_checks():
    problems = []
    for name in ("sdv_defences.c", "sdv_defences.h"):
        for number, line in enumerate((HERE / name).read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("/*")[0].split("//")[0]
            match = FORBIDDEN.search(code)
            if match and not code.strip().startswith("*"):
                problems.append(f"{name}:{number}: {match.group(0)}")
    return problems


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def object_size(cc, build):
    """text/data/bss of the module compiled for the host with -Os, if a `size` tool exists."""
    obj = build / "sdv_defences.o"
    result = run(cc + ["-std=c99", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-Os", "-ffunction-sections",
                       "-c", str(HERE / "sdv_defences.c"), "-o", str(obj)])
    if result.returncode:
        return None, result.stderr
    tool = shutil.which("size")
    if tool:
        out = run([tool, str(obj)]).stdout.splitlines()
        if len(out) >= 2:
            fields = out[1].split()
            return {"text": int(fields[0]), "data": int(fields[1]), "bss": int(fields[2]), "tool": "size"}, ""
    return {"object_file_bytes": obj.stat().st_size, "tool": "file size (no `size` tool)"}, ""


def main(argv=None):
    cases = HERE / "cases" / "cases.txt"
    expected = json.loads((HERE / "cases" / "expected.json").read_text(encoding="utf-8"))
    report = {"compiler": None}
    problems = static_checks()
    print("static check (no float, no allocation, no libc in the module): " + ("OK" if not problems else "FAILED"))
    for p in problems:
        print("  ", p)
    cc = find_compiler()
    if cc is None:
        print("no C compiler found (set CC, or install gcc/clang); nothing was compiled")
        return 2
    report["compiler"] = " ".join(cc)
    version = run(cc + ["--version"]).stdout.splitlines()
    print("compiler:", version[0] if version else cc)
    build = HERE / "build"
    build.mkdir(exist_ok=True)
    size, err = object_size(cc, build)
    if size is None:
        print("COMPILE FAILED (module, strict flags):\n" + err)
        return 1
    print("module compiles cleanly with -std=c99 -Wall -Wextra -Wpedantic -Werror")
    exe = build / ("harness.exe" if os.name == "nt" else "harness")
    built = run(cc + ["-std=c99", "-Wall", "-Wextra", "-Os", "-I", str(HERE), "-o", str(exe),
                      str(HERE / "sdv_defences.c"), str(HERE / "harness.c")])
    if built.returncode:
        print("COMPILE FAILED (harness):\n" + built.stderr)
        return 1
    sizes = run([str(exe), "--sizeof"]).stdout.strip()
    results = {}
    for line in run([str(exe), str(cases)]).stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "RESULT":
            results[parts[1]] = {"code": int(parts[2]), "t_us": int(parts[3]), "rejected": int(parts[4])}

    same = intent_ok = emu_same = emu_total = 0
    mismatches, emu_diff = [], []
    synthetic = 0
    for name, exp in expected.items():
        got = results.get(name)
        ref = exp["reference"]
        if got == ref:
            same += 1
        else:
            mismatches.append((name, got, ref))
        if exp.get("intent") is not None:
            synthetic += 1
            intent_ok += int(got is not None and (got["code"], got["t_us"]) == (exp["intent"]["code"], exp["intent"]["t_us"]))
        if exp.get("emulator") is not None:
            emu_total += 1
            emu = exp["emulator"]
            if got is not None and (got["code"], got["t_us"]) == (emu["code"], emu["t_us"]):
                emu_same += 1
            else:
                emu_diff.append((name, got, emu))
    bench = run([str(exe), "--bench", "5000000"]).stdout.strip()

    print(f"\ncases replayed: {len(expected)} ({emu_total} from emulator runs, {synthetic} hand-built edge cases)")
    print(f"C port == integer reference (code, time, rejected frames): {same}/{len(expected)}")
    print(f"hand-built edge cases matching the design intent:         {intent_ok}/{synthetic}")
    print(f"C port == emulator's floating-point decision:             {emu_same}/{emu_total}")
    for name, got, emu in emu_diff[:5]:
        print(f"   differs: {name}: C {got} vs emulator {emu}")
    print("\nfootprint (host build, -Os; indicative only, an MCU build differs):")
    print("  module:", size)
    print("  " + sizes)
    print("  " + bench + "   (host CPU, not an MCU)")
    report.update({"cases": len(expected), "c_equals_reference": same, "intent_ok": intent_ok, "synthetic": synthetic,
                   "c_equals_emulator": emu_same, "emulator_cases": emu_total, "module_size": size, "sizeof": sizes,
                   "bench": bench})
    (build / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    ok = not problems and not mismatches and intent_ok == synthetic
    print("\nRESULT:", "PASS" if ok else "FAIL")
    for name, got, ref in mismatches[:8]:
        print(f"  mismatch {name}: C {got} vs reference {ref}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
