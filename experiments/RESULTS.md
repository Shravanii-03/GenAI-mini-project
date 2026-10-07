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

## E6 - red/blue loop (`experiments/e6_redblue.py --seeds 1,2,3 --n 60 --model qwen/qwen3.8-27b`)

A redundant radar (0x2B0) is added for this experiment (off elsewhere) and a stronger attacker,
`dual_masquerade`, that spoofs both sensors consistently. Round 0: red samples 60 attacks per family
against the baseline monitors; hazards with no in-time alarm are the blue team's evidence (half for
fitting, half held out). Round 1: red attacks each hardened monitor again.

* **Round 0 (3 seeds):** 84, 92, 91 attack-induced hazards; 45, 47, 51 of them (about 54%) get no in-time
  alarm. They come from two families only: masquerade (23-24 of 26-27) and dual_masquerade (22-28 of 24-29).
* **Blue arms** (same verifier for all: false-alarm rate <= 2% on benign runs and at least one missed hazard
  turned into an in-time detection):

| Arm | Held-out missed hazards now in time | All hazards in time | False-alarm rate | Round-1 evading-hazard volume | Proposals to first rule |
|---|---|---|---|---|---|
| none | 0.00 | 0.46 | 0.01 | 0.094 | - |
| random proposals (9) | 0.53 | 0.75 | 0.01 | 0.048 | 1 |
| exhaustive grid | 0.53 | 0.75 | 0.02 | 0.048 | 52 |
| LLM (qwen3.8-27b) | 0.53 | 0.75 | 0.01 | 0.048 | 1 |

* **All three rule-synthesis arms reach the same hardened state**: a `cross_check` between the two distance
  sensors (tolerance 1-5 m). Evading-hazard volume halves (9.4% -> 4.8%) and the single masquerade drops from
  73/180 to 0/180 sampled attacks.
* **The LLM adds nothing measurable beyond random proposals plus the verifier** at this problem size: equal
  outcome, equal cost (one proposal), and the 7-9 valid proposals per seed after the first were all rejected
  because nothing can cover the dual attacker. The deterministic verifier does the work. The evidence summary
  the LLM sees is per-family and already shows the sensor-vs-radar gap (20.7 m vs 0.11 m benign), which makes
  the task easy; a larger rule language or messier evidence is needed to show any LLM advantage.
* **Irreducible residual:** `dual_masquerade` stays at 78-80 of 180 sampled attacks (about 43%) under every
  arm. A consistent bias on both channels is indistinguishable from reality for any check in this rule
  language; the knowledge base's own mitigation for this threat class is message authentication (SecOC).
* 9 LLM calls in total (3 per seed); no invalid rules after validation, 6-8 proposals per seed rejected by the
  verifier.

## E8 - real attacks on the ROAD dataset (`experiments/e8_road_validation.py`)

