# Experiment results log

All results come from the **emulated** CAN network in `sdv/` with **assumed** ECU compute
times, bus load and a 20 ms mitigation response (see `config.yaml`). They are pilot results,
not measurements on a vehicle. Regenerate with the commands shown; seeds are fixed.

## CORRECTION RECORD (2026-10-15): residual risk after authentication was under-estimated; tables below are the corrected ones

Until 15 Oct 2026, E9, E10, E11, E12 and E14 sampled attacks over only 5-6 base scenarios (each scenario reused for many sampled
attacks), so one unusually tight scenario moved an estimate by 1/6. That made the dual-sensor attacker's hazard volume after
authentication plus the watchdog look like 1.0-2.0%. With **one fresh scenario per sampled attack** it is **4.3% [3.0%, 6.3%]**
(E12, 600 distinct scenarios; 3.3-5.3% in three seeds of 300; 3-4% across the braking strengths in E14). The reason is physical: the
watchdog needs about 35 ms to notice silence plus the chain time, so it cannot save scenarios whose point of no return is shorter.
E9-E14 were then re-run in the cloud (GitHub Actions, tag `repro-20261015b`, commit `7285a54`) with the corrected sampling, and every
hazard-volume table in those sections below is the corrected one. Other qualitative conclusions were unchanged (single-channel
attacks removed by the failover, untrusted-segment floods removed by the guard, the safety-bus flood and the key holder remain open),
and the analytic-bound results (zero violations) do not depend on the sampling.

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
requirements in every condition), gpt-oss-20b and qwen3.8-27b (every second requirement, n=60).
Retriever for RAG: BM25 (top 8 VSS, top 5 CAN). 95% Wilson intervals in brackets.

| Model, n | Condition | Deadline correct | Exact (deadline+vague flag+component) | VSS F1 | CAN F1 | Invalid VSS / predicted |
|---|---|---|---|---|---|---|
| regex baseline, 120 | - | 0.86 [0.78,0.91] | - | - | - | - |
| gpt-oss-120b, 120 | LLM only | 0.99 [0.95,1.00] | 0.87 | 0.03 | 0.07 | 1/2 |
| gpt-oss-120b, 120 | eager (list signals from memory) | 0.98 [0.94,1.00] | 0.84 | 0.02 | 0.03 | 172/185 |
| gpt-oss-120b, 120 | RAG | 0.99 [0.95,1.00] | 0.84 | 0.88 | 0.63 | 0/64 |
| gpt-oss-120b, 120 | validator only (LLM + check and repair) | 0.99 [0.95,1.00] | 0.87 | 0.03 | 0.07 | 0/1 |
| gpt-oss-120b, 120 | eager + validator | 0.99 [0.95,1.00] | 0.86 | 0.06 | 0.09 | 0/8 (was 172/185) |
| gpt-oss-120b, 120 | RAG + validator | 0.99 [0.95,1.00] | 0.84 | 0.88 | 0.63 | 0/64 |
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
  120b the change (0.87 -> 0.84, all 120 requirements) is within the interval. Cause not yet analysed.
* **The validator removes fabricated identifiers but does not restore what they should have been.** With signals listed from
  memory (eager), only 12% of first replies are valid; the repair loop (0.97 repairs per requirement on average) makes
  100% valid and cuts invalid VSS paths from 172/185 to 0/8, but VSS F1 stays at 0.06 because the repair mostly deletes
  the invented paths. Only RAG gives valid *and* correct identifiers (VSS F1 0.88). For the LLM-only and RAG conditions the
  validator changes nothing measurable (first-reply validity was already 98-100%).
* STL: `spec_to_run_demo.py` evaluates the extracted formula on simulated runs; robustness equals
  deadline minus latency and agrees with the plant margin.

**Completion note.** Groq's free tier allows 200,000 tokens per model per day (and 8,000 per minute). The gpt-oss-120b run was
first cut short by that limit (RAG on 83 of 120 requirements) and was completed on 15 Oct 2026 by resuming from the disk cache
(`experiments/run_e4_resilient.sh outputs/logs/e4_openai_gpt-oss-120b.log --model openai/gpt-oss-120b --retriever bm25 --workers 3
--out outputs/e4_openai_gpt-oss-120b_bm25.csv`); every condition now covers all 120 requirements. `--offline` reports only what is
cached. Dense-retriever RAG was not run through the LLM experiment.

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
| masquerade | 44.9% [41.3, 48.5] | **0.0%** [0.0, 0.5] | 0.0% |
| gateway delay | 25.3% [22.2, 28.6] | **0.0%** | 0.0% |
| selective suppression | 3.9% [2.7, 5.6] | **0.0%** | 0.0% |
| jitter injection | 2.6% [1.7, 4.1] | **0.0%** | 0.0% |
| sensor drift | 0.0% | 0.0% | 0.0% |
| dos flood | 27.8% [24.6, 31.2] | 27.4% | 27.4% |
| dual masquerade (both channels forged) | 47.8% [44.2, 51.4] | **47.5%** | 47.5% |
| priority abuse, low-and-slow DoS | 0.0% | 0.0% | 0.0% |

