"""
Evidence summary shown to the blue agent (and used to size the enumerated search).

It reports generic statistics for every numeric signal and every pair of IDs that report the
same field, for benign traffic and for the attack windows of missed attacks. It does not name
a fix: the same table is produced whatever the weakness is.
"""
import itertools
import statistics



def _values(frames, can_id, field, window=None):
    out = []
    for f in frames:
        if f.can_id != can_id:
            continue
        v = f.data.get(field)
        if isinstance(v, (int, float)) and (window is None or window[0] <= f.t_us < window[1]):
            out.append((f.data.get("seq"), v))
    return out


def numeric_ids(observations, field="distance_m"):
    """IDs that carry a numeric value for `field` in benign traffic."""
    ids = set()
    for frames, _ in observations:
        ids |= {f.can_id for f in frames if isinstance(f.data.get(field), (int, float))}
    return sorted(ids)


def _median(values, default=float("nan")):
    return statistics.median(values) if values else default


def collect(observations, can_ids, field, windows=None):
    """Per-ID step sizes, per-pair differences (matched by sequence number) over observations."""
    steps = {i: [] for i in can_ids}
    diffs = {pair: [] for pair in itertools.combinations(can_ids, 2)}
    for index, (frames, _) in enumerate(observations):
        window = windows[index] if windows else None
        series = {i: _values(frames, i, field, window) for i in can_ids}
        for i, s in series.items():
            steps[i] += [abs(b[1] - a[1]) for a, b in zip(s, s[1:])]
        for (i, j) in diffs:
            by_seq = {seq: v for seq, v in series[j] if seq is not None}
            diffs[(i, j)] += [abs(v - by_seq[seq]) for seq, v in series[i] if seq in by_seq]
    return steps, diffs


def _stat_lines(ids, steps, diffs, indent="  "):
    lines = [indent + f"{hex(i)} median |change| between consecutive frames: {_median(steps[i]):.2f}"
             for i in ids]
    lines += [indent + f"{hex(i)} vs {hex(j)} median |difference| for the same sequence number: "
              f"{_median(values):.2f}" for (i, j), values in diffs.items()]
    return lines


def describe(benign_obs, cases, field="distance_m") -> str:
    """Statistics for benign traffic and, per attack family, for the windows of missed attacks."""
    ids = numeric_ids(benign_obs, field)
    families = {}
    for c in cases:
        families.setdefault(c["family"], []).append(c)
    lines = [f"Missed hazard attacks (no in-time alarm): {len(cases)}; by family: "
             + ", ".join(f"{k} x{len(v)}" for k, v in sorted(families.items())),
             f"Signals carrying {field}: " + ", ".join(hex(i) for i in ids),
             "Benign traffic:"]
    lines += _stat_lines(ids, *collect(benign_obs, ids, field))
    for family, group in sorted(families.items()):
        windows = [c["window_us"] for c in group]
        steps, diffs = collect([(c["frames"], c["ctx"]) for c in group], ids, field, windows)
        lines.append(f"During {family} attack windows ({len(group)} missed cases):")
        lines += _stat_lines(ids, steps, diffs)
    return "\n".join(lines)
