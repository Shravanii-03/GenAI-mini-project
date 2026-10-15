"""
prompt_templates.py — Rich Prompt Templates for SDV Safety GenAI System
========================================================================
Every prompt:
  - Has full context (ISO rules, VSS signals, attack patterns from RAG)
  - Gives LLM clear instructions on WHEN to say CRITICAL vs HIGH vs MEDIUM
  - Returns structured JSON
  - Is grounded — LLM cannot hallucinate severity freely
"""


# ─────────────────────────────────────────────────────────────────────────────
# REQUIREMENT PARSING
# ─────────────────────────────────────────────────────────────────────────────

def get_requirement_parse_prompt(requirement: str) -> str:
    return f"""
You are an ISO 26262 automotive safety expert parsing a natural language safety requirement.

REQUIREMENT:
"{requirement}"

Extract ONLY the structure (do NOT extract timing — that is handled separately).

Rules:
- event: the safety-critical action (e.g. "brake", "steer", "alert")
- trigger: what causes it (e.g. "obstacle detected", "lane departure")
- component: the ECU/system responsible (e.g. "brake_ecu", "adas", "steering_ecu")
- iso_standard: most relevant standard (ISO 26262, ISO 21434, or both)
- event_chain: ordered list of 4 steps from sensor to actuator

Output ONLY valid JSON, no explanation:

{{
  "event": "",
  "trigger": "",
  "component": "",
  "iso_standard": "",
  "event_chain": ["sense", "detect", "decide", "actuate"]
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# TIMING EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def get_timing_extraction_prompt(text: str, iso_context: str) -> str:
    return f"""
You are an ISO 26262 timing expert for automotive safety systems.

SAFETY REQUIREMENT:
{text}

ISO 26262 REFERENCE CONTEXT:
{iso_context}

ISO 26262 ASIL timing limits (use these as ground truth):
- ASIL-D (highest): max 100ms — emergency braking, airbag, steering
- ASIL-C: max 150ms — AEB activation, lane keeping
- ASIL-B: max 200ms — driver alerts, warnings
- ASIL-A: max 500ms — comfort functions

Task:
1. Identify the ASIL level from the requirement context
2. Extract or infer the total allowed latency
3. Break it down across: sensor reading, ECU decision, actuator command

Output ONLY valid JSON:

{{
  "event": "",
  "total_latency_ms": 100,
  "component": "",
  "asil_level": "ASIL-D",
  "iso_rule_id": "",
  "breakdown_ms": {{
    "sensor_ms": 10,
    "decision_ms": 55,
    "actuator_ms": 35
  }},
  "confidence": "high",
  "reasoning": "ISO 26262 ASIL-D requires max 100ms for emergency braking"
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# THREAT REASONING — most important prompt, now properly grounded
# ─────────────────────────────────────────────────────────────────────────────

def get_threat_reasoning_prompt(parsed: dict, scenario: dict, evaluation: dict) -> str:

    delay      = scenario.get("actual_delay_ms", 0)
    max_delay  = parsed.get("max_delay_ms", 100)
    risk       = evaluation.get("risk_score", 0)
    severity   = evaluation.get("severity", "LOW")
    road       = scenario.get("parameters", {}).get("road_condition", "dry")
    cpu        = scenario.get("parameters", {}).get("ecu_cpu_load_pct", 50)
    overshoot  = max(0, delay - max_delay)
    event      = parsed.get("event", "braking")
    component  = parsed.get("component", "brake_ecu")

    # Severity grounding rules — tell LLM exactly when to use each
    severity_rules = """
SEVERITY RULES (follow exactly):
- CRITICAL: risk_score >= 1.5 OR delay > 150ms OR road is icy with violation
- HIGH:     risk_score >= 1.0 OR delay > 120ms OR attack detected
- MEDIUM:   risk_score >= 0.7 OR delay > 100ms
- LOW:      no violation, risk < 0.7
"""

    return f"""
You are an ISO 26262 + ISO 21434 automotive cybersecurity threat analyst.

INCIDENT CONTEXT:
- Safety event     : {event}
- Component        : {component}
- Actual delay     : {delay}ms
- Max allowed      : {max_delay}ms (ISO 26262 ASIL-D limit)
- Overshoot        : {overshoot}ms
- Risk score       : {risk} (scale 0-2.0, where >1.5 = CRITICAL)
- Road condition   : {road}
- ECU CPU load     : {cpu}%
- Pre-assessment   : {severity}

{severity_rules}

Based on the context above and the ISO/CAN/VSS knowledge provided, generate a realistic
automotive cyber-physical threat analysis.

The attack_chain must describe a realistic sequence of steps an attacker would take
targeting the CAN bus (0x1A0 BRAKE_CMD) or VSS signals.

Output ONLY valid JSON:

{{
  "attack_type": "can_spoofing|delay_injection|replay_attack|dos|speed_spoofing",
  "attack_chain": [
    "Step 1: attacker gains access to ...",
    "Step 2: injects ...",
    "Step 3: causes ...",
    "Step 4: results in ..."
  ],
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "tara_score": 0.0,
  "software_to_physical_impact": "delay in {event} causes ...",
  "iso_rule_violated": "ISO26262-6-8.4.5",
  "mitigation": "specific technical countermeasure"
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# EXPLANATION
# ─────────────────────────────────────────────────────────────────────────────

def get_explanation_prompt(parsed, scenarios, evaluations, threats, memory) -> str:

    total     = len(scenarios)
    viols     = sum(1 for e in evaluations if e.get("violation"))
    max_risk  = max((e.get("risk_score", 0) for e in evaluations), default=0)
    max_delay = max((s.get("actual_delay_ms", 0) for s in scenarios), default=0)
    event     = parsed.get("event", "safety event")
    limit     = parsed.get("max_delay_ms", 100)

    return f"""
You are an ISO 26262 safety engineer writing a concise incident summary.

SYSTEM UNDER TEST: {event} system (limit: {limit}ms, ASIL-D)

TEST RESULTS:
- Total scenarios tested : {total}
- Violations detected    : {viols} ({round(viols/max(total,1)*100,1)}%)
- Max risk score         : {max_risk}
- Max delay observed     : {max_delay}ms

Write exactly 4 sentences:
1. What the system was tested for and the ISO standard
2. Key finding (worst violation or confirmation of safety)
3. Root cause or threat vector identified
4. Recommended immediate action

Be technical, specific, and reference ISO 26262 where relevant.
Do NOT use bullet points. Plain sentences only.
"""


# ─────────────────────────────────────────────────────────────────────────────
# NEXT ACTION
# ─────────────────────────────────────────────────────────────────────────────

def get_next_action_prompt(parsed, evaluations, threats, memory) -> str:

    viols    = [e for e in evaluations if e.get("violation")]
    has_crit = any(t.get("severity") == "CRITICAL" for t in threats)
    roads    = list(set(e.get("road_condition", "dry") for e in evaluations))
    event    = parsed.get("event", "braking")

    return f"""
You are an autonomous safety testing agent for SDV systems.

CURRENT STATUS:
- Event under test   : {event}
- Violations found   : {len(viols)}
- Critical threats   : {"YES" if has_crit else "NO"}
- Roads tested       : {roads}

Decide the next test action. If violations were found, stress-test further.
If already critical, recommend mitigation verification.

Output ONLY valid JSON:

{{
  "next_action": "what to do next",
  "scenario_type": "normal|edge|stress",
  "target_delay_ms": 100,
  "focus_condition": "wet|icy|dry|foggy",
  "reason": "why this test is needed",
  "should_continue": true
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def get_scenario_generation_prompt(parsed: dict, scenario_type: str, memory: list) -> str:

    past_delays = [m["actual_delay_ms"] for m in memory] if memory else []
    avoid_hint  = (
        f"These delays were already tested: {past_delays}. Generate a DIFFERENT value."
        if past_delays else ""
    )

    limits = {
        "normal": "delay should be 60-90ms (within ISO limit)",
        "edge":   "delay should be 95-110ms (near the limit)",
        "stress": "delay should be 120-180ms (well over limit, simulating attack or high load)",
    }
    hint = limits.get(scenario_type, "")

    return f"""
You are a simulation engine for SDV safety testing.

SYSTEM:
- Event     : {parsed.get('event')}
- Max delay : {parsed.get('max_delay_ms')}ms (ISO 26262 ASIL-D)
- Component : {parsed.get('component')}

SCENARIO TYPE: {scenario_type}
{hint}
{avoid_hint}

Generate a realistic test scenario with proper physics:
- normal: dry road, low CPU, compliant timing
- edge: wet road, moderate CPU, near-limit timing
- stress: icy road, high CPU, over-limit timing

Output ONLY valid JSON:

{{
  "scenario_id": 1,
  "type": "{scenario_type}",
  "parameters": {{
    "vehicle_speed_kmh": 60,
    "road_condition": "dry",
    "ecu_cpu_load_pct": 40,
    "weather": "clear"
  }},
  "event_chain_timing": [
    {{"step": "sense",   "time_ms": 10}},
    {{"step": "detect",  "time_ms": 25}},
    {{"step": "decide",  "time_ms": 45}},
    {{"step": "actuate", "time_ms": 80}}
  ],
  "actual_delay_ms": 80,
  "simulated_violation": false
}}
"""