(hazard volume = share of the attack parameter space that causes a collision, with Wilson 95% intervals; 720 sampled attacks per
family, each in its own freshly drawn tight scenario.)

* **What it supports:** the failover removes every hazard that needs only the primary channel (masquerade, gateway
  delay, suppression, jitter): 0 collisions in 720 sampled attacks per family. An adaptive attacker ((1+1)-ES, 150
  evaluations, 6 scenarios) finds a hazard against the unprotected chain in 6/6 scenarios for masquerade and in 0/6
  once the failover is on. It does **not** help against floods (the attacker sits on the shared bus, so both channels
  are delayed) or the dual-sensor attacker (47.8% -> 47.5%), where ES still succeeds in 6/6 scenarios.
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
* **Tightness:** the median bound is about 1.5-2.1x the observed latency (p95 2-10x, largest for the spoofing families). It is
  deliberately conservative: it stacks worst-case compute times and uses the critical instant on the bus.
* **Proven-safe share of the attack space** (720 sampled attacks per family, one fresh scenario each, failover on): selective
  suppression, drift, masquerade, gateway delay and jitter are proven safe in 68.5% of sampled attacks, with 0% simulated hazard; the
  other 31.5% are "unknown", meaning the bound is too coarse to decide, not that anything went wrong: about 31% of the drawn tight
  scenarios have a point of no return below the benign worst-case bound, so nothing can be certified for them even though none of
  these attacks hurt them. Floods: 30.3% proven safe, 26.7% hazardous, 43.1% unknown. Dual masquerade: 31.8% proven safe, 43.1% hazardous,
  25.1% unknown. Without the failover, masquerade is 43.2% hazardous, 29.0% proven safe.
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
| 0.5x | 0/40 | 39% -> 0% | 18% -> 0% | 19% -> 19% | 41% -> 40% |
| 1x (default) | 0/40 | 42% -> 0% | 28% -> 0% | 26% -> 26% | 42% -> 40% |
| 1.5x | 6/40 | 37% -> 1% | 28% -> 0% | 31% -> 32% | 39% -> 39% |
| 2x | 11/40 | 32% -> 2% | 23% -> 1% | 22% -> 22% | 30% -> 30% |
| jitter 0.30 | 0/40 | 43% -> 0% | 30% -> 0% | 25% -> 25% | 42% -> 42% |

* The qualitative findings do not depend on the assumed timings: single-channel attacks are removed by the failover (at most 2%
  left), floods and the dual-sensor attacker stay at about the same hazard volume.
* The analytic bound stayed sound: 0 violations in 36,000 runs across the five settings.
* What does change: slower ECUs make even benign scenarios unsafe (11/40 at 2x), which is a property of the scenario choice,
  not of the attacks. Absolute hazard volumes therefore depend on the assumed timings and should not be quoted as real-world rates.

## E12 - closing the two remaining holes: gateway guard and message authentication (`experiments/e12_defences.py --scenarios 6 --samples 100 --benign 100 --es-budget 100`)

Two defences on top of the E9 radar failover (`radar_or`):

* **Gateway guard** (`sdv/bus/guard.py`): a gateway between an untrusted segment (OBD-II, infotainment) and the safety bus
  forwards only whitelisted identifiers (the two infotainment messages in the catalog) through a token bucket at 2x their
  nominal rate. A flood injected from that segment never reaches arbitration.
* **Message authentication + fail-safe watchdog** (idealised SecOC-style MAC, same frame size, 0.5 ms assumed verification
  time): a frame whose payload was changed after signing is rejected unless the attacker holds the key. If neither channel
  delivers a valid frame for 30 ms, perception brakes (fail-safe).

Two attacker variants were added so the residual is explicit: a flood from a node **on the safety bus** (the guard cannot
see it) and forging attackers that **hold the signing key**.

Hazard volume (share of the attack parameter space that causes a collision; Wilson 95% intervals in the log):

