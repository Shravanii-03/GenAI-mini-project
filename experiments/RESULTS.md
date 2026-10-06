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

## Caveats

* Metric fix: an alarm before the attack starts is a false alarm and earns no margin
  (`credited_alarm_us`). It changed none of the numbers above.
* Per-family hazard counts in E3 are small (some under 10); do not over-read them.
* LLM refusals occurred in an early generation attempt (stealth framing); refusals are
  retried and never cached.
