# Threat model and what the defences assume

Source material for the paper's threat-model and limitations sections. Every number is from `experiments/RESULTS.md` (E12, E17, E18).

## Attacker positions

| Position | Capability | Families | Stopped by |
|---|---|---|---|
| Untrusted segment (OBD-II, infotainment) | send frames to the gateway | floods, priority abuse, low-and-slow DoS | gateway guard (whitelist + token bucket) |
| Gateway or a node on the safety bus, no key | alter, delay, drop or flood frames | masquerade, drift, suppression, jitter, flood from the safety bus | radar failover (single channel); authentication + watchdog (forgery) |
| Same, **holding the signing key** | sign forged frames correctly | dual masquerade with the key | nothing in this design |

## What each defence assumes (the paper must say these)

* **Radar failover** assumes the attacker reaches only one of the two sensing channels. A dual-channel attacker defeats it.
* **Gateway guard** assumes the flood really enters through the gateway. A node already on the safety bus is invisible to it:
  25.0% of that flood's parameter space still causes a collision after all defences (E12).
* **Authentication + watchdog** assumes the attacker does **not** hold the key. Key provisioning, rotation, storage and revocation
  are not modelled; keys in the simulation are derived from a seed. With the key, the dual-sensor attacker succeeds in 43.0% of
  the parameter space in every defence configuration (E12) and 39.5% with a real truncated MAC (E17).
* **The fail-safe watchdog trades integrity for availability.** Corrupting both channels makes it brake with nothing in the way
  (0/100 to 100/100 unwanted braking in E12), and a key holder can force unwanted braking too. This is a design choice, not a free win.
* **Truncated MAC.** 24 bits behaves like the idealised mode (800/800 identical decisions); 8 bits lets about 1 forged frame in 256 through
  and costs nothing measurable here; 4 bits starts to show (E17). The freshness counter also rejects genuine frames that an attack reorders.

## What is outside the model

* Compromised ECU software or firmware, physical access, sensor hardware faults, and attackers who can jam the physical layer.
* Key management: how keys get into ECUs and what happens when one leaks. The result "a key holder defeats this design" is therefore a
  boundary of the claim, not a finding about any real key scheme.
* More than one safety function: only the brake chain is modelled.
* A real bus: the CAN timing is emulated with assumed ECU compute times (varied in E11) and braking physics (varied in E14, checked
  against CARLA in E13). A real vehicle may differ.

## What a reviewer should take from this

The analytic bound is valid for the stated attacker models and compute-time assumptions; it is checked by simulation
(0 violations in 31,200 runs) and by adversarial search (0 of 260). It is not a safety certificate for a real vehicle.
Two real-data checks (ROAD, HCRL) support the attacker model qualitatively and the watchdog's timing quantitatively on two
vehicles; the HCRL flood captures are lossy and cannot validate the flood bound's tightness (E18).