| attack variant | radar_or | +guard | +auth | +guard+auth |
|---|---|---|---|---|
| dos flood (untrusted segment) | 26.2% | **0.0%** | 23.8% | **0.0%** |
| dual masquerade (both channels forged) | 43.3% | 43.3% | **4.3%** [3.0, 6.3] | **4.3%** [3.0, 6.3] |
| dos flood (node on the safety bus) | 27.3% | 27.3% | 25.0% | 25.0% |
| dual masquerade, attacker holds the key | 43.0% | 43.0% | 43.0% | 43.0% |
| masquerade, gateway delay, suppression, jitter, drift, priority abuse, low-and-slow DoS | 0.0% | 0.0% | 0.0% | 0.0% |

* Adaptive attacker ((1+1)-ES, 100 evaluations, 6 scenarios), scenarios where a hazard was found with all defences on:
  untrusted-segment floods 0/6, dual forgery 1/6, **safety-bus flood 5/6, key-holding dual forgery 6/6**.
* **What remains, stated plainly:** with all three defences the only hazards left are (1) a flood from a node already on the
  safety bus, and (2) forging attackers that hold the key. Authentication moves the trust to key management; the guard
  moves it to the network architecture. Neither is a general solution, and the dual-forgery residue (about 4%) is made of scenarios whose
  point of no return is shorter than the watchdog path can meet (about 35 ms to notice silence, plus the chain).
* **Benign cost:** the guard costs nothing (identical latencies). Authentication adds about 1.0 ms (74.5 -> 75.4 ms mean).
  0/100 benign collisions and 0/100 spurious watchdog triggers in every configuration.
* **Availability cost (measured):** authentication closes the E9 hole (a forged near-obstacle on one channel provokes
  unwanted braking 100/100 times without it, 0/100 with it), but opens the mirror one: corrupting **both** channels now makes
  the fail-safe watchdog brake with nothing in the way (0/100 -> 100/100). A key-holding attacker can still force unwanted
  braking (100/100). Fail-safe behaviour trades integrity for availability; it is a design choice, not a free win.
* **The analytic bound stays sound under every defence:** 0 violations in 31,200 runs (E12 part A), and 0 of 260 adversarial
  searches (`experiments/e12b_bound_adversarial.py`, 5 configurations x 13 attack variants x 4 scenarios, 200 evaluations each)
  found a counter-example. The bound extends to the defences: the guard removes untrusted-segment floods from it, and with
  authentication a forged channel counts as silent until its window ends (or the watchdog fires).
* Assumptions: MAC verification is idealised (no forgery without the key, truncated-MAC collision probability ignored,
  freshness handling and key distribution not modelled); the guard assumes the flood really originates behind it; the
  watchdog threshold (30 ms) and verification time are assumed values.

## E13 - CARLA check of the braking plant (`experiments/e13_carla_plant.py`)

