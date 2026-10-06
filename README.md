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

## Known limitations

- The knowledge base is small (26 VSS signals, 11 CAN messages, 8 attack
  patterns, 12 timing/event rules). Timing limits in it are assumed values, not
  quotations from ISO 26262.
- Simulated delays and attacks are generated, not measured on a real bus.
