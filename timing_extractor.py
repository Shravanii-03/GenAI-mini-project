"""
timing_extractor.py — MODULE 3: GenAI Timing Constraint Extractor (RAG-ENHANCED)

🔥 MAIN NOVELTY MODULE

Now upgraded with:
✔ RAG grounding (ISO + VSS + CAN)
✔ Deterministic fallback
✔ Structured output
✔ ISO alignment validation
"""

import json
import re
from typing import Optional
from rag_engine import rag_enriched_query


# =========================
# HEURISTIC FALLBACK
# =========================

_KEYWORD_TIMING = {
    "brake": 100,
    "emergency": 100,
    "steer": 200,
    "alert": 50,
    "abs": 20,
    "traction": 30,
    "esc": 50,
    "airbag": 15,
    "collision": 15,
    "cruise": 300,
    "pedestrian": 100
}

_ISO_BREAKDOWN_RATIO = {
    "sensor_ms": 0.10,
    "perception_ms": 0.30,
    "decision_ms": 0.20,
    "command_ms": 0.10,
    "actuator_ms": 0.30
}


def _heuristic_timing(text: str) -> Optional[dict]:

    text_lower = text.lower()

    # Extract explicit values
    ms_match = re.search(r'(\d+)\s*ms', text_lower)
    s_match = re.search(r'(\d+(?:\.\d+)?)\s*s', text_lower)

    if ms_match:
        total = int(ms_match.group(1))
    elif s_match:
        total = int(float(s_match.group(1)) * 1000)
    else:
        total = None
        for k, v in _KEYWORD_TIMING.items():
            if k in text_lower:
                total = v
                break

    if total is None:
        return None

    return {
        "total_latency_ms": total,
        "breakdown_ms": {
            k: int(v * total) for k, v in _ISO_BREAKDOWN_RATIO.items()
        },
        "source": "heuristic"
    }


# =========================
# MAIN LLM + RAG FUNCTION
# =========================

def extract_timing_llm(text: str, source_type="requirement"):

    prompt = f"""
You are an ISO 26262 automotive safety expert.

Extract timing constraints from the text below.

TEXT:
"{text}"

TASK:
1. Identify event
2. Extract total latency (ms)
3. Assign SDV component
4. Assign ASIL level
5. Break into pipeline:
   sensor → perception → decision → command → actuator

STRICT JSON OUTPUT:

{{
    "event": "<event>",
    "total_latency_ms": <int>,
    "component": "<component>",
    "asil_level": "<ASIL_A|ASIL_B|ASIL_C|ASIL_D>",
    "breakdown_ms": {{
        "sensor_ms": <int>,
        "perception_ms": <int>,
        "decision_ms": <int>,
        "command_ms": <int>,
        "actuator_ms": <int>
    }},
    "confidence": "<HIGH|MEDIUM|LOW>"
}}
"""

    try:
        # 🔥 RAG-powered LLM
        response = rag_enriched_query(prompt, text)

        start = response.find("{")
        end = response.rfind("}") + 1
        result = json.loads(response[start:end])

        result["source"] = "llm_rag"
        return result

    except Exception as e:
        print(f"[TimingExtractor] LLM failed → fallback: {e}")

        h = _heuristic_timing(text)

        if h:
            return {
                "event": "brake",
                "component": "braking_system",
                "asil_level": "ASIL_D",
                "confidence": "LOW",
                **h,
                "source": "fallback"
            }

        raise ValueError(f"Timing extraction failed: {text}")


# =========================
# PUBLIC APIs
# =========================

def extract_timing_from_requirement(req: str):
    return extract_timing_llm(req, "requirement")


def extract_timing_from_iso_rule(rule: str):
    return extract_timing_llm(rule, "iso_rule")


def extract_timing_from_code_comment(comment: str):
    return extract_timing_llm(comment, "code_comment")


def extract_timing_from_architecture(text: str):
    return extract_timing_llm(text, "architecture")


# =========================
# ISO VALIDATION
# =========================

def enrich_with_iso_rules(timing_result, iso_rules):

    component = timing_result.get("component", "")
    extracted = timing_result.get("total_latency_ms", 0)

    for rule in iso_rules:

        if component in rule.get("component", ""):

            iso_val = rule.get("max_latency_ms", 0)

            timing_result["iso_rule_id"] = rule.get("rule_id")
            timing_result["iso_limit_ms"] = iso_val

            if extracted > iso_val:
                timing_result["iso_violation"] = True
            else:
                timing_result["iso_compliant"] = True

            break

    return timing_result


# =========================
# TEST
# =========================

if __name__ == "__main__":

    test = "Brake within 100ms if obstacle detected"

    result = extract_timing_from_requirement(test)

    print("\n=== TIMING EXTRACTION ===\n")
    print(json.dumps(result, indent=2))