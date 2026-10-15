# Knowledge base provenance

| File | Origin | Notes |
|---|---|---|
| `vss_real_v6.1.json` | Official COVESA Vehicle Signal Specification release v6.1, `vss.json` (downloaded 2026-10-07 from https://github.com/COVESA/vehicle_signal_specification/releases/download/v6.1/vss.json, 370,784 bytes, sha256 prefix `bef9ad501b38edd6`) | 1,382 leaf signals. Only 16 of the 26 paths in `vss_signals.json` exist in it. |
| `vss_signals.json` | Hand-written by the project authors | 10 of 26 paths are **not** real VSS paths (e.g. `Vehicle.ADAS.PedestrianDetection.*`, `Vehicle.ADAS.ABS.IsActive`). Do not describe it as VSS-compliant. |
| `vss_full.json` | Hand-written; despite the name it is not the COVESA catalogue | Contains custom fields such as `iso_reference` and `timing_constraint_ms`. |
| `can_messages.json` | Hand-written, illustrative IDs | Not taken from a real vehicle database. |
| `attack_patterns.json` | Hand-written | Not mapped to a published taxonomy. |
| `iso26262_rules.json` | Hand-written | Rule IDs and the latency limits are assumed values, not quotations from ISO 26262. |