**Run 1 (CARLA 0.9.15 on a Colab T4, server with `-nullrhi`, CARLA's default tyre friction): inconclusive, not validation.**
Raw output: `experiments/results/e13_carla_run1_default_friction.json`.

* Fitted CARLA braking was 25-28 m/s^2 (about 2.6-2.9 g) with the ramp stuck at the edge of the search grid (0.4 s) and a fit
  error of about 1 m/s. No road car can brake like that (friction limit about 0.8 g), so the setup, not the physics model,
  was unrealistic. The probable cause is CARLA's default wheel friction, which the script had not changed.
* CARLA's points of no return (834-1200 ms) were far above the emulator's closed form with its assumed parameters
  (mean absolute error 519 ms). Two scenarios returned exactly 1200 ms, the upper limit of the search: no collision occurred.
* With CARLA's own fitted parameters the closed form matched CARLA's point of no return to 74 ms on average (bias +74 ms),
  so the *shape* of the plant (hold speed, ramp, constant deceleration) is consistent with CARLA; the *numbers* were not tested.
* Fix made after this run: set wheel friction to the emulator's assumed 0.8, read time from CARLA's own clock instead of
  assuming 5 ms steps, widen the ramp search, raise the search limit to 2.5 s, and warn on implausible fits.

**Run 2 (same setup, wheel friction set to 0.8, CARLA's own clock): still not validation.**
* Fitted deceleration 29-60 m/s^2 (still 3-4x any road-car limit) with ramps of 440-970 ms; every tick was exactly 5.0 ms,
  so the clock was not the problem.
* CARLA points of no return (km/h, gap): 40/14 835 ms, 50/20 972, 60/24 918, 60/30 1289, 70/32 1079, 80/45 1416.
  Emulator closed form with assumed parameters: 527, 530, 353, 713, 382, 584 (mean absolute error 570 ms, i.e. far off).
  Closed form with CARLA's fitted parameters: mean absolute error 26 ms, bias +26 ms.
* Setting the wheel friction changed almost nothing (835 vs 834 ms, 972 vs 975 ms), so friction was not the cause, or the
  override did not take effect in this headless (`-nullrhi`) mode. Leading suspicion: the ego was teleported to speed with
  `set_target_velocity`, so its wheels start at rest and skid under braking. Run 3 starts the car by driving it up to speed
  under a throttle controller, places the obstacle afterwards, reads the friction back, and saves the raw speed traces.
* What can be said now: the plant's shape (hold, ramp, constant deceleration) reproduces CARLA's results once its parameters are
  fitted; whether the emulator's numbers are realistic is **untested**.

**Run 3, calibration only (ego driven up to speed under throttle control instead of teleported): realistic braking.**
* Mean deceleration over the first second 5.8 / 6.6 / 7.4 / 8.1 / 8.7 m/s^2 at 40 / 50 / 60 / 70 / 80 km/h; fitted
  5.76 / 6.34 / 6.98 / 7.57 / 8.10 m/s^2 with ramps of 0-40 ms and fit errors of 0.17-0.51 m/s. The earlier 25-60 m/s^2 was
  therefore caused by the teleport start (wheels at rest), not by the plant or the clock.
* The emulator assumes a constant 7.85 m/s^2 and a 50 ms ramp. CARLA's braking depends on speed, so the constant-deceleration
  model is only approximately right; at 60 km/h CARLA is weaker than assumed (6.98 vs 7.85 m/s^2), which would make the
  emulator's points of no return somewhat optimistic (about 250 ms instead of 353 ms for 60 km/h, 24 m: a computed estimate,
  to be replaced by the measured value from the full run).
* Caveat: the wheel-friction override in runs 1-3 did not take effect (the API returns a copy of the wheel list and the
  script did not assign it back; the read-back showed 3.5). These runs used CARLA's default friction. Fixed afterwards.

**Run 4 (full check; wheel friction override now in effect, read back as 0.8; ego driven up to speed): the plant's structure
agrees with CARLA, the emulator's default numbers do not.** (Numbers transcribed from the console output; the JSON file did
not download.)
* CARLA's Model 3 braked at 4.7-5.5 m/s^2 (mean over the first second) at 40-80 km/h, fitted 4.86 / 5.14 / 5.31 / 5.40 / 5.48
  m/s^2 with ramps of 70 / 70 / 50 / 20 / 0 ms and fit errors of 0.04-0.11 m/s. CARLA's friction setting is a scale factor,
  not a friction coefficient: 0.8 here corresponds to about 0.54 g, not 0.8 g.
* Points of no return (km/h, gap): CARLA vs closed form with CARLA's fitted parameters vs emulator defaults:
  40/14 73 vs 81 vs 527 ms; 50/20 49 vs 54 vs 530; 60/30 195 vs 207 vs 713; 80/45 15 vs -4 vs 584; 60/24 and 70/32:
  CARLA collides even at zero latency, and the fitted closed form also predicts unavoidable collision (-153 and -164 ms).
* Mean absolute error of the closed form against CARLA: 11 ms with the fitted parameters (bias +1.5 ms, n = 4, plus two
  scenarios where both agree the collision is unavoidable); 506 ms with the emulator's default parameters.
* **Reading:** the model structure (hold speed, short ramp, constant deceleration) reproduces a physics engine's point of
  no return to about 10 ms once two parameters are calibrated. The emulator's default parameters (7.85 m/s^2, 50 ms) are
  more optimistic than this CARLA vehicle; they are within the range of real passenger cars, so this is a statement about the
  parameters' sensitivity, not proof that they are wrong. The conclusions' sensitivity to the braking parameters is tested in E14.
* Limits: one vehicle model, one town, a straight road, headless physics (`-nullrhi`), 5 ms ticks, speed-dependent braking
  approximated by a constant value, a point-of-no-return search tolerance of 5 ms.

## E14 - sensitivity to the braking physics (`experiments/e14_plant_sensitivity.py --scenarios 5 --samples 80`)

The CARLA check (E13) showed a physics engine's vehicle brakes more weakly than the emulator's default. Braking strength is varied
here (decel = mu * g; scenarios are redrawn to stay tight for each setting). Attack-induced hazard volume, `none / radar_or /
all defences` (radar failover, gateway guard, authentication):

