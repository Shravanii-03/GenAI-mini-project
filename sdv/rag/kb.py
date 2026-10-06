"""
Knowledge-base corpora as uniform documents.

kinds: vss (signals), can (messages), attack (patterns), rule (timing rules).
Document text is normalised so lexical retrievers can match natural language:
dotted paths and CamelCase are split ("Vehicle.ADAS.ABS.IsEngaged" ->
"vehicle adas abs is engaged"), which the original retriever did not do.
"""
import json
import re
from dataclasses import dataclass

import config

KINDS = ("vss", "can", "attack", "rule")
_STOP = set("a an the of to in on for and or is are be by with from at as it its this that".split())


@dataclass(frozen=True)
class Doc:
    id: str
    kind: str
    text: str
    title: str = ""


def split_camel(text: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)


def stem(word: str) -> str:
    """Very light stemming so inflections agree: brake, brakes, braking, braked -> brak."""
    for suffix, minimum in (("ing", 5), ("ed", 5), ("s", 4)):
        if word.endswith(suffix) and len(word) >= minimum and not word.endswith("ss"):
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def tokenize(text: str, remove_stop: bool = True, do_stem: bool = True):
    words = re.findall(r"[a-z0-9]+", split_camel(text).lower())
    if remove_stop:
        words = [w for w in words if w not in _STOP]
    return [stem(w) for w in words] if do_stem else words


def _kb_dir():
    return config.project_root() / config.get("rag.knowledge_base_path", "Knowledge_base/")


def _load(name):
    with open(_kb_dir() / name, encoding="utf-8") as f:
        return json.load(f)


def load_corpora() -> dict:
    corpora = {k: [] for k in KINDS}
    for s in _load("vss_signals.json")["signals"]:
        corpora["vss"].append(Doc(s["path"], "vss", f"{s['path']} {s.get('description', '')}", s["path"]))
    for m in _load("can_messages.json")["messages"]:
        corpora["can"].append(Doc(m["id"], "can", f"{m['name']} {m['id']} {m.get('description', '')}", m["name"]))
    for a in _load("attack_patterns.json")["attack_patterns"]:
        text = f"{a.get('name', '')} {a.get('description', '')} {a.get('attack_vector', '')}"
        corpora["attack"].append(Doc(a["id"], "attack", text, a.get("name", "")))
    rules = _load("iso26262_rules.json")
    for r in rules["timing_rules"] + rules["event_chain_rules"]:
        text = f"{r.get('name', '')} {r.get('description', '')} {r.get('component', '')} {r.get('rule', '')}"
        corpora["rule"].append(Doc(r["rule_id"], "rule", text, r.get("name", "")))
    return corpora


REAL_VSS_FILE = "vss_real_v6.1.json"


def load_real_vss(path=None):
    """Leaf signals of the official COVESA VSS release (see Knowledge_base/PROVENANCE.md)."""
    with open(path or (_kb_dir() / REAL_VSS_FILE), encoding="utf-8") as f:
        tree = json.load(f)
    docs = []

    def walk(node, prefix):
        for name, item in node.items():
            full = f"{prefix}.{name}" if prefix else name
            if item.get("type") == "branch":
                walk(item.get("children", {}), full)
            else:
                docs.append(Doc(full, "vss", f"{full} {item.get('description', '')}", full))

    walk(tree, "")
    return docs


def kb_ids() -> dict:
    """Valid identifiers per kind, used to check citations."""
    return {kind: {d.id for d in docs} for kind, docs in load_corpora().items()}
