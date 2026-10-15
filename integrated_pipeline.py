"""
integrated_pipeline.py — FULLY CONNECTED Pipeline
═══════════════════════════════════════════════════
This is the REAL pipeline where everything connects:

1. Parse actual SDV code → extract real VSS/CAN signals
2. RAG validates those signals against VSS catalog
3. Timing extractor gets constraints from ISO rules
4. Agent1 reasons about the ACTUAL signals found
5. Temporal validator checks real event chain order
6. Threat generator uses actual CAN IDs found in code
7. Diagrams generated from actual analysis

Run:
    python integrated_pipeline.py --code datasets/code_samples/brake_python.py
    python integrated_pipeline.py --code datasets/code_samples/brake_cpp.cpp
    python integrated_pipeline.py --code datasets/code_samples/brake_rust.rs
"""

import os, sys, json, argparse
from datetime import datetime

# ── imports ───────────────────────────────────────────────────────────
from llm_client import query_llm
from rag_engine import (
    build_rag_context, load_vss_signals, load_can_messages,
    load_iso_rules, load_attack_patterns, retrieve
)
from multi_lang_parser import parse_sdv_code
from timing_extractor import extract_timing_from_requirement, enrich_with_iso_rules
from temporal_validator import validate_timing, validate_event_chain_order
from threat_generator import generate_topology_threat
from diagram_renderer import render_from_pipeline_json
from memory import AgentMemory


def _banner(t):
    print(f"\n{'═'*60}\n  {t}\n{'═'*60}")

def _section(t):
    print(f"\n{'─'*55}\n  {t}\n{'─'*55}")