| braking | masquerade | gateway delay | DoS flood | dual masquerade | flood from a safety-bus node | dual attacker with the key |
|---|---|---|---|---|---|---|
| 0.54 g (CARLA-like, 5.3 m/s^2) | 59 / 0 / 0 | 30 / 0 / 0 | 27 / 28 / 0 | 56 / 55 / 3 | 27 / 27 / 23 | 52 / 52 / 52 |
| 0.65 g | 52 / 0 / 0 | 30 / 0 / 0 | 19 / 19 / 0 | 46 / 46 / 4 | 30 / 29 / 27 | 51 / 50 / 50 |
| 0.80 g (default) | 44 / 0 / 0 | 25 / 0 / 0 | 28 / 27 / 0 | 42 / 42 / 4 | 22 / 22 / 20 | 42 / 42 / 42 |
| 0.90 g | 42 / 0 / 0 | 26 / 0 / 0 | 26 / 26 / 0 | 39 / 38 / 4 | 23 / 23 / 21 | 40 / 40 / 40 |

* The ranking of defences and the list of residual holes do not change with braking strength: failover removes single-channel
  attacks, the guard removes untrusted-segment floods, authentication plus the watchdog removes dual forgery (1-2% left), and the
  safety-bus flood and the key holder remain (20-27% and 40-52%).
* Weaker braking raises the absolute hazard volumes (for example masquerade without defences 42% at 0.9 g, 59% at 0.54 g). The
  absolute percentages therefore depend on the assumed braking and should not be quoted as real-world rates.
* Benign collisions: 0/40 in every setting. The analytic bound stayed sound: 0 violations in 7,200 runs per setting.

## E15 - authentication + silence watchdog replayed on real attack traffic (`experiments/e15_road_defence_replay.py`)

What is replayed: the E12 defence logic that can be exercised on real CAN data. A receiver with message authentication rejects
forged frames; a watchdog then notices when a periodic ID goes silent. In ROAD's 13 masquerade captures every frame of the attacked
ID inside the attack window is an injected, labelled frame at the normal rate (no genuine frame of that ID is left), so a receiver
that rejects forged frames sees that ID fall silent. Periods are learned from 3,812 s of normal driving (103 periodic IDs, 10-1500 ms,
robust criterion: 95th-percentile gap at most 1.5x the median); false triggers are counted on 2,778 s of held-out normal driving, of
which 2,270 s is real road. **Authentication is idealised (exactly the labelled frames are rejected): the detection follows from that
assumption, not from the data. What the data adds is the timing: how fast, and what the fail-safe costs on real traffic.**

| threshold k x period (floor 30 ms) | false events / hour (validation) | pre-attack events | detected | median delay | max delay | within 100 ms | without authentication |
|---|---|---|---|---|---|---|---|
| 2 | 62.2 | 1 | 13/13 | 30 ms | 189 ms | 0.92 | 1/13 |
| 3 | 41.5 | 0 | 13/13 | 30 ms | 289 ms | 0.92 | 0/13 |
| 5 | 38.9 | 0 | 13/13 | 50 ms | 489 ms | 0.92 | 0/13 |
| 10 | 31.1 | 0 | 13/13 | 100 ms | 989 ms | 0.46 | 0/13 |

* **Detection (k = 3):** all 13 masquerade captures, within 27-30 ms for the 100 Hz IDs (speedometer, correlated signal, reverse
  lights, 12 of 13) and 289 ms for the 10 Hz engine-coolant message. This includes the six in-range reverse-light forgeries that every
  value-based rule in E8 missed (0/6), because the defence does not look at values. Without authentication the watchdog sees nothing
  (0/13): replacement keeps the frame rate unchanged.
* **The price (k = 3):** 41.5 false triggers per hour across all watched IDs, but they are concentrated: 28 of 32 events are in one
  deliberately odd capture (`ambient_dyno_drive_benign_anomaly`, 221/h); the real-road capture gave 4 events in 1,800 s, the
  diagnostics capture and the reverse capture none. If the watchdog watched only the three sensing-like IDs of the attacked signals
  (as the design does), 17 events in 0.77 h overall (22/h) and 4 events in 0.63 h on the real road, about 6 per hour. In the design
  every such trigger is a precautionary brake, so this is a real availability cost that the emulator (which has no such gaps) hid.
* Raising k lowers the false-trigger rate slowly (31/h at k = 10) and costs detection speed (median 100 ms): the threshold trades
  availability against reaction time, and none of the settings tested is free.
