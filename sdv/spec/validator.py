"""
Deterministic validator for extracted specifications.

Every message is written as an instruction the LLM can act on, so the same list
drives the repair loop. Nothing here calls a model.
"""
import math

from pydantic import ValidationError

from sdv.rag.kb import kb_ids
from sdv.spec import stl
from sdv.spec.schema import COMPONENTS, TimingSpec

MAX_DEADLINE_MS = 60_000


def normalise_can_id(value: str) -> str:
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return "0x" + text[2:].upper()
    return text


def validate(raw: dict, ids: dict = None):
    """Returns (spec or None, [error messages])."""
    ids = ids or kb_ids()
    try:
        spec = TimingSpec.model_validate(raw)
    except ValidationError as error:
        problems = [f"field '{'.'.join(map(str, e['loc']))}': {e['msg']}" for e in error.errors()]
        return None, ["the JSON does not match the schema: " + "; ".join(problems)]

    errors = []
    if spec.component not in COMPONENTS:
        errors.append(f"component '{spec.component}' is not allowed; choose one of {list(COMPONENTS)}")

    if spec.deadline_ms is not None:
        if not math.isfinite(spec.deadline_ms) or not 0 < spec.deadline_ms <= MAX_DEADLINE_MS:
            errors.append(f"deadline_ms={spec.deadline_ms} is not a plausible value in milliseconds "
                          f"(expected 0 < value <= {MAX_DEADLINE_MS}); convert seconds to milliseconds")
        if spec.unresolved:
            errors.append("unresolved=true but deadline_ms is set; use null when the timing is vague")
    if spec.deadline_ms is None and spec.formula:
        errors.append("formula must be null when deadline_ms is null")
    if spec.deadline_ms is not None and not spec.formula:
        errors.append("formula is required when deadline_ms is set")
    if spec.formula:
        try:
            parsed = stl.parse(spec.formula)
            if spec.deadline_ms is not None and (parsed.lo_ms != 0 or abs(parsed.hi_ms - spec.deadline_ms) > 1e-6):
                errors.append(f"formula bounds [{parsed.lo_ms},{parsed.hi_ms}] ms do not match "
                              f"deadline_ms={spec.deadline_ms}; use F[0,{spec.deadline_ms:g} ms]")
        except stl.STLSyntaxError as error:
            errors.append(f"formula is invalid: {error}")

    unknown = [s for s in spec.vss_signals if s not in ids["vss"]]
    if unknown:
        errors.append(f"VSS signals {unknown} are not in the knowledge base; "
                      "list only signals that exist there, or leave the list empty")
    spec.can_ids = [normalise_can_id(c) for c in spec.can_ids]
    unknown = [c for c in spec.can_ids if c not in ids["can"]]
    if unknown:
        errors.append(f"CAN IDs {unknown} are not in the knowledge base; "
                      "list only IDs that exist there, or leave the list empty")
    return spec, errors
