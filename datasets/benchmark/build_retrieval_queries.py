"""
Builds datasets/benchmark/retrieval_queries.json: two labelled queries per knowledge-base entry.

  keyword     reuses the entry's own vocabulary (what a lexical retriever is built for)
  paraphrase  describes the same thing without the entry's key terms (needs semantics)

    python datasets/benchmark/build_retrieval_queries.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

VSS = {
    "Vehicle.ADAS.ABS.IsActive": ("anti-lock braking system active", "is the wheel-lock prevention feature switched on"),
    "Vehicle.ADAS.ABS.IsEngaged": ("ABS engaged controlling brake pressure", "antilock is intervening right now to modulate the brakes"),
    "Vehicle.ADAS.ActiveAutonomyLevel": ("current SAE autonomy level", "how much self-driving capability is the car currently using"),
    "Vehicle.ADAS.CruiseControl.IsActive": ("cruise control active", "is the speed-holding assistant turned on"),
    "Vehicle.ADAS.CruiseControl.SpeedSet": ("cruise control set speed", "target velocity the driver selected for automatic speed holding"),
    "Vehicle.ADAS.EBA.IsActive": ("emergency brake assist active", "panic braking support is enabled"),
    "Vehicle.ADAS.EBA.IsEngaged": ("emergency brake assist engaged", "the panic-brake helper is currently applying extra braking force"),
    "Vehicle.ADAS.ESC.IsActive": ("electronic stability control active", "skid prevention system is switched on"),
    "Vehicle.ADAS.LaneDepartureDetection.IsWarning": ("lane departure warning active", "alert because the car is drifting out of its lane"),
    "Vehicle.ADAS.ObstacleDetection.IsWarning": ("obstacle detection warning", "alert that something is in the way ahead"),
    "Vehicle.Body.Lights.Brake.IsActive": ("brake lights active", "rear red lamps lit when slowing"),
    "Vehicle.Chassis.Brake.IsDriverEmergencyBrakingDetected": ("driver emergency braking detected", "the person at the wheel stamped hard on the brake"),
    "Vehicle.Chassis.Brake.PedalPosition": ("brake pedal position percentage", "how far the brake pedal is pushed down"),
    "Vehicle.Chassis.SteeringWheel.Angle": ("steering wheel angle", "how much the driver has turned the wheel"),
    "Vehicle.CurrentLocation.Latitude": ("current vehicle latitude", "north-south GPS coordinate of the car"),
    "Vehicle.CurrentLocation.Longitude": ("current vehicle longitude", "east-west GPS coordinate of the car"),
    "Vehicle.Driver.AttentiveProbability": ("probability that the driver is attentive", "is the driver paying attention to the road"),
    "Vehicle.OBD.Speed": ("vehicle speed reported by OBD", "velocity read from the diagnostic port"),
    "Vehicle.Speed": ("vehicle speed", "how fast the car is travelling"),
    "Vehicle.Speed.Target": ("target vehicle speed commanded", "the velocity the controller is asking the car to reach"),
    "Vehicle.Powertrain.Transmission.CurrentGear": ("current gear", "which transmission ratio is selected"),
    "Vehicle.Powertrain.CombustionEngine.ECT": ("engine coolant temperature", "how hot the engine's cooling liquid is"),
    "Vehicle.Cabin.HVAC.IsAirConditioningActive": ("air conditioning active", "is the cabin cooling system running"),
    "Vehicle.ADAS.PedestrianDetection.IsDetected": ("pedestrian detected in vehicle path", "a person walking ahead of the car has been spotted"),
    "Vehicle.ADAS.PedestrianDetection.CameraConfidence": ("camera-based pedestrian detection confidence", "how sure the image sensor is that it sees a walker"),
    "Vehicle.ADAS.PedestrianDetection.LidarConfidence": ("LIDAR pedestrian detection confidence", "how certain the laser scanner is about a person ahead"),
}
CAN = {
    "0x1A0": ("emergency brake command to the brake actuator", "message telling the wheels to stop the car urgently"),
    "0x1A3": ("brake pressure feedback from actuator", "reading of hydraulic force reported back after braking"),
    "0x200": ("vehicle speed broadcast from wheel speed sensors", "periodic velocity message derived from the wheels"),
    "0x210": ("steering angle command", "request that points the front wheels in a given direction"),
    "0x300": ("fused perception data from camera and LiDAR", "combined view of the surroundings from several sensors"),
    "0x310": ("LiDAR point cloud summary data", "condensed laser scanner measurements"),
    "0x320": ("camera object detection result", "what the image sensor recognised in front of the car"),
    "0x400": ("infotainment system control messages", "commands for the media and entertainment head unit"),
    "0x500": ("over-the-air software update control", "wireless firmware upgrade management messages"),
    "0x600": ("zone ECU liveness heartbeat", "periodic I'm-alive signal from a regional controller"),
    "0x700": ("traction control commands", "messages limiting wheel spin on slippery surfaces"),
}
ATTACK = {
    "CAN Bus Spoofing": ("forged CAN messages injected to override brake commands", "attacker sends fake frames pretending to be a legitimate controller"),
    "Sensor Data Injection": ("sensor data injection", "feeding false readings into the perception inputs"),
    "ECU Timing Attack (Delay Injection)": ("delay injection timing attack on an ECU", "making a controller respond later than its deadline by stalling messages"),
    "OTA Firmware Tampering": ("OTA firmware tampering", "malicious modification of software delivered wirelessly to the vehicle"),
    "Infotainment to CAN Bridge Attack": ("infotainment to CAN bridge attack", "pivoting from the entertainment system into the safety network"),
    "Replay Attack on Safety Messages": ("replay attack on safety messages", "recording valid frames and sending them again later"),
    "DoS on CAN Bus": ("denial of service flooding the CAN bus", "saturating the network so legitimate frames cannot get through"),
    "GPS Spoofing for Navigation Hijack": ("GPS spoofing navigation hijack", "fake satellite positions that steer the route"),
}
RULE = {
    "ISO26262-6-8.4.5": ("emergency brake response time limit", "maximum delay between seeing an obstacle and full braking"),
    "ISO26262-6-8.4.6": ("steering override response time", "how quickly an urgent steering takeover must complete"),
    "ISO26262-6-8.4.7": ("driver alert response", "how soon the occupant must be notified of danger"),
    "ISO26262-3-7.4.2": ("pedestrian detection to brake latency", "time allowed from spotting a walker to starting to stop"),
    "ISO26262-3-7.4.3": ("lane departure warning timing", "time limit for alerting when the vehicle strays from its lane"),
    "ISO26262-3-7.4.4": ("adaptive cruise control response time", "limit for reacting to a slower vehicle ahead while following"),
    "ISO26262-4-6.4.1": ("safety mechanism activation time", "how fast a protective function must kick in after a fault"),
    "ISO26262-6-9.4.3": ("ECU watchdog timeout", "how long a controller may stay silent before being reset"),
}


def build():
    from sdv.rag.kb import load_corpora
    corpora = load_corpora()
    attack_ids = {d.title: d.id for d in corpora["attack"]}
    queries = []
    for kind, table in (("vss", VSS), ("can", CAN), ("attack", ATTACK), ("rule", RULE)):
        for key, (keyword, paraphrase) in table.items():
            gold = attack_ids[key] if kind == "attack" else key
            for style, text in (("keyword", keyword), ("paraphrase", paraphrase)):
                queries.append({"id": f"Q{len(queries) + 1:03d}", "kind": kind, "style": style,
                                "query": text, "gold": [gold]})
    return queries


if __name__ == "__main__":
    qs = build()
    out = Path(__file__).with_name("retrieval_queries.json")
    out.write_text(json.dumps(qs, indent=1), encoding="utf-8")
    ids = {d.id for docs in __import__("sdv.rag.kb", fromlist=["x"]).load_corpora().values() for d in docs}
    assert all(g in ids for q in qs for g in q["gold"]), "gold id missing from KB"
    print(f"wrote {len(qs)} queries to {out}")
