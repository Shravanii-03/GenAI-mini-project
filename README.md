# Temporal Safety and Threat Detection for Software-Defined Vehicles

Research prototype that checks safety-critical timing requirements (for example
"brake within 100 ms if an obstacle is detected") on a simulated SDV, injects
cyber attacks, and uses an LLM with retrieval over a small automotive knowledge
base to explain violations and draft threat analyses.

> **Status: being rebuilt.** The current pipeline generates delays and attacks
> synthetically, so its results should not be read as measurements. The rebuild
> plan (measured latency on a CAN bus, bus-level attacks, STL monitors, a
> detection-margin metric and baseline-controlled evaluation) is tracked in the
> `rebuild` branch.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then put your Groq API key in .env
```

The LLM is read from `config.yaml` (`llm.model`). `.env` is git-ignored; never
commit it.

## Run

```bash
pytest tests/ -v                   # unit tests, no API key needed
python Agent1.py                   # iterative reasoning agent
python realtime_monitor.py         # 50 ms real-time monitoring loop
streamlit run dashboard/app.py     # dashboard
```

## Layout

| Path | Purpose |
|---|---|
| `parser.py`, `timing_extractor.py`, `multi_lang_parser.py` | Requirement and code parsing |
| `rag_engine.py`, `Knowledge_base/` | TF-IDF retrieval over small JSON catalogs |
| `reasoning_engine.py`, `threat_generator.py` | Risk scoring and LLM threat reasoning |
| `vehicle_simulator.py`, `attack_injector.py`, `simulator_rl.py` | Simulation, attacks, Q-learning |
| `dashboard/` | Streamlit dashboard |
| `config.yaml`, `config.py` | Configuration |

## Rebuilt core (`sdv/` package)

| Module | Purpose |
|---|---|
| `sdv/sim`, `sdv/bus` | Discrete-event engine and CAN emulator (arbitration, bit-accurate timing) |
| `sdv/system` | Emulated sensor, perception, decision and actuator chain, with optional failover to a redundant radar |
| `sdv/plant` | Braking model with an exact point of no return |
| `sdv/attacks` | Eight bus-level attack families (plus the dual-sensor attacker and an availability attack) with capabilities and search bounds |
| `sdv/bus/guard.py` | Gateway guard (whitelist + token bucket) between an untrusted segment and the safety bus |
| `sdv/analysis` | Attack-aware worst-case latency bound (CAN response-time analysis + attacker model) and the attack space it proves safe |
| `sdv/monitors` | Deadline (STL robustness), frequency IDS, plausibility, fused monitors |
| `sdv/metrics` | Detection margin and run-level F1 |
| `sdv/spec` | Natural-language requirement -> validated timing spec (bounded-response STL, deterministic validator, repair loop) |
| `sdv/rag` | Normalised KB corpora, BM25, legacy TF-IDF wrapper, optional dense/hybrid, Recall@k/MRR |
| `sdv/blue` | Monitor rule language, deterministic verifier, exhaustive and random baselines, LLM blue agent |
| `sdv/realdata` | ROAD dataset loader and semantics-free detectors (real attacks; data stays outside the repo) |
| `sdv/carla_check` | Pure helpers for the CARLA plant check (`experiments/e13_carla_plant.py`, not yet run; see `docs/CARLA.md`) |
| `sdv/evidence` | Evidence bundle, auditor that re-runs every claim (incl. failover and bound checks), GSN-style rendering |
| `sdv/pipeline.py` | End-to-end orchestrator (`python -m sdv`) |
| `sdv/llm` | Disk-cached, rate-limit-aware LLM calls |
| `datasets/benchmark` | 120 labelled timing requirements, 106 labelled retrieval queries |
| `experiments/` | `phase1_demo.py`, `e1_pilot.py` (detector ranking by F1 vs margin) |

```bash
python experiments/e1_pilot.py --n 300 --seed 1
```

## Run the whole pipeline

```bash
python -m sdv --requirement "Brake within 100 ms if an obstacle is detected." --blue enumerate
# -> spec, red team, verified monitor rules, residual risk, audited evidence in outputs/pipeline_run/
python experiments/reproduce_all.py --quick     # regenerate the result tables offline
docker build -t sdv-safety . && docker run --rm sdv-safety     # tests in a container
```

`--blue llm --llm-model <groq model>` lets an LLM propose the monitor rules (needs `GROQ_API_KEY`); every
proposal still has to pass the same deterministic verifier. Experiment results and their caveats are in
`experiments/RESULTS.md`.

## Known limitations

- The knowledge base is small (26 VSS signals, 11 CAN messages, 8 attack
  patterns, 12 timing/event rules). Timing limits in it are assumed values, not
  quotations from ISO 26262.
- The rebuilt core runs on an **emulated** CAN network; ECU compute times, bus load
  and the mitigation response time are assumptions set in `config.yaml`.
- The legacy modules (`vehicle_simulator.py`, `attack_injector.py`, ...) still generate
  delays and attacks synthetically and are being replaced.