ROAD (Oak Ridge National Laboratory, CC-BY 4.0, https://zenodo.org/records/10462796) holds real CAN
captures from one vehicle with physically verified attacks. It is **not** in this repository; the data was
downloaded to `GenAI_project_data/road` (557 MB zip, 3 GB extracted) and `ROAD_DIR` points at it. Signals are
anonymised, so every detector here is semantics-free and learned from normal driving only.

* **Setup:** training on 7 normal captures (3,812 s, dyno); rule selection on 4 held-out normal captures
  (2,778 s, of which 2,270 s are real-road driving); attacks are never used for learning or selection.
  The deliberately abnormal "exercise all bits" capture is excluded. 13 masquerade captures with a known onset
  are replayed (the 4 accelerator attacks begin before the capture and are skipped).
* **Selection:** signal rules were accepted only with zero false alarms on the held-out normal captures:
  range 568/664, jump 596/664, redundancy pair 10/34. All accepted rules fused: 0 false-alarm events on the
  validation data.

| Attack (captures) | frame-rate IDS | range | jump | redundancy pair | all signal rules fused |
|---|---|---|---|---|---|
| correlated signal (3) | 2/3, median 8.9 s | 3/3, 0 ms | 0/3 | 0/3 | 3/3, 0 ms |
| max speedometer (3) | 2/3, median 34.8 s | 3/3, 7 ms | 3/3, 6.7 s | 3/3, 4 ms | 3/3, 4 ms |
| max engine coolant (1) | 0/1 | 0/1 | 0/1 | 1/1, 0 ms | 1/1, 0 ms |
| reverse light off (3) | 1/3, 15.6 s | 0/3 | 0/3 | 0/3 | 0/3 |
| reverse light on (3) | 3/3, 15.5 s | 0/3 | 0/3 | 0/3 | 0/3 |

Share of the 13 captures detected within 100 ms: fused signal rules 0.54, range 0.46, redundancy pair 0.31,
jump 0.08, frame-rate IDS 0.00 (it reaches 0.62 only after seconds).

* **What it supports:** a semantics-free redundancy cross-check catches a real single-signal forgery (max
  speedometer, engine coolant) within a few milliseconds of the onset at zero false alarms on held-out normal
  data, and range checks catch extreme forged values immediately.
* **Frame-rate IDS:** in masquerade captures genuine frames are replaced, so the frame rate is unchanged and a
  rate-based detector has no signal by construction. On real data my simple per-ID rate IDS could not be tuned to
  a usable false-alarm rate (even its least sensitive setting gave 316 events, about 409/h, on held-out normal
  driving), so its late "detections" (8-35 s) are indistinguishable from false alarms. This reflects the
  limits of this baseline, not of every timing IDS.
* **What it does not support:** in-range semantic forgeries are missed entirely (reverse-light flags, 0/6 by
  every signal rule). ROAD's "correlated signal attack" forges four values to extremes that are inconsistent with
  each other and with normal driving, so it is easy; the consistent dual-sensor attacker of the emulation is **not
  present in ROAD**, so the irreducible-residual finding is untested on real data.
* **Real-world friction the emulation hid:** only 10 of 34 learned redundancy pairs survived the zero-false-alarm
  check on held-out data. A cross-check between wheel-speed signals is a natural candidate, but wheels legitimately
  differ in corners and on real roads, so tolerances learned on dyno data fail to transfer. Redundancy is not
  free in practice.
* **Contamination caveat:** before the injection starts, the fused rules still raised 5 false-alarm events in
  217 s of normal driving inside the attack captures (captures start with transients and other conditions), so
  zero false alarms on the validation captures does not guarantee a low rate elsewhere.
* Small sample: 13 attack captures from one vehicle, 3 per family at most. There is no braking plant in ROAD, so
  this validates detector behaviour, not hazard outcomes or the detection margin.

## E9 - mitigation: failover to the redundant sensor (`experiments/e9_mitigation.py --scenarios 6 --samples 120 --benign 100 --es-budget 150`)

Perception normally trusts the primary sensor only. `radar_or` also reads the independent radar channel and brakes
when EITHER channel reports a time-to-collision at or below the trigger (no added latency: both are read in
parallel). `disagree_brake` additionally brakes as soon as the channels disagree by more than 3 m. Same scenarios,
attack parameters and seeds in every arm; the radar is on the bus in every arm so bus load is identical.

| attack family | none | radar_or | disagree_brake |
|---|---|---|---|
| masquerade | 42.9% [39.3, 46.6] | **0.0%** [0.0, 0.5] | 0.0% |
| gateway delay | 20.3% [17.5, 23.4] | **0.0%** | 0.0% |
| selective suppression | 3.5% [2.4, 5.1] | **0.0%** | 0.0% |
| jitter injection | 1.9% [1.2, 3.2] | **0.0%** | 0.0% |
| sensor drift | 0.1% | 0.0% | 0.0% |
| dos flood | 24.6% [21.6, 27.9] | 24.6% | 24.6% |
| dual masquerade (both channels forged) | 45.3% [41.7, 48.9] | **45.0%** | 45.0% |
| priority abuse, low-and-slow DoS | 0.0% | 0.0% | 0.0% |

(hazard volume = share of the attack parameter space that causes a collision, with Wilson 95% intervals.)

* **What it supports:** the failover removes every hazard that needs only the primary channel (masquerade, gateway
  delay, suppression, jitter): 0 collisions in 720 sampled attacks per family. An adaptive attacker ((1+1)-ES, 150
  evaluations, 6 scenarios) finds a hazard against the unprotected chain in 6/6 scenarios for masquerade and in 0/6
  once the failover is on. It does **not** help against floods (the attacker sits on the shared bus, so both channels
  are delayed) or the dual-sensor attacker (45.3% -> 45.0%), where ES still succeeds in 6/6 scenarios.
* **Benign cost:** none in latency (mean 77.0 -> 74.5 ms, since two channels can only trigger earlier), 0/100 benign
  collisions, 0/100 precautionary triggers.
* **Negative result:** `disagree_brake` is identical to `radar_or`. In these scenarios the channels only disagree once the
  attack is already hiding the real distance, and by then the radar's own TTC has triggered.
* **The price (measured, part D):** with `radar_or`, an attacker who forges only the radar channel to report a near obstacle
  triggers unwanted braking in 100/100 trials when nothing is in the way (0/100 without the failover, where the radar is
  ignored). The primary sensor can already cause this (100/100 in every arm). Redundant OR-voting trades an integrity
  hole for an availability hole; a real system needs plausibility gating or authentication, which is out of scope here.
* Emulation only; the radar is assumed independent, with the same sampling period and noise as the primary sensor.

## E10 - analytic worst-case latency bound (`sdv/analysis/bounds.py`, `experiments/e10_bound_validation.py --scenarios 6 --samples 120`)

For a scenario and an attack instance the module returns an upper bound on obstacle-appearance -> brake-onset latency that
should hold for every random draw (sampling phase, sensor noise, compute jitter, background phase). Components: the time of
the first sensor frame that reports TTC <= trigger (including how long a forged distance can delay it), CAN frame response
times from non-preemptive fixed-priority response-time analysis over the catalogued background traffic with the attacker as a
frame-budgeted stream (and a busy-period argument for floods whose backlog outlives the flood), and compute-time WCETs
(mean x load factor x exp(4 sigma - sigma^2/2)). Comparing the bound with the exact point of no return gives a verdict:
bound <= latest safe latency means **proven safe for every seed**.

* **Soundness:** 0 violations in 12,960 simulated runs (9 families x 720 samples x 2 perception policies), and 0 of 90
  adversarial searches ((1+1)-ES maximising observed - bound, 250 evaluations each, 5 scenarios) found a counter-example.
  No simulated collision was ever labelled proven safe ("hazard & proven" column: 0 in every row).
* **The adversarial search earned its keep:** an earlier version of the bound was violated in 1 of 27 searches (a flood that
  ends just before the obstacle appears but leaves a queue of ~550 frames that is still draining). Two earlier flood
  versions were also wrong (queue backlog ignored; flood started before the obstacle). All three are fixed and have
  regression tests in `tests/test_sdv_bounds.py`.
* **Tightness:** the median bound is about 1.5-2.1x the observed latency (p95 2-6x for the spoofing families). It is
  deliberately conservative: it stacks worst-case compute times and uses the critical instant on the bus.
* **Proven-safe share of the attack space** (with the failover on): selective suppression, drift, masquerade, gateway
  delay and jitter are proven safe in 83% of sampled attacks and the remaining 17% are "unknown" (no simulated hazard: the
  scenario draw whose benign worst case already exceeds its point of no return cannot be certified). Floods: 41% proven
  safe, 26% hazardous, 34% unknown. Dual masquerade: 38% proven safe, 42% hazardous, 21% unknown.
* **Headline** (60 km/h, obstacle 24 m, CPU load 0.3, point of no return 353 ms, benign bound 140 ms): a flood starting when
  the obstacle appears is proven safe up to 400 ms at <= 3000 frames/s, up to 184 ms at 4000 frames/s and up to 122 ms at
  6000 frames/s.
* **Conditions on the claim:** compute times never exceed the declared WCET (a 4-sigma draw has probability 3e-5 per
  stage), the attacker behaves as the emulated families do, and the bus is the emulated one. The bound is a proof for the
  model, not for a real vehicle, and an "unknown" verdict means only that the bound is too coarse to decide.

## E11 - sensitivity to the assumed ECU timings (`experiments/e11_sensitivity.py --scenarios 5 --samples 80`)

The ECU compute times are assumptions. They are scaled (0.5x, 1x, 1.5x, 2x on perception, decision and actuator) and the
jitter is raised to 0.30. Attack-induced hazard volume, policy `none` -> `radar_or` (scenarios stay tight at the default
timings; hazards that also occur without an attack are not counted):

| timing | benign collisions | masquerade | gateway delay | dos flood | dual masquerade |
|---|---|---|---|---|---|
| 0.5x | 0/40 | 37% -> 0% | 12% -> 0% | 19% -> 19% | 38% -> 36% |
| 1x (default) | 0/40 | 40% -> 0% | 22% -> 0% | 24% -> 24% | 40% -> 40% |
| 1.5x | 6/40 | 38% -> 2% | 26% -> 2% | 30% -> 30% | 38% -> 38% |
| 2x | 11/40 | 39% -> 0% | 26% -> 0% | 29% -> 28% | 38% -> 38% |
| jitter 0.30 | 0/40 | 42% -> 0% | 23% -> 0% | 24% -> 24% | 41% -> 40% |

* The qualitative findings do not depend on the assumed timings: single-channel attacks are removed by the failover (at most 2%
  left), floods and the dual-sensor attacker stay at about the same hazard volume.
* The analytic bound stayed sound: 0 violations in 36,000 runs across the five settings.
* What does change: slower ECUs make even benign scenarios unsafe (11/40 at 2x), which is a property of the scenario choice,
  not of the attacks. Absolute hazard volumes therefore depend on the assumed timings and should not be quoted as real-world rates.

## Evidence chain and pipeline (`python -m sdv`, `sdv/evidence`)

* One command takes a requirement in plain English through spec extraction, red team, blue team, a second red
  round and an audited evidence bundle (about 13 s for 40 samples per family, no API key with `--blue enumerate`).
* The auditor re-runs every claim (10 checks: formula, bound, violation reproduces, attack and KB citation,
  declared threat mapping, rule validity, benign false-alarm rate, in-time detection). Tamper tests confirm
  that falsified latencies, collision flags, attack parameters, KB fields, an unparseable formula, a rule that
  alarms on benign traffic and a rule that does not cover the violation are each caught.
* **A defect found by reading the first generated document:** retrieval matched the sensor masquerade to the
  knowledge-base pattern "DoS on CAN Bus", and the original audit passed because it only checked that the
  cited pattern existed. The bundle now cites an explicitly declared family -> pattern mapping
  (`KB_PATTERN_FOR`, the authors' judgement), records what retrieval suggested next to it, and the auditor
  fails a bundle that cites a real but wrong pattern.
* The bundle is machine-checked consistency on an emulated system, not a certified safety case.

## Caveats

* Metric fix: an alarm before the attack starts is a false alarm and earns no margin
  (`credited_alarm_us`). It changed none of the numbers above.
* Per-family hazard counts in E3 are small (some under 10); do not over-read them.
* LLM refusals occurred in an early generation attempt (stealth framing); refusals are
  retried and never cached.
* E6 uses 3 seeds and 60 samples per family per round; the held-out set per seed is about 22-25 cases.
* ROAD results are descriptive (13 captures, one vehicle); see the E8 section for what they do and do not support.
* The Docker image has not been built (Docker is not installed on the development machine); the dependency
  list was checked by installing `requirements.txt` into a fresh virtual environment and running the tests.
* Raw LLM replies live in `outputs/llm_cache/` (not committed). Keep a copy: they are the evidence
  behind the E4 tables and make every number reproducible offline with `--offline`.
