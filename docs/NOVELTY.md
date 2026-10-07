# Novelty analysis (2026-10-07)

Purpose: decide what this project can honestly claim as new, based on the closest prior work found.
This is a focused search, not a systematic survey. Every source below is marked with how much of it was
actually read.

## Verdict in one paragraph

The **concept** behind our "detection margin" (an attack must be detected before the system can no longer
avoid an unsafe state; judge a detector by detection delay against that deadline) **already exists** in the
cyber-physical-systems security literature as the *detection deadline*. It must be cited and the metric
renamed accordingly. What is not covered by what I found: applying it to **bus-level CAN attacks** (arbitration,
queueing, injection, gateway tampering) with a closed-form braking plant, comparing **standard IDS-style
monitors** by in-time detection, characterising the **hazard volume** of attack families, and the specific
**masquerade blind spot** with its redundancy fix and irreducible dual-sensor residual. That is an
incremental, application-level contribution plus a reproducible artifact, not a new metric.

## Closest prior work

| Work | What it does | Read | What it means for us |
|---|---|---|---|
| Akowuah & Kong, *Real-Time Adaptive Sensor Attack Detection in Autonomous CPS*, IEEE RTAS 2021 | Defines the **detection deadline** ("timing constraint before which attacks must be detected", e.g. a speed-sensor spoof must be caught before the car hits the one in front); argues detectors must meet it; adapts a CUSUM+LSTM detector's delay/false-alarm trade-off to the deadline; AEGIS automotive data | pages 1-3 (abstract, intro, system model) | **Direct antecedent of our margin.** Concept not new. Differences: physical *sensor* attacks, residual/CUSUM detectors on sensor streams, no CAN bus, no attack families, no search |
| Akowuah, Fletcher & Kong, *Variable Window and Deadline-Aware Sensor Attack Detector for Automotive CPS*, 2023 | Variable time-window detector sized to the detection deadline | pages 1-2 | Same lineage; same differences |
| Zhang, Chen, Kong & Cardenas, *Real-Time Attack-Recovery for CPS Using Linear Approximations*, RTSS 2020 | Reachability-based **deadline calculator**; recovery control after an attack is detected | pages 1-3 | Source of the reachability-based safety-deadline idea; about recovery, not detector evaluation |
| Berdich & Groza, *Cyberattacks on Adaptive Cruise Controls and Emergency Braking Systems*, IEEE Trans. Reliability 73(2), 2024 | Impact assessment of CAN-bus attacks on AEB/ACC in Simulink, assuming a low false-negative IDS; countermeasures | **abstract only** (paywalled) | Closest *automotive* neighbour for "CAN attack -> AEB safety outcome". Must be read in full before submission to confirm they do not evaluate detector timeliness or search for worst-case attacks |
| Stachowski, Gaynier & LeBlanc, *An Assessment Method for Automotive IDS Performance*, NHTSA DOT HS 812 708, 2019 | Government assessment method: false-negative/positive rate, recall, precision, F-score, informedness, markedness. "Detection speed" is listed but **set aside** as "not considered relevant at this stage" | metrics section | Supports the motivation: the standard automotive IDS assessment has no safety-based timeliness measure |
| *Beyond Time to Collision: The Point of No Return...*, Applied Sciences 16(8), 2026 | PONR as a physically grounded indicator of whether a rear-end collision can still be avoided (dashcam video) | abstract only | Our "latest safe latency" is the same idea from the braking side; cite for the concept. Traffic safety, not security |
| Bak et al., *Large Language Models as Falsifiers for CPS*, 2026 | LLM-driven minimisation of STL robustness on ARCH-COMP | abstract only | General CPS falsification; not CAN, timing or security |
| Verification-guided LLM synthesis of IDS rules (CIKM 2026), GenTI, GRIDAI | LLM proposes rules, deterministic verification with benign counter-examples (CEGIS) | abstracts via search | The *pattern* "LLM proposes, verifier decides" is established for network IDS. Ours is an automotive/timing application |
| Cross-Modal Phantom (2026) and sensor-fusion spoofing work | Coordinated spoofing of several sensors defeats redundancy checks | abstract | Our dual-sensor attacker is a known idea; supports the "irreducible residual" finding |
| Petrovic et al., 2025-2026 (event chains, VSS, CAN, LLM) | Closest LLM-for-SDV framework (cited in our earlier paper) | abstracts | No timing validation, attack injection or RL; our earlier paper overlapped heavily with it |

## What we can claim, and how strongly

