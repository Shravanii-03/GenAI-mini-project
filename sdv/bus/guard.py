"""
Gateway guard between an untrusted segment (OBD-II port, infotainment bridge) and the safety bus.

The untrusted segment has no business sending safety-relevant identifiers, and the few it does send
(infotainment and diagnostics messages) have a catalogued rate. The guard forwards a frame from that segment
only if its identifier is whitelisted and a per-identifier token bucket has a token (nominal rate x slack).
Everything else is dropped before arbitration, so a flood from that segment never reaches the safety bus.

What it does NOT cover (and the emulator makes explicit): a compromised node that sits on the safety bus
itself, and a compromised ECU or gateway that forges frames of identifiers it is allowed to send.
"""
from sdv.schemas import CanFrame

UNTRUSTED_SRC = "attacker"          # frames injected from the untrusted segment
SAFETY_BUS_SRC = "safety_node"      # frames injected by a node that is already on the safety bus

# identifier -> nominal cycle (ms) of the messages the untrusted segment may send (from the message catalog)
ALLOWED_FROM_UNTRUSTED = {0x400: 100.0, 0x600: 100.0}


class GatewayGuard:
    def __init__(self, allowed=None, slack: float = 2.0, burst: int = 2):
        self.allowed = dict(ALLOWED_FROM_UNTRUSTED if allowed is None else allowed)
        self.slack, self.burst = slack, burst
        self._tokens = {i: float(burst) for i in self.allowed}
        self._last = {}
        self.blocked = 0

    def __call__(self, frame: CanFrame, now_us: int):
        if frame.src != UNTRUSTED_SRC:
            return frame, 0
        cycle_ms = self.allowed.get(frame.can_id)
        if cycle_ms is None:
            self.blocked += 1
            return None, 0
        rate_per_us = self.slack / (cycle_ms * 1000.0)
        last = self._last.get(frame.can_id, now_us)
        tokens = min(float(self.burst), self._tokens[frame.can_id] + (now_us - last) * rate_per_us)
        self._last[frame.can_id] = now_us
        if tokens < 1.0:
            self._tokens[frame.can_id] = tokens
            self.blocked += 1
            return None, 0
        self._tokens[frame.can_id] = tokens - 1.0
        return frame, 0
