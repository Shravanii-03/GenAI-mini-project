"""
E13: does the emulator's braking plant agree with a physics engine? (CARLA)

NOT YET RUN: written against the CARLA 0.9.15 Python API and never executed against a live server (no GPU here).
The pure analysis parts (fit, bisection, summary) are unit-tested in tests/test_sdv_carla_analysis.py.

What it does
  1. Calibration: brake the ego vehicle from v0 with no obstacle, record speed, fit (deceleration, ramp) with the
     same shape the emulator uses.
  2. For each scenario (speed, obstacle gap) find CARLA's point of no return: the largest brake latency, counted
     from the moment the obstacle becomes a threat, at which the ego still stops short of the obstacle.
  3. Compare with the closed-form point of no return from sdv/plant using (a) the assumed parameters of
     config.yaml and (b) the parameters fitted from CARLA.

It validates the plant (latency -> collision), not the CAN emulation or the attacks.

    python experiments/e13_carla_plant.py --host localhost --port 2000 --out outputs/e13_carla.json
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.carla_check.analysis import bisect_ponr, closed_form_ponr_ms, fit_braking, summarise
from sdv.plant.longitudinal import decel_for_road, ramp_seconds

SCENARIOS = [(40, 14.0), (50, 20.0), (60, 24.0), (60, 30.0), (70, 32.0), (80, 45.0)]   # (km/h, gap in m)
DT = 0.005


class Trial:
    def __init__(self, carla, world, ego_bp, obstacle_bp, tire_friction=0.8):
        self.carla, self.world, self.ego_bp, self.obstacle_bp = carla, world, ego_bp, obstacle_bp
        self.tire_friction = tire_friction      # CARLA's default (about 3.5) allows braking no road car can reach
        self.dt_seen = []                       # simulated seconds per tick, as reported by CARLA itself

    def _spawn_points(self, gap):
        spawns = self.world.get_map().get_spawn_points()
        for tf in spawns:
            wp = self.world.get_map().get_waypoint(tf.location)
            ahead = wp.next(gap + 12.0)
            if ahead and abs(((ahead[0].transform.rotation.yaw - tf.rotation.yaw + 180) % 360) - 180) < 2.0:
                return tf, ahead[0].transform
        raise RuntimeError("no straight stretch long enough for this gap; try another town")

    def run(self, v0_kmh, gap_m, latency_ms, obstacle=True, max_s=20.0):
        """Returns (collided, speed trace after brake onset as (t, v))."""
        carla, world = self.carla, self.world
        ego_tf, obs_tf = self._spawn_points(gap_m if obstacle else 300.0)
        actors = []
        try:
            ego = world.spawn_actor(self.ego_bp, ego_tf)
            actors.append(ego)
            if self.tire_friction is not None:
                control = ego.get_physics_control()
                for wheel in control.wheels:
                    wheel.tire_friction = self.tire_friction
                ego.apply_physics_control(control)
            if obstacle:
                obs = world.spawn_actor(self.obstacle_bp, obs_tf)
                actors.append(obs)
                # put the obstacle's rear bumper gap_m ahead of the ego's front bumper
                forward = ego_tf.get_forward_vector()
                centre = gap_m + ego.bounding_box.extent.x + obs.bounding_box.extent.x
                obs.set_transform(carla.Transform(ego_tf.location + forward * centre, ego_tf.rotation))
                obs.apply_control(carla.VehicleControl(hand_brake=True))
            sensor = world.spawn_actor(world.get_blueprint_library().find("sensor.other.collision"),
                                       carla.Transform(), attach_to=ego)
            actors.append(sensor)
            hits = []
            sensor.listen(lambda event: hits.append(event))

            v0 = v0_kmh / 3.6
            forward = ego_tf.get_forward_vector()
            ego.set_target_velocity(carla.Vector3D(forward.x * v0, forward.y * v0, 0.0))
            for _ in range(20):                         # let the physics settle without letting the speed drift
                ego.set_target_velocity(carla.Vector3D(forward.x * v0, forward.y * v0, 0.0))
                world.tick()
            hits.clear()

            clock = lambda: world.get_snapshot().timestamp.elapsed_seconds
            start = clock()
            t, trace, braking = 0.0, [], False
            t_brake = latency_ms / 1000.0
            while t < max_s:
                if not braking and t >= t_brake:
                    ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
                    braking = True
                    onset = t
                elif not braking:
                    ego.set_target_velocity(carla.Vector3D(forward.x * v0, forward.y * v0, 0.0))
                world.tick()
                t = clock() - start             # CARLA's own simulated time, not an assumed step
                self.dt_seen.append(world.get_snapshot().timestamp.delta_seconds)
                vel = ego.get_velocity()
                speed = math.sqrt(vel.x ** 2 + vel.y ** 2)
                if braking:
                    trace.append((t - onset, speed))
                if hits and obstacle:
                    return True, trace
                if braking and speed < 0.05:
                    break
            return False, trace
        finally:
            for actor in reversed(actors):
                try:
                    if hasattr(actor, "stop"):
                        actor.stop()
                    actor.destroy()
                except RuntimeError:
                    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--town", default="Town04")
    ap.add_argument("--out", default="outputs/e13_carla.json")
    ap.add_argument("--tire-friction", type=float, default=0.8,
                    help="wheel friction (the emulator assumes 0.8 on dry road); use 0 to keep CARLA's default")
    ap.add_argument("--max-latency-ms", type=float, default=2500.0, help="upper limit of the point-of-no-return search")
    args = ap.parse_args()
    try:
        import carla
    except ImportError:
        print("The carla Python package is not installed (see docs/CARLA.md).")
        return 1

    client = carla.Client(args.host, args.port)
    client.set_timeout(180.0)               # software rendering can take minutes to load a map
    import time
    for attempt in range(20):               # wait for a server that is still starting up
        try:
            current = client.get_world().get_map().name
            print(f"connected to the server (current map: {current})", flush=True)
            break
        except RuntimeError as error:
            print(f"waiting for the server ({attempt + 1}/20): {str(error)[:80]}", flush=True)
            time.sleep(15)
    else:
        print("could not reach the server; check that it is running (see docs/CARLA.md)")
        return 1
    world = client.get_world() if current.endswith(args.town) else client.load_world(args.town)
    settings = world.get_settings()
    settings.synchronous_mode, settings.fixed_delta_seconds = True, DT
    world.apply_settings(settings)
    library = world.get_blueprint_library()
    trial = Trial(carla, world, library.find("vehicle.tesla.model3"), library.find("vehicle.audi.a2"),
                  tire_friction=args.tire_friction or None)
    try:
        assumed = (decel_for_road("dry"), ramp_seconds())
        rows = []
        print("calibration (no obstacle):")
        fits = {}
        for v in sorted({s[0] for s in SCENARIOS}):
            _, trace = trial.run(v, 300.0, 0.0, obstacle=False)
            t, sp = np.array(trace).T
            sp = np.concatenate([[v / 3.6], sp])
            t = np.concatenate([[0.0], t])
            fits[v] = fit_braking(t, sp, ramp_grid=np.linspace(0.0, 1.0, 101))
            print(f"  {v} km/h: decel {fits[v]['decel']:.2f} m/s^2, ramp {fits[v]['ramp_s'] * 1000:.0f} ms, "
                  f"rmse {fits[v]['rmse']:.2f} m/s   (assumed {assumed[0]:.2f} m/s^2, {assumed[1] * 1000:.0f} ms)")
            if fits[v]["decel"] > 12.0:
                print(f"    WARNING: {fits[v]['decel']:.1f} m/s^2 is above any road-tyre limit; the setup is not realistic")
            if fits[v]["ramp_s"] >= 0.99:
                print("    WARNING: the fitted ramp hit the edge of the search range")
        print(f"simulated time per tick seen: min {min(trial.dt_seen):.4f} s, max {max(trial.dt_seen):.4f} s "
              f"(script assumed {DT} s)")
        print("\nscenario            CARLA PONR   assumed model   fitted model")
        for v, gap in SCENARIOS:
            collides = lambda ms, v=v, gap=gap: trial.run(v, gap, ms)[0]
            ponr = bisect_ponr(collides, 0.0, args.max_latency_ms, tol_ms=5.0)
            v_ms = v / 3.6
            row = {"v_kmh": v, "gap_m": gap, "carla_ms": ponr,
                   "assumed_ms": closed_form_ponr_ms(v_ms, gap, *assumed),
                   "fitted_ms": closed_form_ponr_ms(v_ms, gap, fits[v]["decel"], fits[v]["ramp_s"])}
            rows.append(row)
            row["capped"] = ponr is not None and ponr >= args.max_latency_ms - 1e-9
            shown = ("collides at 0" if ponr is None else f"{ponr:7.0f} ms" + (" (CAPPED: never collided)" if row["capped"] else ""))
            print(f"{v:>3} km/h, {gap:>4.0f} m   {shown:>12}   {row['assumed_ms']:>10.0f} ms   {row['fitted_ms']:>9.0f} ms")
        summary = summarise(rows)
        print("\n" + json.dumps(summary, indent=2))
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "fits": fits, "summary": summary, "tire_friction": args.tire_friction,
                       "dt_seen": [min(trial.dt_seen), max(trial.dt_seen)],
                       "assumed": {"decel": assumed[0], "ramp_s": assumed[1]}}, f, indent=2, default=float)
    finally:
        settings.synchronous_mode = False
        world.apply_settings(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
