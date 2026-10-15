"""
Compare two reproduce_all.py logs, step by step, ignoring run times.

    python experiments/compare_logs.py outputs/logs/reproduce_all_previous.log outputs/logs/reproduce_all.log

Prints, for every step, whether its output is identical, and a short diff for the steps that differ. Exit code 0 when every
step present in both logs is identical, 1 otherwise. Steps present in only one log are reported but do not fail the comparison.
"""
import difflib
import re
import sys

STEP = re.compile(r"^=== (.+)$")
TIMING = [(re.compile(r"\b(ok|FAILED \(exit \d+\)) in \d+s"), r"\1"),
          (re.compile(r"total time \d+s"), "total time"),
          (re.compile(r";\s*\d+s$"), ""),
          (re.compile(r"\(\d+(\.\d+)?s\)")  , "")]


def normalise(line: str) -> str:
    line = line.rstrip()
    for pattern, repl in TIMING:
        line = pattern.sub(repl, line)
    return line


def split_steps(text: str) -> dict:
    steps, current = {}, None
    for raw in text.splitlines():
        match = STEP.match(raw)
        if match:
            current = match.group(1).strip()
            steps[current] = []
            continue
        if current is None or set(raw.strip()) <= {"="} or raw.startswith("--- "):
            continue
        line = normalise(raw)
        if line:
            steps[current].append(line)
    return steps


def compare(old_text: str, new_text: str) -> dict:
    old, new = split_steps(old_text), split_steps(new_text)
    report = {"identical": [], "different": {}, "only_old": [], "only_new": []}
    for title in old:
        if title not in new:
            report["only_old"].append(title)
        elif old[title] == new[title]:
            report["identical"].append(title)
        else:
            diff = [d for d in difflib.unified_diff(old[title], new[title], "old", "new", lineterm="", n=0)
                    if not d.startswith(("---", "+++", "@@"))]
            report["different"][title] = diff
    report["only_new"] = [t for t in new if t not in old]
    return report


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    old = open(argv[0], encoding="utf-8", errors="replace").read()
    new = open(argv[1], encoding="utf-8", errors="replace").read()
    report = compare(old, new)
    print(f"identical steps: {len(report['identical'])}")
    for title in report["identical"]:
        print(f"  = {title}")
    for title, diff in report["different"].items():
        print(f"\nDIFFERENT: {title}  ({len(diff)} differing lines)")
        for line in diff[:12]:
            print("   ", line[:170])
    for title in report["only_old"]:
        print(f"only in the old log: {title}")
    for title in report["only_new"]:
        print(f"only in the new log: {title}")
    return 1 if report["different"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
