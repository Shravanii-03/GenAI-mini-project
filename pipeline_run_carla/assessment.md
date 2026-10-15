# Requirement conformance and defence assessment

```
requirement conformance (deadline 100 ms; 36 benign runs over 12 scenarios)
  baseline       violated in simulation: analytic worst case 147 ms, slowest simulated run 101 ms
                 smallest deadline that can be proven for this chain: 147 ms
  all defences   met in simulation only (not provable): analytic worst case 149 ms, slowest simulated run 92 ms
                 smallest deadline that can be proven for this chain: 149 ms

defence assessment (40 sampled attacks per variant; hazard share by configuration; bound violations 0/2600)
  attack variant                           none     radar_or       +guard        +auth  +guard+auth   cheapest sufficient defence
  dos_flood                                 30%          30%           0%          22%           0%   +guard (95% upper bound on hazard 9%)
  priority_abuse                             0%           0%           0%           0%           0%   none (95% upper bound on hazard 9%)
  low_slow_dos                               0%           0%           0%           0%           0%   none (95% upper bound on hazard 9%)
  selective_suppression                      0%           0%           0%           0%           0%   none (95% upper bound on hazard 9%)
  sensor_drift_spoof                        18%           0%           0%           0%           0%   radar_or (95% upper bound on hazard 9%)
  masquerade                                62%           0%           0%           0%           0%   radar_or (95% upper bound on hazard 9%)
  gateway_delay                             22%           0%           0%           0%           0%   radar_or (95% upper bound on hazard 9%)
  jitter_injection                           8%           0%           0%           0%           0%   radar_or (95% upper bound on hazard 9%)
  dual_masquerade                           60%          60%          60%           2%           2%   OPEN (best +auth: 2%)
  dos_flood (safety-bus node)               32%          32%          32%          32%          32%   OPEN (no defence helps: 32%)
  low_slow_dos (safety-bus node)             0%           0%           0%           0%           0%   none (95% upper bound on hazard 9%)
  masquerade (holds key)                    42%           0%           0%           0%           0%   radar_or (95% upper bound on hazard 9%)
  dual_masquerade (holds key)               65%          65%          65%          65%          65%   OPEN (no defence helps: 65%)
  open after every defence: dual_masquerade, dos_flood (safety-bus node), dual_masquerade (holds key)
  (covered = sampled hazard share at most 2%; the 95% upper bound shows how little a small sample can certify: with 40 samples, zero hazards still allows 9%)
```
