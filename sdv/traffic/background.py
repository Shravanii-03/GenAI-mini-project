"""
Background CAN traffic taken from the knowledge-base message catalog.

Every periodic message in Knowledge_base/can_messages.json is replayed with its
catalogued cycle time and a random phase. Payloads larger than 8 bytes (CAN-FD
messages in the catalog) are capped at 8 bytes because the emulator is classical
CAN; this is a documented simplification. IDs used by the brake chain itself are
excluded so the chain controls its own traffic.
"""
import json

import config
from sdv.schemas import CanFrame

_KB_FILE = "can_messages.json"


def load_periodic_messages(exclude_ids=()):
    path = config.project_root() / config.get("rag.knowledge_base_path", "Knowledge_base/") / _KB_FILE
    with open(path, encoding="utf-8") as f:
        catalog = json.load(f)["messages"]
    excluded = {int(i) if not isinstance(i, str) else int(i, 16) for i in exclude_ids}
    out = []
    for m in catalog:
        cycle = m.get("cycle_time_ms")
        can_id = int(m["id"], 16)
        if not cycle or can_id in excluded:
            continue
        out.append({
            "id": can_id,
            "name": m["name"],
            "cycle_us": int(cycle * 1000),
            "dlc": min(int(m.get("dlc", 8)), 8),
        })
    return out


class BackgroundTraffic:
    """Schedules periodic frames until the simulation stops."""

    def __init__(self, sim, bus, rng, exclude_ids=(), jitter=0.01):
        self.sim, self.bus, self.rng, self.jitter = sim, bus, rng, jitter
        self.messages = load_periodic_messages(exclude_ids)

    def start(self):
        for msg in self.messages:
            phase = int(self.rng.uniform(0, msg["cycle_us"]))
            self.sim.schedule(phase, self._emit, msg)

    def _emit(self, msg):
        self.bus.send(CanFrame(can_id=msg["id"], src=msg["name"], dlc=msg["dlc"], data={}))
        j = 1.0 + self.rng.uniform(-self.jitter, self.jitter)
        self.sim.schedule(int(msg["cycle_us"] * j), self._emit, msg)
