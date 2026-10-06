# Experiment results log

All results come from the **emulated** CAN network in `sdv/` with **assumed** ECU compute
times, bus load and a 20 ms mitigation response (see `config.yaml`). They are pilot results,
not measurements on a vehicle. Regenerate with the commands shown; seeds are fixed.

## E1 — detector comparison (`experiments/e1_pilot.py --n 300 --seed 1`)

| Monitor | Recall | FPR | F1 | In time (of attack-induced hazards) |
|---|---|---|---|---|
| deadline (observable) | 0.02 | 0.01 | 0.03 | 0.08 |
| frequency IDS | 0.64 | 0.00 | 0.78 | 0.60 |
| plausibility | 0.43 | 0.00 | 0.60 | 0.08 |
| fused (all three) | 0.90 | 0.01 | 0.95 | 0.63 |

* Recall and F1 overstate protection: the best detector flags about 63% of hazards in time.
* Timing monitors and content monitors fail on different attacks.
* A deadline monitor that starts counting at the *observed* threat cannot see delays upstream
  of its own observation (e.g. a flood that starves the sensor).
* No convincing F1-vs-margin ranking reversal: rankings differ only at the bottom, where the
  in-time rates are tied.

## E2 — attack search (`experiments/e2_search.py --budget 50 --trials 20 --seed 1`)

* Hazard volume (share of parameter space that causes a collision, `hazard_volume.py`):
  masquerade 42.9%, dos_flood 24.7%, gateway_delay 20.3%, selective_suppression 3.5%,
  jitter_injection 1.9%, sensor_drift_spoof 0.1%, priority_abuse 0%, low_slow_dos 0%.
* Bayesian optimisation, (1+1)-ES and tabular Q-learning do **not** beat random search
  (BO fewer simulations in 29 paired cells, more in 37). Grid search is worse (misses `k=1`).
* The LLM prior (RAG-grounded, cached) needs fewer simulations than random in 54 of 80 paired
  cells and more in 0; the clearest gain is selective suppression (median 1 vs 16), where the
  LLM names the mechanism ("drop every frame").
* `sensor_drift_spoof` has a real hazard corner (rate ~29 m/s, 700 ms, start -380 ms) that no
  method found in 50 evaluations: a needle in a flat landscape.
* Stealth objective: only masquerade yields hazards that evade the fused monitor in time.

## E3 — detector tuning sweep (`experiments/e3_tuning_sweep.py --n 60 --seed 1..3`)

* 576 fused configurations; selection on one half, reporting on the other.
* The F1-optimal configuration is also the margin-optimal one for any false-alarm cap up to
  20% (3 seeds). Extra timeliness (+4 to +9 points) costs about 0.1-0.15 F1 and a 20-40% FPR.
  The hypothesis "tuning for F1 gives the wrong detector" is **not supported**.
* What limits the best configuration: **masquerade**. 38 hazards, 32 eventually detected,
  **2 in time**, median detection 528 ms after attack start. Other families: 100% in time.
* Mechanism (checked directly): a constant-bias masquerade that begins before the obstacle
  appears keeps the distance consistent with ego motion, so the kinematic check only fires
  when the bias ends. If it starts after the obstacle appears it is caught in ~105 ms.
  A cross-sensor (redundant) check is needed.

## E4 - natural language -> timing specification (`experiments/e4_spec_extraction.py`)

120 author-written requirements, 8 categories (`datasets/benchmark/`). Models: gpt-oss-120b (all 120
for LLM-only and eager; RAG on the first 83), gpt-oss-20b and qwen3.8-27b (every second requirement, n=60).
Retriever for RAG: BM25 (top 8 VSS, top 5 CAN). 95% Wilson intervals in brackets.

| Model, n | Condition | Deadline correct | Exact (deadline+vague flag+component) | VSS F1 | CAN F1 | Invalid VSS / predicted |
|---|---|---|---|---|---|---|
| regex baseline, 120 | - | 0.86 [0.78,0.91] | - | - | - | - |
| gpt-oss-120b, 120 | LLM only | 0.99 [0.95,1.00] | 0.87 | 0.03 | 0.07 | 1/2 |
| gpt-oss-120b, 120 | eager (list signals from memory) | 0.98 [0.94,1.00] | 0.84 | 0.02 | 0.03 | 172/185 |
| gpt-oss-120b, 83 | RAG | 0.99 [0.93,1.00] | 0.83 (LLM only on same 83: 0.86) | 0.85 | 0.64 | 0/45 |
| gpt-oss-20b, 60 | LLM only / eager / RAG | 1.00 / 0.97 / 1.00 | 0.83 / 0.78 / 0.73 | 0.00 / 0.00 / 0.87 | 0.00 / 0.00 / 0.19 | 8/8, 38/38, 0/35 |
| qwen3.8-27b, 60 | LLM only / eager / RAG | 1.00 / 0.98 / 1.00 | 0.90 / 0.80 / 0.80 | 0.06 / 0.02 / 0.85 | 0.00 / 0.00 / 0.46 | 2/3, 69/80, 0/39 |