* A learning-criterion pitfall found on the way: the E8 rate IDS filter (coefficient of variation below 0.3) discards the speedometer
  ID (208) and the correlated-signal ID (1760) because a few rare long gaps (2.4 s, 9.5 s) inflate the standard deviation, although
  their median gap is exactly 10 ms. The first version of this replay inherited the filter and detected 1 of 13; with a robust
  criterion it detects 13 of 13. E8's rate-IDS result is unchanged, but its "periodic ID" set was narrower than necessary.
* Limits: one vehicle; labelled frames define "forged" exactly; fabrication-type attacks (extra frames, genuine ones continue) are
  rejected by authentication and do not silence the stream, so they are not a watchdog case; the watchdog thresholds are not tuned
  for a false-trigger budget; ROAD has no braking, so this validates detection timing and false-trigger cost only.

## E16 - embedded feasibility of the perception-side defences (`embedded/`, `experiments/e16_embedded_feasibility.py`)

`embedded/sdv_defences.c` implements the perception logic (TTC trigger, radar failover, disagreement trigger, authentication hook,
fail-safe watchdog) as portable C99 with fixed-width integers only: no floating point, no allocation, no loops, no libc (checked by a
static scan). The MAC itself is delegated (the caller passes the verdict). **Not run on a microcontroller.** Details: `docs/EMBEDDED.md`.

