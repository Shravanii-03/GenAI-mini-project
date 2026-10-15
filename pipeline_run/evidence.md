# Evidence bundle: REQ-1

**G1.** The vehicle meets: *Brake within 100 ms if an obstacle is detected.* (extracted by regex baseline)

## S1. Specification
- Deadline 100.0 ms; formula `G(obstacle_detected -> F[0,100 ms] brake_applied)` [PASS] [PASS]

## S2. Counter-example found by the red team
- Attack `masquerade` with parameters {'bias_m': 14.62450367107581, 'phase_shift_ms': 4.180924236713443, 'duration_ms': 717.3335964002966, 'start_offset_ms': -247.41484544656478}
- Scenario {'v0_kmh': 60.89799800482294, 'd0_m': 20.459288863165526, 'road': 'dry', 'cpu_load': 0.4526772829259311}, seed 906308217
- Recorded: latency 165.1 ms, robustness -65.1 ms, collision=True, latest safe latency 106.8 ms [PASS] [PASS]

## S3. Threat
- Family `masquerade`; attacker capability: compromised ECU or gateway between a sender and the bus [PASS]
- Knowledge-base pattern ATK-002 *Sensor Data Injection* (severity CRITICAL, likelihood MEDIUM, TARA risk 0.88); KB mitigation: Sensor data validation, redundant sensing, anomaly detection [PASS] [PASS]
- Note: retrieval suggested ATK-007 *DoS on CAN Bus* instead; the declared mapping for this attack family is used because retrieval is unreliable for this link.

## S4. Mitigation
- Monitor rule `{'type': 'cross_check', 'id_a': '0x2A0', 'id_b': '0x2B0', 'field': 'distance_m', 'tol': 1.0, 'max_skew_ms': 15.0}` [PASS]
- Verified false-alarm rate 0.000 (cap 0.02), turns 18 missed hazard(s) into in-time detections [PASS] [PASS]

## S5. Failover to the redundant sensor
- Policy `radar_or`: latency 78.3 ms; the collision is prevented [PASS]
- Analytic worst-case latency 152.0 ms vs point of no return 106.8 ms: the bound is too conservative to prove safety (simulation decides) [PASS]

## S6. Defence configurations (same attack, same seed)
- `radar_or`: latency 78.3 ms, no collision; analytic worst case 152.0 ms vs point of no return 106.8 ms, bound does not prove safety [PASS] [PASS]
- `+guard`: latency 78.3 ms, no collision; analytic worst case 152.0 ms vs point of no return 106.8 ms, bound does not prove safety [PASS] [PASS]
- `+auth`: latency 79.0 ms, no collision; analytic worst case 153.1 ms vs point of no return 106.8 ms, bound does not prove safety [PASS] [PASS]
- `+guard+auth`: latency 79.0 ms, no collision; analytic worst case 153.1 ms vs point of no return 106.8 ms, bound does not prove safety [PASS] [PASS]

## Residual risk
- `dual_masquerade`: 18/40 sampled attacks still cause a collision with no in-time alarm

## Audit: 20/20 checks re-verified (coverage 100%)
- spec_formula_parses: PASS - G(obstacle_detected -> F[0,100 ms] brake_applied)
- spec_bound_matches_deadline: PASS - formula 100.0 ms vs deadline 100.0 ms
- violation_reproduces: PASS - re-run latency 165.095 vs recorded 165.095
- violation_is_real: PASS - robustness -65.1 ms, collision=True
- attack_is_known: PASS - masquerade
- threat_mapping_is_declared: PASS - declared for masquerade: ATK-002, cited: ATK-002
- kb_pattern_matches_the_knowledge_base: PASS - ATK-002 Sensor Data Injection
- rule_is_valid: PASS - 
- rule_fpr_reproduces: PASS - deployed monitor false-alarm rate 0.017 (cap 0.02)
- rule_catches_the_violation_in_time: PASS - detected=True, in_time=True
- failover_reproduces: PASS - re-run latency 78.286 vs recorded 78.286, collision=False
- failover_bound_is_sound: PASS - bound 152.0 ms vs observed 78.286 ms, point of no return 106.8 ms, proves safe=False
- defence[radar_or]_reproduces: PASS - re-run latency 78.286 vs recorded 78.286, collision=False
- defence[radar_or]_bound_is_sound: PASS - bound 152.0 ms vs observed 78.286 ms, point of no return 106.8 ms, proves safe=False
- defence[+guard]_reproduces: PASS - re-run latency 78.286 vs recorded 78.286, collision=False
- defence[+guard]_bound_is_sound: PASS - bound 152.0 ms vs observed 78.286 ms, point of no return 106.8 ms, proves safe=False
- defence[+auth]_reproduces: PASS - re-run latency 78.986 vs recorded 78.986, collision=False
- defence[+auth]_bound_is_sound: PASS - bound 153.1 ms vs observed 78.986 ms, point of no return 106.8 ms, proves safe=False
- defence[+guard+auth]_reproduces: PASS - re-run latency 78.986 vs recorded 78.986, collision=False
- defence[+guard+auth]_bound_is_sound: PASS - bound 153.1 ms vs observed 78.986 ms, point of no return 106.8 ms, proves safe=False

*Machine-checked consistency on an emulated system; not a certified safety case.*