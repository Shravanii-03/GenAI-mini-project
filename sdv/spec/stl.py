"""
Bounded-response Signal Temporal Logic.

Supported fragment (the one every timing requirement in this project reduces to):

    G( trigger -> F[lo, hi ms] response )

"Whenever the trigger holds, the response occurs between lo and hi milliseconds
later." Atoms are snake_case identifiers. Robustness of a response at latency L is
min(L - lo, hi - L): positive means satisfied, negative means violated, and the
magnitude is the slack in milliseconds. No response at all gives -inf.
"""
import math
import re
from dataclasses import dataclass

_ATOM = r"[a-z][a-z0-9_]*"
_PATTERN = re.compile(
    rf"^\s*G\s*\(\s*(?P<trigger>{_ATOM})\s*->\s*F\s*\[\s*(?P<lo>\d+(?:\.\d+)?)\s*,\s*"
    rf"(?P<hi>\d+(?:\.\d+)?)\s*(?:ms)?\s*\]\s*(?P<response>{_ATOM})\s*\)\s*$"
)


class STLSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class BoundedResponse:
    trigger: str
    response: str
    lo_ms: float
    hi_ms: float

    def robustness(self, latency_ms) -> float:
        if latency_ms is None or math.isinf(latency_ms):
            return -math.inf
        return min(latency_ms - self.lo_ms, self.hi_ms - latency_ms)

    def satisfied(self, latency_ms) -> bool:
        return self.robustness(latency_ms) >= 0

    def __str__(self):
        return format_formula(self.trigger, self.response, self.hi_ms, self.lo_ms)


def format_formula(trigger: str, response: str, deadline_ms: float, lo_ms: float = 0) -> str:
    fmt = lambda x: str(int(x)) if float(x).is_integer() else str(x)
    return f"G({trigger} -> F[{fmt(lo_ms)},{fmt(deadline_ms)} ms] {response})"


def parse(formula: str) -> BoundedResponse:
    match = _PATTERN.match(formula or "")
    if not match:
        raise STLSyntaxError(
            "formula must look like G(trigger_atom -> F[0,100 ms] response_atom) with snake_case atoms"
        )
    lo, hi = float(match["lo"]), float(match["hi"])
    if hi < lo:
        raise STLSyntaxError("upper bound must not be smaller than the lower bound")
    return BoundedResponse(match["trigger"], match["response"], lo, hi)


def robustness_of_run(formula: str, run_result) -> float:
    """Robustness of a simulated run: the trigger is the obstacle becoming a threat (t=0)
    and the response is brake onset at the run's end-to-end latency."""
    return parse(formula).robustness(run_result.e2e_latency_ms)