* **Done, without a compiler:** a line-by-line Python mirror of the C logic (the integer reference) reproduces the emulator's own
  floating-point decision (trigger source and time) in **120/120** emulator runs (6 defence configurations x 10 attack types; sources: 64
  sensor, 44 radar, 12 watchdog), and matches the design intent in **18/18** hand-built edge cases (exact TTC threshold, one millimetre
  above it, stale channels, rejected frames, the watchdog's exact limit, the disagreement trigger that the emulator never produces first).
  Rounding to millimetres never moved a decision in these runs.
* **Compiled and replayed (GCC 16.2.0 for x86-64 Windows, `-std=c99 -Wall -Wextra -Wpedantic -Werror -Os`, no warnings):** all 138 cases
  through the compiled binary match the integer reference **exactly** (trigger source, time, rejected frames: 138/138), match the design
  intent in 18/18 edge cases, and match the emulator's floating-point decision in 120/120 runs. `python embedded/verify.py` reproduces it.
* **Footprint, host build only:** module code 528 bytes (`size`: text 528, data 0, bss 0), state structure 52 bytes, configuration 24 bytes;
  host timing about 5 ns per frame-plus-tick call on a PC. These are indicative figures for an x86-64 host, **not** measurements on a
  microcontroller: a Cortex-M build will differ in size, and the host timing says nothing about an ECU.
* **Second compiler, Linux (GitHub Actions, GCC 13.3, x86-64, `-Os`):** the same 138 cases pass again (138/138, 18/18, 120/120); the module
  is 490 bytes of code against 528 bytes with the Windows GCC 16.2 build, so code size depends on the compiler and the figures are only
  indicative.
* Caveats for the paper: footprints will be host builds (indicative only); host timing says nothing about an ECU; real MAC cost and key
  handling are out of scope.

## E17 - real truncated HMAC instead of idealised authentication (`sdv/security/mac.py`, `experiments/e17_real_mac.py --samples 200`)

`auth_mode="hmac"` (default stays `"ideal"`): every sensor and radar frame carries its freshness counter and a truncated HMAC-SHA256 tag
over (CAN id, counter, distance in mm, speed in mm/s, obstacle flag), SecOC style; the receiver recomputes the tag and requires the
counter to increase. A gateway that alters the payload leaves the old tag, so a forged frame passes only by chance; an attacker holding
the key re-signs; replayed or reordered frames are rejected.

* **A. Forged frames that pass, measured** (10,631 forged frames): 4-bit MAC 6.26% accepted (theory 6.25%), 8-bit 0.395% (theory 0.391%),
  16-bit 0 (theory 0.0015%), 24-bit 0 (theory 6e-6%). The idealised mode's "perfect" rejection is therefore the 24-bit behaviour up to a
  forgery probability of about 6e-8 per frame.
* **B. Hazard volume with authentication + watchdog** (200 sampled attacks per variant, one fresh scenario each): dual masquerade 6.5%
  ideal / 8.5% (4-bit) / 6.5% (8, 16, 24-bit); dual masquerade with the key 39.5% in every mode; masquerade and sensor drift 0% in every
  mode. Truncating the MAC to 8 bits costs nothing measurable here because accepting an occasional forged frame (one in 256) neither
  triggers braking nor keeps the watchdog quiet (the gaps stay longer than 30 ms); 4 bits starts to show.
* **C. Decisions:** the 24-bit real MAC gives the same trigger source and outcome as the idealised mode in **800/800** attacked runs.
* **D. A side effect the idealised mode hid:** the freshness counter rejects genuine frames that an attack reorders. Under jitter
  injection (random per-frame holds) at least one genuine frame was rejected in 200/200 runs. Real systems must choose how strictly to
  enforce counter order.
* Limits: HMAC-SHA256 truncated (SecOC permits it; AES-CMAC is more usual on ECUs), keys are derived for simulation and key
  provisioning is not modelled, the verification time (0.5 ms) is still assumed, and the analytic bound's authentication assumption
  now reads "unless a forged frame collides with the truncated MAC (2^-bits per frame)".

## E18 - a second real vehicle: HCRL Car-Hacking against the flood model and the silence watchdog (`experiments/e18_hcrl_replay.py`)

Data: HCRL Car-Hacking (Song, Woo and Kim, *Vehicular Communications* 21, 2020; released for academic use), stored outside the
repository (`sdv/realdata/hcrl.py`; `HCRL_DIR`). Files used: attack-free driving (988,871 frames, 506 s, 27 IDs), DoS (300 bursts of ID 0x000),
fuzzy, RPM spoofing and gear spoofing. The bit rate is not stated in the release; 500 kbit/s is assumed. This experiment is **mostly
inconclusive**, and the reasons are part of the result.

* **The captures are lossy.** The DoS file logs 427 injected frames/s against the documented 3,333/s (about 13%): the logger loses
  frames when the bus is busy. So a long silence in the log can be bus starvation or logger loss, and the data cannot tell them apart.
* **(a) Real DoS against the flood bound: not validated.** 300 bursts, 4.56 s median (4.85 s longest), one every 7.6 s. Normal 10 ms
  frames are missing for 1.3 s on median per ID (up to 2.2 s), 100 ms and slower IDs up to 5 s or more. The analytic bound, computed
  from this vehicle's own measured traffic (bus load 0.52) with a periodic flood: the longest silence exceeds it for 22 of 26 IDs at a
  0.5 ms flood and 6 of 26 at the documented 0.3 ms flood (the highest-priority IDs: bound 16 to 71 ms against 1.1 to 1.6 s observed).
  For a saturating flood (one frame right after another) the bound is about the burst length (4.9 to 11 s) and 1 of 26 IDs exceeds it
  (ID 0xa1, a 100 ms message: silent 5.4 s against a 5.1 s bound, a 0.3 s overshoot, well inside the 1-2 s recovery tail seen in (b2), so recovery or logger loss could account for it). So **the capture is not consistent with a periodic 0.3 ms flood model**; it is
  consistent with a saturating flood (the backlog model that the production bound `latency_bound_ms` uses for every flood, whatever its rate), but equally with logger loss. What it does support: an unguarded flood removes 10 ms control
  traffic for 1 to 2 s at a time inside a 4.5 s burst, about thirteen times a 100 ms brake deadline (median over IDs), which is the worst case the model already assumes and the
  reason the gateway guard (keeping a flood off the safety bus) matters. The flood model's *rate* assumption is a weakness: a real
  attacker may saturate the bus, and the bound should be quoted for a saturating flood when the attacker's rate is not known.
* **(b) Silence watchdog on a second vehicle.** Learned on the first 253 s of attack-free driving (27 periodic IDs), tested on the next 253 s:
  0 false events at k = 2, 3, 5 and 10; the 95% upper bound is 43 per hour (rule of three; 253 s is too short to say more; ROAD gave about
  6/h on a real road). The silence of a DoS burst is noticed in 300 of 300 bursts, 127 ms median after the burst starts (95th percentile
  181 ms, max 245 ms), earlier than the bus alone might show because of the logger loss.
* **(b2) Recovery.** In 46 of 299 windows 1-2 s after a burst ended the watchdog still sees a silence, so the stretches between bursts
  are not clean normal driving and **no false-trigger rate is taken from the attack files**.
* **(c) Injection attacks do not selectively silence the spoofed ID.** Inside the bursts the share of genuine-frame gaps longer than the
  watchdog threshold is 4.7% for the spoofed RPM ID (other IDs 5.3% on median) and 7.8% for the gear ID (others 7.3%); fuzzy 31.7% across IDs.
  The spoofed stream is no worse off than the rest, which supports the premise that injection leaves the genuine stream running. But
  every ID has a far higher share than in attack-free driving (0%), so the genuine stream is degraded in these files (bus load and
  logger), and a watchdog would trip on that during sustained injection: availability cost, not detection.
* **Data quality.** Each file has one recording pause where recordings were joined (22 s to 7,745 s); outside the bursts the genuine rate
  is 1,800 to 1,840 frames/s against 1,953/s attack-free.
* **A bug found by the test, not the data:** the parser appended a timestamp before the ID of a malformed line failed to parse. The real
  files parse cleanly, so no result changed; fixed and covered by `tests/test_hcrl.py`.
* What this adds to the paper: a second vehicle's attack-free timing (the watchdog's thresholds transfer without retuning, zero false
  events in a short window), a real record of DoS burst length, and an honest negative result on validating the flood bound with
  lossy logs. What it does not add: a validation of the bound's tightness, or a false-trigger rate for injection attacks.

