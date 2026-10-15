# Embedded feasibility of the perception-side defences (E16)

`embedded/sdv_defences.c` is the logic of the brake chain's perception (TTC trigger, radar failover, disagreement trigger,
authentication hook, fail-safe watchdog) as portable C99: fixed-width integers only, no floating point, no allocation, no loops,
no libc. It is a feasibility artefact: **it has not been run on a microcontroller** and it is not a certified implementation.
The MAC itself is not computed there; the design delegates it to a hardware security module and the caller passes the verdict.

## What is verified without a compiler (done)
`python experiments/e16_embedded_feasibility.py` generates 138 cases and checks the **integer reference** (a line-by-line Python
mirror of the C code) in Python:
- 120 cases recorded from emulator runs (6 defence configurations x 10 attack types): the integer logic reproduces the emulator's
  own floating-point decision, trigger source and time, in 120/120.
- 18 hand-built edge cases (exact TTC threshold, one millimetre above it, stale channels, rejected frames, the watchdog's exact
  limit, a disagreement trigger the emulator never produces first): 18/18 match the design intent.

## Compile-and-replay (done: PASS)
Result on GCC 16.2.0 (x86-64, `-Os`): 138/138 cases identical to the reference, 18/18 edge cases, 120/120 emulator decisions;
module text 528 bytes, state 52 bytes (host build, indicative only).

`python embedded/verify.py` compiles the module with `-std=c99 -Wall -Wextra -Wpedantic -Werror`, replays all cases through the
compiled binary and requires an **exact** match with the reference (code, time, rejected frames). It also prints the code size
(`size`), the state size and a host timing. Standard library only.

On Google Colab (a compiler is already there):
```bash
# on your laptop, in the project folder
git archive -o embedded.zip HEAD embedded
```
```python
# in Colab
from google.colab import files; files.upload()          # choose embedded.zip
!unzip -q -o embedded.zip && python3 embedded/verify.py
```
Send the printed output (it ends with `RESULT: PASS` or `FAIL`). A local compiler works too (`CC=gcc python embedded/verify.py`).

## How to describe it honestly
- "The decision logic is small and free of floating point and allocation" is checked by `verify.py` (static scan) and by the code
  itself.
- Code size and state size are measured on a **host** build; an MCU build will differ. The timing is a host figure and says nothing
  about an ECU.
- Rounding to millimetres can in principle move a decision by one frame; on the 120 emulator cases it never did.
