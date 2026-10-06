"""
RAG ENGINE — FINAL PRODUCTION VERSION (STRONG RAG ENFORCEMENT)

✔ Stronger context injection
✔ Better semantic grounding
✔ Structured knowledge formatting
✔ Fallback-safe retrieval
✔ Forces LLM grounding
"""

import json
import math
import re
from pathlib import Path
from llm_client import query_llm
import config


# =========================
# LOAD KB
# =========================

_KB_PATH = config.project_root() / config.get("rag.knowledge_base_path", "Knowledge_base/")
_CACHE = {}

def _load_kb(filename):
    if filename in _CACHE:
        return _CACHE[filename]

    path = _KB_PATH / filename
    if not path.exists():
        return {}

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Ensure we always return a dict
    if isinstance(data, dict):
        _CACHE[filename] = data
    else:
        _CACHE[filename] = {}
    return _CACHE[filename]


def load_vss_signals():
    data = _load_kb("vss_signals.json")
    return data.get("signals", [])


def load_can_messages():
    data = _load_kb("can_messages.json")
    return data.get("messages", [])


def load_iso_rules():
    data = _load_kb("iso26262_rules.json")
    return data.get("timing_rules", []) + data.get("event_chain_rules", [])


def load_attack_patterns():
    data = _load_kb("attack_patterns.json")
    return data.get("attack_patterns", [])


# =========================
# TOKEN + TF-IDF
# =========================

def _tokenize(text):
    return re.findall(r'\w+', text.lower())


def _tfidf_score(query_tokens, doc_tokens, corpus):

    overlap = set(query_tokens) & set(doc_tokens)
    if not overlap:
        return 0

    score = 0
    N = len(corpus)

    for term in overlap:
        tf = doc_tokens.count(term) / (len(doc_tokens) + 1)
        df = sum(1 for d in corpus if term in d)
        idf = math.log((N + 1) / (df + 1)) + 1
        score += tf * idf

    return score / (len(query_tokens) + 1)


def _doc_to_text(item, t):

    if t == "vss":
        return f"{item.get('path','')} {item.get('description','')}"

    if t == "can":
        return f"{item.get('id','')} {item.get('name','')} {item.get('description','')}"

    if t == "iso":
        return f"{item.get('rule_id','')} {item.get('rule','')} {item.get('component','')} {item.get('max_latency_ms','')}"

    if t == "attack":
        return f"{item.get('name','')} {item.get('description','')} {item.get('attack_vector','')}"

    return str(item)


# =========================
# RETRIEVAL
# =========================

def retrieve(query, doc_type, top_k=3):

    loaders = {
        "vss": load_vss_signals,
        "can": load_can_messages,
        "iso": load_iso_rules,
        "attack": load_attack_patterns
    }

    corpus = loaders[doc_type]()
    if not corpus:
        return []

    texts = [_doc_to_text(x, doc_type) for x in corpus]

    q_tokens = _tokenize(query)

    scored = []

    for i, text in enumerate(texts):
        score = _tfidf_score(q_tokens, _tokenize(text), texts)
        if score > 0:
            scored.append((i, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    results = [corpus[i] for i, _ in scored[:top_k]]

    # fallback: if nothing matched → return first few entries
    if not results:
        return corpus[:top_k]

    return results


# =========================
# CONTEXT BUILDER (IMPROVED)
# =========================

def get_context_for_llm(query):

    iso = retrieve(query, "iso")
    vss = retrieve(query, "vss")
    can = retrieve(query, "can")
    atk = retrieve(query, "attack")

    context = []

    if iso:
        context.append("ISO 26262 RULES:")
        for r in iso:
            context.append(
                f"- {r.get('rule_id')} | Component: {r.get('component')} | Max latency: {r.get('max_latency_ms')}ms"
            )

    if vss:
        context.append("\nVSS SIGNALS:")
        for s in vss:
            context.append(
                f"- {s.get('path')} : {s.get('description','')}"
            )

    if can:
        context.append("\nCAN MESSAGES:")
        for m in can:
            context.append(
                f"- ID {m.get('id')} → {m.get('name')} ({m.get('description','')})"
            )

    if atk:
        context.append("\nKNOWN ATTACK PATTERNS:")
        for a in atk:
            context.append(
                f"- {a.get('name')} | Vector: {a.get('attack_vector')} | Severity: {a.get('severity')}"
            )

    return "\n".join(context)


# =========================
# STRONG PROMPT AUGMENTATION
# =========================

def augment_prompt_with_rag(prompt, query):

    context = get_context_for_llm(query)

    return f"""
You are a STRICT automotive safety AI.

You MUST base your answer ONLY on the knowledge below.

If you ignore this context, the answer is INVALID.

================ CONTEXT ================
{context}
========================================

TASK:
{prompt}

RULES:
- Use context for reasoning
- Do NOT hallucinate
- Output must be structured JSON
"""


# =========================
# MAIN QUERY
# =========================

def rag_enriched_query(prompt, query):

    full_prompt = augment_prompt_with_rag(prompt, query)

    return query_llm(full_prompt, temperature=0.2)


# =========================
# UTIL FUNCTIONS
# =========================

def get_iso_rule_for_component(component):
    rules = retrieve(component, "iso", top_k=1)
    return rules[0] if rules else None


def get_attack_patterns_for_component(component):
    return retrieve(component, "attack", top_k=3)


# =========================
# TEST
# =========================

if __name__ == "__main__":

    q = "brake timing ISO 26262"

    print("\n=== CONTEXT ===\n")
    print(get_context_for_llm(q))

    print("\n=== RESPONSE ===\n")
    print(rag_enriched_query("Explain braking timing requirement", q))