## Evidence chain and pipeline (`python -m sdv`, `sdv/evidence`)

* One command takes a requirement in plain English through spec extraction, red team, blue team, a second red
  round and an audited evidence bundle (about 13 s for 40 samples per family, no API key with `--blue enumerate`).
* The auditor re-runs every claim (10 base checks: formula, bound, violation reproduces, attack and KB citation,
  declared threat mapping, rule validity, benign false-alarm rate, in-time detection). Tamper tests confirm
  that falsified latencies, collision flags, attack parameters, KB fields, an unparseable formula, a rule that
  alarms on benign traffic and a rule that does not cover the violation are each caught.
* The bundle also records the same attack under the radar failover and under four defence configurations (`radar_or`,
  `+guard`, `+auth`, `+guard+auth`); the auditor re-runs each (outcome reproduces; analytic bound dominates the re-run and
  its "proves safe" verdict matches), 20 checks in a full bundle. Tamper tests catch a falsified latency or a tampered
  bound in any configuration.
* **A defect found by reading the first generated document:** retrieval matched the sensor masquerade to the
  knowledge-base pattern "DoS on CAN Bus", and the original audit passed because it only checked that the
  cited pattern existed. The bundle now cites an explicitly declared family -> pattern mapping
  (`KB_PATTERN_FOR`, the authors' judgement), records what retrieval suggested next to it, and the auditor
  fails a bundle that cites a real but wrong pattern.
* The bundle is machine-checked consistency on an emulated system, not a certified safety case.
* **Pipeline stages added after the freeze (requirement conformance, defence assessment, calibrated plant profile).**
  * *Conformance:* every simulated benign run meets "brake within 100 ms" at the default settings (slowest about 91-101 ms, the
    baseline chain misses it in some draws), but the analytic worst case is about 147-149 ms, so 100 ms is **not provable**; the
    smallest provable deadline for this chain is about 150 ms. The bound is dominated by the assumed compute-time worst cases
    (perception, decision and actuator together about 136 of 149 ms), so this is a statement about those assumptions.
  * *Defence assessment:* reproduces the E12 picture automatically. At 40 samples per variant under the CARLA-like plant: failover
    removes the single-channel attacks, the guard removes the untrusted-segment flood, authentication plus the watchdog leaves the
    dual-sensor attacker at about 2% in a 40-sample run, but the 40-sample figure is noisy: with 600 distinct scenarios (E12) it is 4.3%
    [3.0%, 6.3%]. The safety-bus flood (about 25-32%) and the key holder (about 43-65%) stay open. It reports 95% upper bounds because
    zero hazards in 40 samples still allows 9%.
  * *Two defects found while building it:* (1) the auditor caught that a rule verified alone can push the **deployed** monitor over
    the false-alarm cap (0.017 alone, 0.033 deployed); the pipeline now has a deployment check that drops such rules. (2) The first
    assessment cycled through only 6 scenarios, so one very tight scenario counted as about 1/6 of the sample and showed a 15% residual
    for the dual-sensor attacker; with one fresh scenario per sample it is 2%, in line with E14.
  * *Calibrated plant:* `experiments/profiles/carla_model3.json` (5.31 m/s^2, 50 ms ramp, from CARLA run 4, transcribed from console
    output). The plant changes hazard outcomes and points of no return, not the end-to-end latency, so the conformance numbers do
    not change with the profile.

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
* Raw LLM replies live in `outputs/llm_cache/` (committed, about 1 MB); they are the evidence behind the E4/E6
  tables and make every number reproducible offline with `--offline`. The gpt-oss-120b E4 run, first incomplete, was completed on 2026-10-15 (all conditions, 120/120).
* **Freeze (2026-10-07):** `python experiments/reproduce_all.py` ran end to end (16 steps, all ok). E1 and E9-E12 reproduce
  the recorded tables line for line; E2-E6 and the pipeline ran without error. E13 (CARLA) is not part of it: it has never
  been run.
