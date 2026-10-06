"""
Spec agent: natural-language requirement -> validated timing specification.

Conditions it supports (the ablation axes):
  retriever=None    the LLM must name signals and CAN IDs from memory
  retriever=<obj>   candidate VSS signals and CAN messages are retrieved and shown
  validate=False    first reply is used as is
  validate=True    a deterministic validator checks the reply and its messages are sent
                    back for up to `max_repairs` repair attempts
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from sdv.rag.kb import kb_ids
from sdv.spec.schema import FIELDS_HELP
from sdv.spec.validator import validate as validate_spec

_TASK = """You convert a natural-language automotive timing requirement into a structured specification.

Rules
- deadline_ms: the overall end-to-end deadline in MILLISECONDS. Convert units (1 s = 1000 ms) and do any
  arithmetic the text requires. If a total budget is split into parts, give the total. Use null when the
  text states no timing requirement.
- unresolved: true only when timing is asked for in vague words ("promptly", "as soon as possible") and no
  number can be derived. Then deadline_ms must be null.
- trigger and response: short snake_case events (for example obstacle_detected, brake_applied).
- vss_signals / can_ids: {grounding}
- formula: G(trigger -> F[0,D ms] response) where D is deadline_ms, or null when deadline_ms is null.

Reply with ONLY one JSON object with exactly these fields:
{fields}
{context}
Requirement: "{text}"
"""

_GROUND_RAG = ("choose ONLY from the candidates listed below, and only those the requirement names or "
               "clearly implies; use [] if none apply.")
_GROUND_NONE = ("list only items the requirement names or clearly implies, and only if you are certain "
                "they exist; otherwise use [].")


def build_prompt(text: str, vss_docs=None, can_docs=None) -> str:
    context = ""
    if vss_docs is not None:
        context += "\nCandidate VSS signals:\n" + "\n".join(
            f"- {d.id}: {d.text[len(d.id):].strip()}" for d in vss_docs)
        context += "\nCandidate CAN messages:\n" + "\n".join(f"- {d.id} {d.title}" for d in (can_docs or []))
        context += "\n"
    return _TASK.format(grounding=_GROUND_RAG if vss_docs is not None else _GROUND_NONE,
                        fields=FIELDS_HELP, context=context, text=text)


def build_repair_prompt(prompt: str, previous_reply: str, errors: List[str]) -> str:
    return (f"{prompt}\nYour previous reply was:\n{previous_reply}\n\n"
            "A validator found these problems:\n" + "\n".join(f"- {e}" for e in errors) +
            "\n\nReturn the corrected JSON object only.")


def extract_json(reply: str) -> Optional[dict]:
    """First balanced {...} object in the reply, tolerating code fences and extra prose."""
    reply = re.sub(r"```(?:json)?", "", reply or "")
    start = reply.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(reply)):
            depth += reply[end] == "{"
            depth -= reply[end] == "}"
            if depth == 0:
                try:
                    obj = json.loads(reply[start:end + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    break
        start = reply.find("{", start + 1)
    return None


@dataclass
class SpecResult:
    spec: Optional[dict]
    valid: bool
    errors_initial: List[str] = field(default_factory=list)
    errors_final: List[str] = field(default_factory=list)
    repairs: int = 0
    llm_calls: int = 0
    raw_first_reply: str = ""
    retrieved_vss: List[str] = field(default_factory=list)
    retrieved_can: List[str] = field(default_factory=list)


def extract_spec(text: str, llm, retriever=None, validate: bool = True, max_repairs: int = 2,
                 k_vss: int = 8, k_can: int = 5, ids: dict = None) -> SpecResult:
    ids = ids or kb_ids()
    vss_docs = can_docs = None
    if retriever is not None:
        vss_docs = retriever.retrieve(text, "vss", k_vss)
        can_docs = retriever.retrieve(text, "can", k_can)
    prompt = build_prompt(text, vss_docs, can_docs)
    result = SpecResult(
        spec=None, valid=False,
        retrieved_vss=[d.id for d in vss_docs or []], retrieved_can=[d.id for d in can_docs or []],
    )

    reply = llm(prompt)
    result.llm_calls, result.raw_first_reply = 1, reply
    for attempt in range(max_repairs + 1):
        raw = extract_json(reply)
        if raw is None:
            errors = ["the reply did not contain a JSON object"]
            spec = None
        else:
            spec, errors = validate_spec(raw, ids)
        if attempt == 0:
            result.errors_initial = list(errors)
        result.spec = spec.model_dump() if spec is not None else None
        result.errors_final = list(errors)
        if not errors:
            result.valid = True
            break
        if not validate or attempt == max_repairs:
            break
        reply = llm(build_repair_prompt(prompt, reply, errors))
        result.llm_calls += 1
        result.repairs += 1
    return result
