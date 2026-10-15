"""
parser.py — Requirement Understanding (GenAI + RAG)

Role:
✔ Extract semantic structure (event, trigger, component, event_chain)
✔ Uses RAG context (ISO 26262 + VSS + CAN)
❌ DOES NOT extract timing (handled separately)

This makes parsing:
- grounded in automotive knowledge
- less hallucinated
- paper-worthy
"""

import json
from rag_engine import rag_enriched_query


def parse_requirement(requirement: str) -> dict:
    """
    Extract semantic structure from requirement using RAG + LLM.
    """

    prompt = f"""
You are an automotive safety analyst.

Your job is to understand the SYSTEM LOGIC of the requirement.

Requirement:
"{requirement}"

Extract ONLY STRUCTURE (NOT timing).

OUTPUT STRICT JSON:

{{
  "event": "<main action>",
  "trigger": "<what triggers the event>",
  "component": "<system component>",
  "event_chain": ["<step1>", "<step2>", "<step3>", "<step4>"]
}}

RULES:
- DO NOT include timing values
- Use automotive terminology (ADAS, braking ECU, sensor fusion, etc.)
- Event chain must follow real SDV pipeline:
  sensing → detection → decision → actuation
- Return ONLY JSON
"""

    try:
        # 🔥 RAG + LLM call
        response = rag_enriched_query(prompt, requirement)

        # Extract JSON safely
        start = response.find("{")
        end = response.rfind("}") + 1
        parsed = json.loads(response[start:end])

        # Validate structure
        required = ["event", "trigger", "component", "event_chain"]
        for field in required:
            if field not in parsed:
                raise ValueError(f"Missing field: {field}")

        return parsed

    except Exception as e:
        print(f"[Parser Warning] Fallback triggered: {e}")

        return {
            "event": "brake",
            "trigger": "obstacle_detected",
            "component": "braking_system",
            "event_chain": [
                "sensor_input",
                "object_detection",
                "decision_logic",
                "brake_actuation"
            ],
            "source": "fallback"
        }