| Claim | Status | Wording to use |
|---|---|---|
| Detection margin as a new metric | **Not defensible** | "We adopt the detection-deadline notion (Akowuah & Kong) for CAN-bus IDS evaluation, with an exact point of no return from a braking model" |
| F1/recall overstate protection: the best fused detector flags only ~62% of attack-induced hazards in time | Supported (emulation, 3 seeds); fits the RTAS argument | Report as an empirical finding in a new setting |
| Constant-bias masquerade that starts before the obstacle appears is invisible to self-consistency checks (2/38 in time); a redundant-sensor cross-check fixes the single-sensor case; the dual-sensor attacker is an irreducible residual (~43%) | Supported; mechanism verified directly | Main technical finding |
| Hazard volume per attack family; search comparison (BO/ES/Q-learning no better than random; an LLM prior helps where it names the mechanism) | Supported, small scale | Secondary, with the limits stated |
| LLM-synthesised monitor rules | **Weak**: random proposals + the verifier match the LLM | State the negative result; do not claim the LLM improves detection |
| Audited evidence chain (re-runs every claim; tamper-tested) | Modest but concrete | Artifact contribution, "not a certified safety case" |
| Knowledge-base audit: 16/26 KB signals are real VSS; ~86-100% of VSS paths an LLM lists unaided are fabricated | Supported for our KB and 3 models | Caution for LLM+VSS work; avoid generalising |

## Suggested contribution list

1. A CAN-bus, hazard-grounded evaluation of IDS-style monitors using the detection-deadline notion, showing that
   F1/recall overstate protection and exposing a concrete blind spot (constant-bias masquerade).
2. Verified synthesis of redundancy-based monitor rules and a characterisation of the residual risk the rule
   language cannot remove (consistent dual-sensor spoofing needs message authentication). The verifier, not the
   LLM, does the work; we report this.
3. An open, reproducible artifact: bus emulator, attack library with declared capabilities, labelled spec and
   retrieval benchmarks, an auditor that re-runs every claim in an evidence bundle, and a knowledge-base audit.

## Risks that remain

- **Novelty is incremental.** Expect a reviewer who knows the detection-deadline literature to say so. Fit is
  better for applied automotive/security venues and workshops than for a top-tier venue.
- **Not yet checked:** the full text of Berdich & Groza; the Syracuse group's later CAN-related papers
  ("AI-enabled Real-Time Sensor Attack Detection", the 2025 adaptive anomaly-detection survey); a Google
  Scholar pass for "detection deadline" + "CAN" + "intrusion detection".
- **Everything is on an emulation with assumed ECU timings.** Real attack data (ROAD / Car-Hacking) and a CARLA
  confirmation would answer the strongest objection.

## References to cite

- F. Akowuah, F. Kong. Real-Time Adaptive Sensor Attack Detection in Autonomous Cyber-Physical Systems. IEEE RTAS 2021. https://par.nsf.gov/servlets/purl/10294496
- F. Akowuah, K. Fletcher, F. Kong. Variable Window and Deadline-Aware Sensor Attack Detector for Automotive CPS. 2023. https://par.nsf.gov/servlets/purl/10424741
- L. Zhang, X. Chen, F. Kong, A. Cardenas. Real-Time Attack-Recovery for Cyber-Physical Systems Using Linear Approximations. IEEE RTSS 2020. https://users.soe.ucsc.edu/~alacarde/papers/RTSS2020RTRecovery_png.pdf
- A. Berdich, B. Groza. Cyberattacks on Adaptive Cruise Controls and Emergency Braking Systems: Adversary Models, Impact Assessment, and Countermeasures. IEEE Trans. Reliability 73(2), 2024. https://ieeexplore.ieee.org/document/10478772/
- S. Stachowski, R. Gaynier, D. LeBlanc. An Assessment Method for Automotive Intrusion Detection System Performance. NHTSA DOT HS 812 708, 2019. https://rosap.ntl.bts.gov/view/dot/41006/dot_41006_DS1.pdf
- Beyond Time to Collision: The Point of No Return as a Reliable Safety Indicator in Rear-End Vehicle Conflicts. Applied Sciences 16(8), 2026. https://www.mdpi.com/2076-3417/16/8/3869
- A. ArjomandBigdeli, J. Zhou, S. Bak. Large Language Models as Falsifiers for Cyber-Physical Systems. 2026. https://arxiv.org/abs/2609.20752
- Verification-Guided Specification Synthesis with LLMs for Intrusion Detection Rules. CIKM 2026. https://arxiv.org/abs/2608.22889
- N. Petrovic et al. LLM-Empowered Functional Safety and Security by Design in Automotive Systems. 2026. https://arxiv.org/abs/2601.02215
