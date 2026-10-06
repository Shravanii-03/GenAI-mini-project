"""
A small, checkable monitor language.

Rules are plain JSON so an LLM can propose them and a deterministic verifier can
validate, compile and test them. Four rule types:

  cross_check  two IDs report the same field (e.g. two independent distance sensors);
               alarm when they disagree by more than tol within max_skew_ms
  jump         alarm when consecutive values of one ID's field change by more than max_step
  drift        alarm when a field rises by more than slack over `window` frames
               (distance to an approaching obstacle must fall)
  range        alarm when a field leaves [lo, hi]

Every message returned by `validate_rule` is written as an instruction, so the same list
drives a repair prompt.
"""
from sdv.monitors.monitors import Monitor

FIELDS = ("distance_m", "speed_ms")

PARAMS = {
    "cross_check": {"tol": (0.3, 20.0), "max_skew_ms": (1.0, 50.0)},
    "jump": {"max_step": (0.3, 20.0)},
    "drift": {"window": (3, 30), "slack_m": (0.0, 5.0)},
    "range": {"lo": (-5.0, 300.0), "hi": (-5.0, 300.0)},
}
ID_KEYS = {"cross_check": ("id_a", "id_b"), "jump": ("id",), "drift": ("id",), "range": ("id",)}

DSL_HELP = """\
Rule types (JSON objects). Use CAN IDs as hex strings such as "0x2A0".
  {"type":"cross_check","id_a":"0x..","id_b":"0x..","field":"distance_m","tol":<0.3-20>,"max_skew_ms":<1-50>}
      two IDs reporting the same field must agree within tol
  {"type":"jump","id":"0x..","field":"distance_m","max_step":<0.3-20>}
      consecutive values of one ID's field may not change by more than max_step
  {"type":"drift","id":"0x..","field":"distance_m","window":<3-30 frames>,"slack_m":<0-5>}
      the field may not rise by more than slack_m over `window` frames
  {"type":"range","id":"0x..","field":"distance_m","lo":<number>,"hi":<number>}
Allowed fields: distance_m, speed_ms."""


def normalise_id(value) -> str:
    """CAN IDs as upper-case hex strings, whether given as 672, "0x2a0" or "0x2A0"."""
    if isinstance(value, int) and not isinstance(value, bool):
        return "0x%X" % value
    text = str(value).strip()
    return "0x" + text[2:].upper() if text.lower().startswith("0x") else text


def validate_rule(rule: dict, known_ids):
    """Returns (normalised rule or None, [instruction-style errors])."""
    errors = []
    if not isinstance(rule, dict):
        return None, ["a rule must be a JSON object"]
    kind = rule.get("type")
    if kind not in PARAMS:
        return None, [f"unknown rule type {kind!r}; use one of {sorted(PARAMS)}"]
    known = {normalise_id(i) for i in known_ids}
    out = {"type": kind}
    for key in ID_KEYS[kind]:
        value = normalise_id(rule.get(key, ""))
        if value not in known:
            errors.append(f"{key}={value!r} is not a CAN ID seen on the bus; choose from {sorted(known)}")
        out[key] = value
    if kind == "cross_check" and out.get("id_a") == out.get("id_b"):
        errors.append("cross_check needs two different IDs")
    field = rule.get("field")
    if field not in FIELDS:
        errors.append(f"field {field!r} is not allowed; use one of {list(FIELDS)}")
    out["field"] = field
    for key, (lo, hi) in PARAMS[kind].items():
        value = rule.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{key} must be a number between {lo} and {hi}")
        elif not lo <= value <= hi:
            errors.append(f"{key}={value} is outside the allowed range {lo}..{hi}")
        else:
            out[key] = int(value) if key == "window" else float(value)
    extra = set(rule) - set(out) - set(PARAMS[kind]) - set(ID_KEYS[kind]) - {"type", "field"}
    if extra:
        errors.append(f"unknown keys {sorted(extra)}; remove them")
    if kind == "range" and not errors and out["lo"] >= out["hi"]:
        errors.append("range needs lo < hi")
    return (None if errors else out), errors


class RuleMonitor(Monitor):
    """A compiled rule. Sees only bus-visible fields, like every other monitor."""

    def __init__(self, rule: dict):
        self.rule = dict(rule)
        self.name = "rule:" + rule["type"]

    def _series(self, frames, can_id, field):
        return [(f.t_us, f.data.get(field)) for f in frames if f.can_id == int(can_id, 16)
                and isinstance(f.data.get(field), (int, float))]

    def first_alarm_us(self, frames, ctx):
        kind, r = self.rule["type"], self.rule
        if kind == "cross_check":
            return self._cross_check(frames, r)
        series = self._series(frames, r["id"], r["field"])
        if kind == "jump":
            for (_, a), (t, b) in zip(series, series[1:]):
                if abs(b - a) > r["max_step"]:
                    return t
        elif kind == "drift":
            n = r["window"]
            for i in range(n, len(series)):
                if series[i][1] - series[i - n][1] > r["slack_m"]:
                    return series[i][0]
        elif kind == "range":
            for t, v in series:
                if v < r["lo"] or v > r["hi"]:
                    return t
        return None

    def _cross_check(self, frames, r):
        a_id, b_id = int(r["id_a"], 16), int(r["id_b"], 16)
        skew = int(r["max_skew_ms"] * 1000)
        last = {a_id: None, b_id: None}
        for f in frames:
            value = f.data.get(r["field"])
            if f.can_id not in last or not isinstance(value, (int, float)):
                continue
            last[f.can_id] = (f.t_us, value)
            other = last[b_id if f.can_id == a_id else a_id]
            if other and abs(f.t_us - other[0]) <= skew and abs(value - other[1]) > r["tol"]:
                return f.t_us
        return None


def compile_rule(rule: dict, known_ids):
    """Returns (RuleMonitor or None, errors)."""
    normalised, errors = validate_rule(rule, known_ids)
    return (RuleMonitor(normalised), []) if normalised else (None, errors)