* **Deadline extraction is essentially solved by these LLMs** on this benchmark (0.97-1.00) and the
  benchmark does not separate the models or conditions. The LLM clearly beats regex on the categories
  regex cannot handle: derived/arithmetic 1.00 vs 0.20, units 1.00 vs 0.80, formats 1.00 vs 0.80.
  The single error of the 120b model is an arguably ambiguous multi-clause label (500 ms timeout with a
  20 ms follow-up). A harder benchmark (real industrial requirements) is needed.
* **Hallucination without grounding.** Asked to list VSS signals from memory, 93% (120b: 172/185),
  100% (20b: 38/38) and 86% (qwen: 69/80) of the paths are fabricated. None is a real VSS v6.1 path
  that is merely missing from our KB (`experiments/e4_hallucination_check.py`). Told to list only what
  it is sure of, the model returns nothing (VSS F1 about 0): a recall gap instead.
* **RAG fixes identifiers:** VSS F1 0.00-0.03 -> 0.85-0.87 with zero invalid paths. CAN IDs stay hard
  (F1 0.19-0.64) because the candidates are retrieved from 11 illustrative messages.
* **RAG can hurt classification:** exact-match fell 0.83 -> 0.73 (20b) and 0.90 -> 0.80 (qwen); for
  120b the change (0.86 -> 0.83) is within the interval. Cause not yet analysed.
* **The validator and repair loop gave no measurable benefit** for these models: first-reply
  validity was already 98-100%. It would matter for weaker models; not tested.
* STL: `spec_to_run_demo.py` evaluates the extracted formula on simulated runs; robustness equals
  deadline minus latency and agrees with the plant margin.

**Not completed (free-tier limits).** Groq allows 200,000 tokens per model per day (and 8,000 per
minute). gpt-oss-120b exhausted its daily budget after about 320 calls, so its RAG condition covers
83 of 120 requirements and the validator-only and eager+validator conditions were not run for it.
The remaining calls resume from the disk cache automatically
(`experiments/run_e4_resilient.sh outputs/logs/e4_openai_gpt-oss-120b.log --model openai/gpt-oss-120b
--retriever bm25 --workers 3 --out outputs/e4_openai_gpt-oss-120b_bm25.csv`) once the budget refills.
`--offline` reports only what is cached and `--matched` restricts every condition to common items.
Dense-retriever RAG was not run through the LLM experiment for the same reason.

## E5 - retrieval (`experiments/e5_retrieval.py [--real-vss] [--dense]`)

MRR with chance in brackets; 95% bootstrap CIs are in the script output.

| Setting | Legacy TF-IDF | BM25 | Dense (bge-small, quantised) | Hybrid (RRF) | Chance |
|---|---|---|---|---|---|
| Hand-made KB (26/11/8/12 docs), all 106 queries | 0.60 | 0.69 | 0.85 | 0.83 | 0.22 |
| same, keyword queries | 0.87 | 1.00 | 0.99 | 1.00 | 0.22 |
| same, paraphrase queries | 0.34 | 0.38 | 0.72 | 0.67 | 0.22 |
| Real VSS v6.1 (1,382 signals), 32 queries | 0.43 | 0.53 | 0.58 | 0.55 | 0.01 |
| same, paraphrase only (16) | 0.15 | 0.19 | 0.33 | 0.23 | 0.01 |

* On the tiny KB, "return the first 5 documents" already reaches R@5 = 0.38 on paraphrases; the
  original retriever's fallback does exactly that when nothing matches (9 of 53 paraphrase queries).
* Dense retrieval is clearly best on paraphrases for the small KB. On the real 1,382-signal corpus
  retrieval is hard for every method (best paraphrase MRR 0.33), and with 32 queries the intervals
  overlap, so only the ordering "dense >= BM25 > legacy" is suggested, not established.
* **Knowledge-base audit** (`Knowledge_base/PROVENANCE.md`): only 16 of the 26 hand-written VSS paths
  exist in the official VSS v6.1; the ISO rule IDs, CAN IDs and attack patterns are illustrative.

## Caveats

* Metric fix: an alarm before the attack starts is a false alarm and earns no margin
  (`credited_alarm_us`). It changed none of the numbers above.
* Per-family hazard counts in E3 are small (some under 10); do not over-read them.
* LLM refusals occurred in an early generation attempt (stealth framing); refusals are
  retried and never cached.
* Raw LLM replies live in `outputs/llm_cache/` (not committed). Keep a copy: they are the evidence
  behind the E4 tables and make every number reproducible offline with `--offline`.