def save_output(data, label="integrated"):
    os.makedirs("outputs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"outputs/{label}_{ts}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Output saved: {path}")
    return path


# ══════════════════════════════════════════════════════════════════════
# STEP 1: Parse actual SDV code
# ══════════════════════════════════════════════════════════════════════

def step1_parse_code(filepath: str) -> dict:
    """Read actual code file and extract VSS/CAN signals using LLM."""
    _section("STEP 1: Parsing SDV Code File")
    print(f"  File: {filepath}")

    with open(filepath, encoding="utf-8") as f:
        code = f.read()

    lang = "python" if filepath.endswith(".py") else \
           "cpp"    if filepath.endswith(".cpp") else \
           "rust"   if filepath.endswith(".rs") else "python"

    result = parse_sdv_code(code, filename=os.path.basename(filepath))

    print(f"  Language:         {result['language']}")
    print(f"  CAN IDs found:    {result['can_ids']}")
    print(f"  VSS signals:      {result['vss_signals'][:5]}")
    print(f"  Functions:        {result['safety_functions']}")
    print(f"  Event chain:      {' → '.join(result['event_chain'])}")
    print(f"  Timing constants: {result['timing_constants_ms']}")

    return result


# ══════════════════════════════════════════════════════════════════════
# STEP 2: RAG — validate signals against knowledge base
# ══════════════════════════════════════════════════════════════════════

def step2_rag_validate(code_result: dict) -> dict:
    """
    Validate extracted VSS/CAN signals against the knowledge base.
    This is what the paper does — check signals actually exist in catalog.
    """
    _section("STEP 2: RAG Signal Validation")

    vss_catalog  = load_vss_signals()
    can_catalog  = load_can_messages()
    catalog_paths = {s["path"] for s in vss_catalog}
    catalog_ids   = {m["id"] for m in can_catalog}

    # Validate VSS signals
    validated_vss = []
    invalid_vss   = []
    for sig in code_result["vss_signals"]:
        if sig in catalog_paths:
            validated_vss.append(sig)
            print(f"  VSS OK:     {sig}")
        else:
            # Try partial match
            partial = [p for p in catalog_paths if sig.split(".")[-1] in p]
            if partial:
                validated_vss.append(partial[0])
                print(f"  VSS MATCH:  {sig} → {partial[0]}")
            else:
                invalid_vss.append(sig)
                print(f"  VSS MISS:   {sig} (not in catalog)")

    # Validate CAN IDs
    validated_can = []
    invalid_can   = []
    for cid in code_result["can_ids"]:
        if cid in catalog_ids:
            validated_can.append(cid)
            msg = next(m for m in can_catalog if m["id"] == cid)
            print(f"  CAN OK:     {cid} = {msg['name']} ({msg['description'][:40]})")
        else:
            invalid_can.append(cid)
            print(f"  CAN MISS:   {cid} (not in catalog)")

    # Get relevant ISO rules for detected component
    iso_rules = retrieve(code_result["component"], "iso", top_k=3)
    attack_patterns = retrieve(code_result["component"], "attack", top_k=3)

    print(f"\n  Validated VSS: {len(validated_vss)}/{len(code_result['vss_signals'])}")
    print(f"  Validated CAN: {len(validated_can)}/{len(code_result['can_ids'])}")
    print(f"  Relevant ISO rules: {[r.get('rule_id') for r in iso_rules]}")
    print(f"  Known attack patterns: {[a.get('name') for a in attack_patterns]}")

    return {
        "validated_vss":    validated_vss,
        "invalid_vss":      invalid_vss,
        "validated_can":    validated_can,
        "invalid_can":      invalid_can,
        "iso_rules":        iso_rules,
        "attack_patterns":  attack_patterns,
        "rag_context":      build_rag_context(
            " ".join(validated_vss[:3] + [code_result["component"]]), top_k=3
        )
    }


# ══════════════════════════════════════════════════════════════════════
# STEP 3: Extract timing from code + ISO rules
# ══════════════════════════════════════════════════════════════════════

def step3_timing(code_result: dict, rag_result: dict) -> dict:
    """
    Extract timing constraints from:
    - Constants found in the actual code
    - ISO 26262 rules from RAG
    """
    _section("STEP 3: Timing Constraint Extraction")

    # Get from code constants first
    code_timing_ms = code_result["timing_constants_ms"]
    component      = code_result["component"]

    # Get from ISO rules
    iso_timing = None
    for rule in rag_result["iso_rules"]:
        if rule.get("max_latency_ms"):
            iso_timing = rule
            break

    # Use code timing if available, else ISO
    if code_timing_ms:
        max_latency = min(code_timing_ms)  # most strict constraint
        source = "code"
    elif iso_timing:
        max_latency = iso_timing["max_latency_ms"]
        source = f"ISO rule {iso_timing['rule_id']}"
    else:
        # Ask LLM to extract from component name
        t = extract_timing_from_requirement(
            f"{component} safety timing constraint"
        )
        max_latency = t.get("total_latency_ms", 100)
        source = "llm_inference"

    print(f"  Component:      {component}")
    print(f"  Max latency:    {max_latency}ms (from {source})")
    if iso_timing:
        print(f"  ISO rule:       {iso_timing.get('rule_id')}")
        print(f"  ASIL level:     {iso_timing.get('asil_level')}")
        print(f"  Breakdown:      {iso_timing.get('breakdown', {})}")

    return {
        "max_latency_ms": max_latency,
        "source":         source,
        "iso_rule":       iso_timing,
        "code_constants": code_timing_ms
    }


# ══════════════════════════════════════════════════════════════════════
# STEP 4: LLM analyzes the actual code with RAG context
# ══════════════════════════════════════════════════════════════════════

def step4_llm_code_analysis(code_result: dict, rag_result: dict,
                             timing: dict, filepath: str) -> dict:
    """
    LLM reads the actual code WITH RAG context.
    This is Prompt Construct 1+2 from the paper.
    """
    _section("STEP 4: LLM Code Analysis (RAG-grounded)")

    with open(filepath, encoding="utf-8") as f:
        code = f.read()

    # Build grounded prompt (paper's approach)
    prompt = f"""
You are analyzing SDV (Software-Defined Vehicle) code for functional safety.
This is aligned with the TUM paper "LLM-Empowered Functional Safety by Design".

{rag_result['rag_context']}

CODE TO ANALYZE ({code_result['language'].upper()}):
```
{code[:2500]}
```

EXTRACTED SIGNALS (validated against VSS/CAN catalog):
- VSS signals: {rag_result['validated_vss']}
- CAN message IDs: {rag_result['validated_can']}
- Safety functions: {code_result['safety_functions']}
- Timing constraint: {timing['max_latency_ms']}ms max

Based on this ACTUAL code and validated signals, perform:

1. EVENT CHAIN: List the exact sequence of events this code performs
   (use the actual function names from the code)

2. TIMING ANALYSIS: For each step, estimate time in ms based on code complexity
   Total must relate to the {timing['max_latency_ms']}ms constraint

3. SAFETY VIOLATIONS: Does the code violate any ISO 26262 event ordering rules?
   Check: does sense happen before detect? detect before decide? decide before actuate?

4. SIGNAL VALIDITY: Any VSS/CAN signals used incorrectly?

Output STRICT JSON only. No markdown.

{{
    "event_chain": ["<step1 from actual code>", "<step2>", "<step3>", "<step4>"],
    "event_chain_timing": [
        {{"step": "<name>", "time_ms": <int>, "function": "<actual function name>"}}
    ],
    "total_estimated_ms": <int>,
    "safety_violations": [
        {{"rule": "<ISO rule>", "description": "<what is wrong in code>"}}
    ],
    "signal_issues": ["<any signal used incorrectly>"],
    "overall_verdict": "<SAFE|UNSAFE|NEEDS_REVIEW>",
    "explanation": "<2 sentence summary of findings>"
}}
"""

    response = query_llm(prompt, temperature=0.2)
    try:
        start = response.find("{")
        end   = response.rfind("}") + 1
        result = json.loads(response[start:end])
        print(f"  Event chain:     {' → '.join(result.get('event_chain', []))}")
        print(f"  Estimated time:  {result.get('total_estimated_ms')}ms")
        print(f"  Verdict:         {result.get('overall_verdict')}")
        print(f"  Violations:      {len(result.get('safety_violations', []))}")
        if result.get("safety_violations"):
            for v in result["safety_violations"]:
                print(f"    ⚠ {v.get('description')}")
        return result
    except Exception as e:
        print(f"  LLM parse failed: {e}")
        return {
            "event_chain": code_result["event_chain"],
            "event_chain_timing": [],
            "total_estimated_ms": timing["max_latency_ms"],
            "safety_violations": [],
            "overall_verdict": "NEEDS_REVIEW",
            "explanation": "Manual review required"
        }


# ══════════════════════════════════════════════════════════════════════
# STEP 5: Temporal validation of event chain
# ══════════════════════════════════════════════════════════════════════

def step5_temporal_validate(llm_analysis: dict, timing: dict,
                             rag_result: dict) -> dict:
    """Validate event chain ordering + timing against ISO rules."""
    _section("STEP 5: Temporal Validation")

    chain_timing  = llm_analysis.get("event_chain_timing", [])
    event_chain   = llm_analysis.get("event_chain", [])
    estimated_ms  = llm_analysis.get("total_estimated_ms", 0)
    max_ms        = timing["max_latency_ms"]
    iso_rules     = rag_result.get("iso_rules", [])

    # Timing check
    timing_result = validate_timing(max_ms, estimated_ms, chain_timing)
    print(f"  Timing verdict:  {timing_result['verdict']}")
    print(f"  Risk score:      {timing_result['risk_score']}")
    print(f"  Margin:          {timing_result['margin_ms']}ms")

    # Event chain order check
    ec_rules = [r for r in iso_rules if "rule" in r]
    order_violations = validate_event_chain_order(event_chain, ec_rules)
    if order_violations:
        print(f"  Order violations:")
        for v in order_violations:
            print(f"    ⚠ [{v['rule_id']}] {v['violation']}")
    else:
        print(f"  Event chain order: OK")

    return {
        **timing_result,
        "chain_order_violations": order_violations,
        "event_chain": event_chain
    }


# ══════════════════════════════════════════════════════════════════════
# STEP 6: Threat analysis using actual signals found
# ══════════════════════════════════════════════════════════════════════

def step6_threat_analysis(code_result: dict, rag_result: dict,
                          validation: dict, timing: dict) -> dict:
    """
    Generate threats based on ACTUAL CAN IDs and VSS signals found in code.
    """
    _section("STEP 6: Threat Analysis (based on actual signals)")

    component      = code_result["component"]
    validated_can  = rag_result["validated_can"]
    attack_patterns = rag_result["attack_patterns"]

    # Show which attack patterns match the actual CAN IDs found
    print(f"  CAN IDs in code: {validated_can}")
    for pattern in attack_patterns:
        target_ids = pattern.get("target_can_ids", [])
        matched    = [cid for cid in validated_can if cid in target_ids]
        if matched:
            print(f"  MATCH: {pattern['name']} targets {matched} → {pattern['severity']} risk")

    # Build scenario-like dict for threat generator
    scenario = {
        "type": "code_analysis",
        "parameters": {
            "road_condition": "unknown",
            "ecu_cpu_load_pct": 50
        }
    }
    evaluation = {
        "violation":        validation["violation"],
        "risk_score":       validation["risk_score"],
        "actual_delay_ms":  validation["actual_ms"],
        "expected_delay_ms": timing["max_latency_ms"]
    }
    parsed = {
        "event":        component,
        "max_delay_ms": timing["max_latency_ms"],
        "component":    component,
        "iso_standard": "ISO_26262"
    }

    threat = generate_topology_threat(
        component, component, parsed, evaluation,
        scenario, attack_patterns
    )

    print(f"  Severity:    {threat.get('severity')}")
    print(f"  TARA score:  {threat.get('tara_score')}")
    print(f"  Attack type: {threat.get('attack_type')}")
    print(f"  Path:        {' → '.join(threat.get('topology_path', []))}")
    print(f"  Mitigation:  {threat.get('mitigation', '')[:70]}")

    return threat


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def run_integrated_pipeline(filepath: str) -> dict:
    _banner(f"INTEGRATED SDV SAFETY PIPELINE")
    print(f"  Code file: {filepath}")
    print(f"  This pipeline analyzes ACTUAL code — not simulated inputs")

    # Run all steps
    code_result  = step1_parse_code(filepath)
    rag_result   = step2_rag_validate(code_result)
    timing       = step3_timing(code_result, rag_result)
    llm_analysis = step4_llm_code_analysis(code_result, rag_result, timing, filepath)
    validation   = step5_temporal_validate(llm_analysis, timing, rag_result)
    threat       = step6_threat_analysis(code_result, rag_result, validation, timing)

    # Build output in format diagram_renderer understands
    event_chain   = llm_analysis.get("event_chain", code_result["event_chain"])
    chain_timing  = llm_analysis.get("event_chain_timing", [])
    estimated_ms  = llm_analysis.get("total_estimated_ms", 0)
    violation     = validation["violation"]

    final = {
        "mode":        "integrated_code_analysis",
        "filepath":    filepath,
        "language":    code_result["language"],
        "requirement": f"Analyze {os.path.basename(filepath)} for functional safety",
        "agent_output": {
            "event":        code_result["component"],
            "max_delay_ms": timing["max_latency_ms"],
            "iso_standard": timing.get("iso_rule", {}).get("rule_id", "ISO_26262"),
            "event_chain":  event_chain,
            "explanation":  llm_analysis.get("explanation", ""),
            "scenarios": [
                {
                    "type":              "code_analysis",
                    "delay_ms":          estimated_ms,
                    "violation":         violation,
                    "risk_score":        validation["risk_score"],
                    "road_condition":    "N/A (static analysis)",
                    "severity":          threat.get("severity", "UNKNOWN"),
                    "attack_chain":      threat.get("attack_chain", []),
                    "mitigation":        threat.get("mitigation", ""),
                    "event_chain_timing": chain_timing
                }
            ]
        },
        "code_analysis":     code_result,
        "rag_validation":    {
            "validated_vss": rag_result["validated_vss"],
            "invalid_vss":   rag_result["invalid_vss"],
            "validated_can": rag_result["validated_can"],
            "invalid_can":   rag_result["invalid_can"]
        },
        "timing":            timing,
        "llm_analysis":      llm_analysis,
        "temporal_validation": validation,
        "threat":            threat,
        "timestamp":         datetime.now().isoformat()
    }

    _banner("FINAL SUMMARY")
    print(f"  File:            {os.path.basename(filepath)}")
    print(f"  Language:        {code_result['language']}")
    print(f"  VSS signals:     {len(rag_result['validated_vss'])} validated")
    print(f"  CAN IDs:         {len(rag_result['validated_can'])} validated")
    print(f"  Max latency:     {timing['max_latency_ms']}ms")
    print(f"  Estimated time:  {estimated_ms}ms")
    print(f"  Timing verdict:  {validation['verdict']}")
    print(f"  Safety verdict:  {llm_analysis.get('overall_verdict')}")
    print(f"  Threat severity: {threat.get('severity')}")
    print(f"  Violations:      {len(llm_analysis.get('safety_violations', []))}")

    # Save + generate diagrams
    json_path = save_output(final, "integrated_pipeline")

    print("\n  Generating diagrams...")
    try:
        render_from_pipeline_json(json_path)
    except Exception as e:
        print(f"  Diagram generation skipped: {e}")

    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default="datasets/code_samples/brake_python.py",
                        help="Path to SDV code file to analyze")
    args = parser.parse_args()

    if not os.path.exists(args.code):
        print(f"File not found: {args.code}")
        sys.exit(1)

    run_integrated_pipeline(args.code)