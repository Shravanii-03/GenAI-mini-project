# Evidence bundle: REQ-1

**G1.** The vehicle meets: *Brake within 100 ms if an obstacle is detected.* (extracted by regex baseline)

## S1. Specification
- Deadline 100.0 ms; formula `G(obstacle_detected -> F[0,100 ms] brake_applied)` [PASS] [PASS]

## S2. Counter-example found by the red team
- Attack `sensor_drift_spoof` with parameters {'rate_m_per_s': 14.46889597707714, 'duration_ms': 545.1656119956572, 'start_offset_ms': -360.1678280697764}
- Scenario {'v0_kmh': 62.35566406711919, 'd0_m': 30.64916918316855, 'road': 'dry', 'cpu_load': 0.28131039384515183}, seed 604131316
- Recorded: latency 268.3 ms, robustness -168.3 ms, collision=True, latest safe latency 113.5 ms [PASS] [PASS]

## S3. Threat
- Family `sensor_drift_spoof`; attacker capability: compromised ECU or gateway between a sender and the bus [PASS]
- Knowledge-base pattern ATK-002 *Sensor Data Injection* (severity CRITICAL, likelihood MEDIUM, TARA risk 0.88); KB mitigation: Sensor data validation, redundant sensing, anomaly detection [PASS] [PASS]
- Retrieval over the knowledge base independently suggests the same pattern.

## S4. Mitigation
- Monitor rule `{'type': 'cross_check', 'id_a': '0x2A0', 'id_b': '0x2B0', 'field': 'distance_m', 'tol': 1.0, 'max_skew_ms': 15.0}` [PASS]
- Verified false-alarm rate 0.000 (cap 0.02), turns 29 missed hazard(s) into in-time detections [PASS] [PASS]

## S5. Failover to the redundant sensor
- Policy `radar_or`: latency 70.0 ms; the collision is prevented [PASS]
- Analytic worst-case latency 138.4 ms vs point of no return 113.5 ms: the bound is too conservative to prove safety (simulation decides) [PASS]

## S6. Defence configurations (same attack, same seed)
- `radar_or`: latency 70.0 ms, no collision; analytic worst case 138.4 ms vs point of no return 113.5 ms, bound does not prove safety [PASS] [PASS]
- `+guard`: latency 70.0 ms, no collision; analytic worst case 138.4 ms vs point of no return 113.5 ms, bound does not prove safety [PASS] [PASS]
- `+auth`: latency 70.7 ms, no collision; analytic worst case 139.4 ms vs point of no return 113.5 ms, bound does not prove safety [PASS] [PASS]
- `+guard+auth`: latency 70.7 ms, no collision; analytic worst case 139.4 ms vs point of no return 113.5 ms, bound does not prove safety [PASS] [PASS]

## Residual risk
- `dual_masquerade`: 24/40 sampled attacks still cause a collision with no in-time alarm

## Audit: 20/20 checks re-verified (coverage 100%)
- spec_formula_parses: PASS - G(obstacle_detected -> F[0,100 ms] brake_applied)
- spec_bound_matches_deadline: PASS - formula 100.0 ms vs deadline 100.0 ms
- violation_reproduces: PASS - re-run latency 268.313 vs recorded 268.313
- violation_is_real: PASS - robustness -168.3 ms, collision=True
- attack_is_known: PASS - sensor_drift_spoof
- threat_mapping_is_declared: PASS - declared for sensor_drift_spoof: ATK-002, cited: ATK-002
- kb_pattern_matches_the_knowledge_base: PASS - ATK-002 Sensor Data Injection
- rule_is_valid: PASS - 
- rule_fpr_reproduces: PASS - deployed monitor false-alarm rate 0.017 (cap 0.02)
- rule_catches_the_violation_in_time: PASS - detected=True, in_time=True
- failover_reproduces: PASS - re-run latency 70.012 vs recorded 70.012, collision=False
- failover_bound_is_sound: PASS - bound 138.4 ms vs observed 70.012 ms, point of no return 113.5 ms, proves safe=False
- defence[radar_or]_reproduces: PASS - re-run latency 70.012 vs recorded 70.012, collision=False
- defence[radar_or]_bound_is_sound: PASS - bound 138.4 ms vs observed 70.012 ms, point of no return 113.5 ms, proves safe=False
- defence[+guard]_reproduces: PASS - re-run latency 70.012 vs recorded 70.012, collision=False
- defence[+guard]_bound_is_sound: PASS - bound 138.4 ms vs observed 70.012 ms, point of no return 113.5 ms, proves safe=False
- defence[+auth]_reproduces: PASS - re-run latency 70.727 vs recorded 70.727, collision=False
- defence[+auth]_bound_is_sound: PASS - bound 139.4 ms vs observed 70.727 ms, point of no return 113.5 ms, proves safe=False
- defence[+guard+auth]_reproduces: PASS - re-run latency 70.727 vs recorded 70.727, collision=False
- defence[+guard+auth]_bound_is_sound: PASS - bound 139.4 ms vs observed 70.727 ms, point of no return 113.5 ms, proves safe=False

*Machine-checked consistency on an emulated system; not a certified safety case.*