# CARLA check of the braking plant (E13)

**Status: written, not run.** `experiments/e13_carla_plant.py` targets the CARLA 0.9.15 Python API and has never been
executed against a live server (this machine has no GPU and no CARLA). Its analysis helpers are unit-tested
(`tests/test_sdv_carla_analysis.py`). Treat any claim about CARLA as unsupported until the script has been run and its
output committed.

## What it can and cannot show
- It checks the **plant**: for a speed and an obstacle gap, is the emulator's closed-form point of no return (the largest
  brake latency that still avoids a collision) close to the one a physics engine gives? It reports the error for the assumed
  parameters (`config.yaml`: friction 0.8, ramp 50 ms) and for parameters fitted from CARLA's own braking response.
- It does **not** validate the CAN emulation, ECU timings or the attacks. Those stay emulated.

## Running it
CARLA's server needs a GPU with Vulkan. Options, most to least reliable:
1. a local Windows/Linux machine with an NVIDIA GPU (CARLA 0.9.15 release, `CarlaUE4.exe -quality-level=Low`)
2. a rented Linux GPU instance running the CARLA docker image headless (`-RenderOffScreen`)
3. Google Colab: I have **not** verified that it works; the free tier gives no display and no docker, so expect trouble.

```bash
pip install carla==0.9.15              # client matching the server version
python experiments/e13_carla_plant.py --host localhost --port 2000 --out outputs/e13_carla.json
```
It prints the calibration fits, a table of CARLA vs closed-form points of no return, and the mean absolute error and bias
of each model. Expect the assumed parameters to be off (CARLA's brake torque model differs); the fitted model should be close.

## How to read the result
- Small error with fitted parameters: the plant *shape* (hold speed, ramp, constant deceleration) is adequate; report the
  assumed-vs-fitted gap as the calibration the emulator needs.
- Large error even with fitted parameters: the plant is too simple (load transfer, ABS, tyre slip); say so and bound the
  claims accordingly.
