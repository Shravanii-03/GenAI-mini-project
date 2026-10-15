"""
multi_lang_parser.py — MODULE 1: Multi-Language SDV Code Analyzer
══════════════════════════════════════════════════════════════════
Novel Point: Extends the base paper (Python-only) to C++ and Rust.
Extracts VSS signals, CAN IDs, functions, and control logic from
multi-language SDV code using static analysis + GenAI.

Solves: parser.py only handles requirements text — not actual code.
Paper reference: VSS/CAN extraction workflow (Fig. 1, steps 1-6)
"""

import re
import json
from pathlib import Path
from llm_client import query_llm


# ──────────────────────────────────────────────────────────────────────
# REGEX-based static extractors (fast, no LLM needed)
# ──────────────────────────────────────────────────────────────────────

# CAN ID patterns: 0x1A0, 0x300, CAN_BRAKE_CMD = 0x1A0
_CAN_PATTERN = re.compile(r'\b(0x[0-9A-Fa-f]{2,4})\b')

# VSS signal patterns: "Vehicle.ADAS.xxx" or VSS_SOMETHING = "Vehicle..."
_VSS_PATTERN = re.compile(r'"(Vehicle\.[A-Za-z0-9_.]+)"')

# Function/method definition patterns per language
_FUNC_PATTERNS = {
    "python": re.compile(r'^def\s+(\w+)\s*\(', re.MULTILINE),
    "cpp":    re.compile(r'(?:void|bool|int|float|auto|struct\s+\w+)\s+(\w+)\s*\(', re.MULTILINE),
    "rust":   re.compile(r'fn\s+(\w+)\s*[\(<]', re.MULTILINE),
}

# Timing constant patterns: MAX_LATENCY = 100, constexpr int MAX = 100
_TIMING_PATTERN = re.compile(
    r'(?:constexpr|const|#define)?\s*(?:int|uint\d+|u64|i32|usize)?\s*'
    r'(?:MAX|LATENCY|TIMEOUT|THRESHOLD|DELAY)\w*\s*[=:]\s*(\d+)',
    re.IGNORECASE
)


def detect_language(code: str, filename: str = "") -> str:
    """Detect programming language from filename or code content."""
    fname = filename.lower()
    if fname.endswith(".py"):    return "python"
    if fname.endswith(".cpp") or fname.endswith(".cc") or fname.endswith(".h"): return "cpp"
    if fname.endswith(".rs"):    return "rust"

    # Fallback: heuristic from code content
    if "fn " in code and "let " in code and "::" in code:  return "rust"
    if "#include" in code or "std::" in code:               return "cpp"
    return "python"


def extract_can_ids(code: str) -> list:
    """Extract all CAN message IDs from code (any language)."""
    raw = _CAN_PATTERN.findall(code)
    # Deduplicate, keep order
    seen = set()
    ids = []
    for r in raw:
        val = int(r, 16)
        if val >= 0x100 and val not in seen:  # filter out small hex that are probably not CAN IDs
            seen.add(val)
            ids.append({"hex": r, "decimal": val})
    return ids


def extract_vss_signals(code: str) -> list:
    """Extract all VSS signal path strings from code."""
    raw = _VSS_PATTERN.findall(code)
    return list(dict.fromkeys(raw))  # deduplicate, preserve order


def extract_functions(code: str, language: str) -> list:
    """Extract function/method names based on language."""
    pattern = _FUNC_PATTERNS.get(language, _FUNC_PATTERNS["python"])
    return pattern.findall(code)


def extract_timing_constants(code: str) -> list:
    """Extract timing-related constants (latency/timeout/delay values)."""
    matches = _TIMING_PATTERN.findall(code)
    return [int(m) for m in matches]


# ──────────────────────────────────────────────────────────────────────
# LLM-assisted deep extraction
# ──────────────────────────────────────────────────────────────────────

