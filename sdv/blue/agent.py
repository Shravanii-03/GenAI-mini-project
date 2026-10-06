"""
Blue agent: an LLM proposes monitor rules from a summary of the attacks that got through.

  evidence    per-family statistics of missed attacks vs benign traffic (summary.describe)
  proposal    JSON rules in the rule language (rules.DSL_HELP)
  repair      validation errors are sent back as instructions (up to `max_repairs` times)
  verdict     the deterministic verifier; rejected rules come back as feedback in the next attempt

The LLM never decides what is accepted. A rule is deployed only if verify_rule says so.
"""
import json
import re

from sdv.blue.rules import DSL_HELP, validate_rule
from sdv.blue.summary import describe
from sdv.blue.verify import adopt_rule, uncovered, verify_rule

_PROMPT = """You are a vehicle-safety monitor engineer reviewing an emulated emergency-braking system.
Attacks on the CAN bus can still make the vehicle collide without any monitor raising an alarm in time.
Propose up to {k} monitor rules that would catch the attacks listed below without raising alarms on
normal traffic.

{dsl}

Evidence (bus-visible statistics; the benign values show what normal traffic looks like):
{evidence}
{feedback}
Reply with ONLY a JSON object: {{"rules": [ ... ]}}"""


def build_prompt(evidence: str, feedback: str = "", k: int = 3) -> str:
    feedback = f"\nPrevious proposals and why they were rejected:\n{feedback}\n" if feedback else ""
    return _PROMPT.format(k=k, dsl=DSL_HELP, evidence=evidence, feedback=feedback)


def parse_rules(reply: str):
    """Rules from the first JSON object in the reply; [] if there is none."""
    match = re.search(r"\{.*\}", reply or "", re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    rules = data.get("rules") if isinstance(data, dict) else None
    return rules if isinstance(rules, list) else []


def propose_rules(llm, evidence: str, known_ids, feedback: str = "", k: int = 3, max_repairs: int = 2):
    """Returns (valid normalised rules, number of LLM calls, validation errors seen)."""
    prompt = build_prompt(evidence, feedback, k)
    reply = llm(prompt)
    calls, seen_errors = 1, []
    for attempt in range(max_repairs + 1):
        valid, errors = [], []
        for rule in parse_rules(reply)[:k]:
            normalised, problems = validate_rule(rule, known_ids)
            if normalised:
                valid.append(normalised)
            else:
                errors.append(f"{json.dumps(rule)[:120]}: " + "; ".join(problems))
        if not parse_rules(reply):
            errors.append("the reply did not contain a JSON object with a non-empty 'rules' list")
        seen_errors += errors
        if valid or attempt == max_repairs:
            return valid, calls, seen_errors
        reply = llm(f"{prompt}\nYour previous reply was:\n{reply}\n\nIt had these problems:\n"
                    + "\n".join(f"- {e}" for e in errors) + "\n\nReturn the corrected JSON object only.")
        calls += 1
    return [], calls, seen_errors


def blue_step_llm(llm, benign_obs, cases, known_ids, fpr_cap: float = 0.02, attempts: int = 3, k: int = 3):
    """LLM-driven rule synthesis. Mutates cases' base alarms as rules are adopted.

    Returns (accepted verdicts, stats) where stats counts LLM calls and proposals.
    """
    accepted, feedback = [], []
    stats = {"llm_calls": 0, "proposals": 0, "invalid_proposals": 0, "rejected_proposals": 0, "attempts": 0}
    for _ in range(attempts):
        missing = uncovered(cases)
        if not missing:
            break
        stats["attempts"] += 1
        rules, calls, errors = propose_rules(llm, describe(benign_obs, missing), known_ids,
                                             "\n".join(feedback[-6:]), k)
        stats["llm_calls"] += calls
        stats["invalid_proposals"] += len(errors)
        for rule in rules:
            stats["proposals"] += 1
            verdict = verify_rule(rule, benign_obs, cases, known_ids, fpr_cap)
            if verdict["ok"]:
                verdict["proposal_index"] = stats["proposals"]       # proposals made up to this rule
                accepted.append(verdict)
                adopt_rule(verdict["rule"], cases)
            else:
                stats["rejected_proposals"] += 1
                feedback.append(f"- {json.dumps(verdict['rule'])}: {'; '.join(verdict['errors'])}")
    return accepted, stats
