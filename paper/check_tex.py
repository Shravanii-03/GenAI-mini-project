"""Static checks on paper/main.tex (no TeX engine needed): environments balance, every \\cite has a \\bibitem and vice versa,
every \\ref has a \\label, every figure file exists, braces balance, and a word count."""
import os
import re
import sys

here = os.path.dirname(os.path.abspath(__file__))
tex = open(os.path.join(here, "main.tex"), encoding="utf-8").read()
body = re.sub(r"(?<!\\)%.*", "", tex)
problems = []

begins = re.findall(r"\\begin\{(\w+\*?)\}", body)
ends = re.findall(r"\\end\{(\w+\*?)\}", body)
if sorted(begins) != sorted(ends):
    problems.append(f"environments differ: {sorted(set(begins) ^ set(ends))}")
if body.count("{") != body.count("}"):
    problems.append(f"braces: {body.count('{')} open vs {body.count('}')} close")

cited = {k.strip() for m in re.findall(r"\\cite\{([^}]*)\}", body) for k in m.split(",")}
items = set(re.findall(r"\\bibitem\{([^}]*)\}", body))
if cited - items:
    problems.append(f"cited but no bibitem: {sorted(cited - items)}")
if items - cited:
    problems.append(f"bibitem never cited: {sorted(items - cited)}")

labels = set(re.findall(r"\\label\{([^}]*)\}", body))
refs = set(re.findall(r"\\(?:eq)?ref\{([^}]*)\}", body))
if refs - labels:
    problems.append(f"ref without label: {sorted(refs - labels)}")
if labels - refs:
    problems.append(f"label never referenced: {sorted(labels - refs)}")

for f in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", body):
    if not os.path.exists(os.path.join(here, "figs", f)):
        problems.append(f"missing figure file: {f}")

text = re.sub(r"\\begin\{thebibliography\}.*", "", body, flags=re.S)
text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)
text = re.sub(r"[{}$~&\\]", " ", text)
words = len(re.findall(r"[A-Za-z][A-Za-z'-]+", text))
print(f"words (approx, body incl. captions and tables): {words}")
print("figures:", len(re.findall(r"\\begin\{figure", body)), "tables:", len(re.findall(r"\\begin\{table", body)))
for p in problems:
    print("PROBLEM:", p)
print("OK" if not problems else "FAILED")
sys.exit(1 if problems else 0)