def llm_extract_signals(code: str, language: str) -> dict:
    """
    Use LLM (with RAG context hint) to deeply extract signals, control logic,
    and event chain structure from multi-language code.
    Aligned with paper's Prompt Construct 1.
    """
    prompt = f"""
You are an automotive software analyst. Analyze this {language.upper()} SDV code.

Extract EXACTLY:
1. All VSS signals referenced (path strings like "Vehicle.ADAS.xxx")
2. All CAN message IDs used (hex like 0x1A0)
3. All safety-critical functions (brake, steer, detect, sense, decide, actuate)
4. The event chain order: what calls what in sequence
5. Any timing constraints found (max latency values in ms)
6. The primary SDV component this code controls

Code:
```{language}
{code[:3000]}
```

Output STRICT JSON only. No markdown. No explanation.

{{
    "vss_signals": ["<signal1>", "<signal2>"],
    "can_ids": ["0xXXX", "0xYYY"],
    "safety_functions": ["<func1>", "<func2>"],
    "event_chain": ["<step1>", "<step2>", "<step3>", "<step4>"],
    "timing_constraints_ms": {{"max_total": <int>, "per_step": {{}}}},
    "component": "<component name>",
    "language": "{language}"
}}
"""
    response = query_llm(prompt, temperature=0.1)
    try:
        start = response.find("{")
        end   = response.rfind("}") + 1
        return json.loads(response[start:end])
    except Exception:
        return {
            "vss_signals": extract_vss_signals(code),
            "can_ids": [x["hex"] for x in extract_can_ids(code)],
            "safety_functions": extract_functions(code, language),
            "event_chain": ["sense", "detect", "decide", "actuate"],
            "timing_constraints_ms": {"max_total": None},
            "component": "unknown",
            "language": language
        }


# ──────────────────────────────────────────────────────────────────────
# Main public API
# ──────────────────────────────────────────────────────────────────────

def parse_sdv_code(code: str, filename: str = "") -> dict:
    """
    Main entry point: parse SDV code in any language.
    Returns unified extraction result with VSS, CAN, functions, event chain.
    """
    language = detect_language(code, filename)

    # Fast static extraction
    can_ids   = extract_can_ids(code)
    vss       = extract_vss_signals(code)
    funcs     = extract_functions(code, language)
    timing    = extract_timing_constants(code)

    # Deep LLM extraction
    llm_result = llm_extract_signals(code, language)

    # Merge static + LLM results
    all_can_ids = list({x["hex"] for x in can_ids} | set(llm_result.get("can_ids", [])))
    all_vss     = list(dict.fromkeys(vss + llm_result.get("vss_signals", [])))

    return {
        "language":             language,
        "filename":             filename,
        "can_ids":              all_can_ids,
        "vss_signals":          all_vss,
        "safety_functions":     list(dict.fromkeys(funcs + llm_result.get("safety_functions", []))),
        "event_chain":          llm_result.get("event_chain", ["sense", "detect", "decide", "actuate"]),
        "timing_constants_ms":  timing,
        "llm_timing":           llm_result.get("timing_constraints_ms", {}),
        "component":            llm_result.get("component", "unknown"),
        "summary":              f"{language.upper()} code | {len(all_can_ids)} CAN IDs | {len(all_vss)} VSS signals"
    }


def parse_sdv_file(filepath: str) -> dict:
    """Parse an SDV code file by path."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Code file not found: {filepath}")
    code = path.read_text(encoding="utf-8")
    return parse_sdv_code(code, filename=path.name)


# ──────────────────────────────────────────────────────────────────────
# CLI test
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        result = parse_sdv_file(sys.argv[1])
    else:
        # Default: parse the brake_python.py sample
        sample_path = "datasets/code_samples/brake_python.py"
        print(f"[MultiLangParser] Parsing: {sample_path}")
        result = parse_sdv_file(sample_path)

    print(json.dumps(result, indent=2))