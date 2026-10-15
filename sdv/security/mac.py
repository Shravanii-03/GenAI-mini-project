"""
A real (truncated) message authentication code for the emulated sensor and radar frames.

Design, in the style of AUTOSAR SecOC: every sender frame carries a freshness counter (the existing `seq`) and a truncated MAC over
(can id, counter, payload):

    tag = first `bits` bits of HMAC-SHA256(key, can_id || counter || distance_mm || speed_mm_s || obstacle)

The receiver recomputes the tag and also requires the counter to increase, so a replayed or reordered frame is rejected. A gateway
that changes the payload without the key leaves the old tag in place; it then passes only by chance, with probability 2**-bits per
frame (about 6e-8 at 24 bits). An attacker that HOLDS the key re-signs its forged frames and passes always.

Why HMAC-SHA256 and not AES-CMAC: it is in the Python standard library, so the emulator needs no extra dependency. SecOC allows
both. Real ECUs would use a hardware security module; the cost of the MAC is not modelled beyond the assumed verification time.
"""
import hashlib
import hmac
import struct


def encode_payload(distance_m, speed_ms, obstacle) -> bytes:
    """Quantise the signed fields the way a CAN payload would hold them (millimetres, mm/s, one flag byte)."""
    distance_mm = 0 if distance_m is None else int(round(distance_m * 1000))
    speed_mms = 0 if speed_ms is None else int(round(speed_ms * 1000))
    return struct.pack(">iiB", distance_mm, speed_mms, 1 if obstacle else 0)


class FrameMac:
    def __init__(self, key: bytes, bits: int = 24):
        if not 1 <= bits <= 64:
            raise ValueError("bits must be between 1 and 64")
        self._key, self.bits = key, bits

    @staticmethod
    def derive_key(seed) -> bytes:
        """A deterministic per-run key for simulation (a real key would be provisioned, never derived like this)."""
        return hashlib.sha256(f"sdv-simulation-key-{seed}".encode()).digest()

    def tag(self, can_id: int, counter: int, payload: bytes) -> int:
        message = struct.pack(">IQ", can_id, counter) + payload
        digest = hmac.new(self._key, message, hashlib.sha256).digest()
        return int.from_bytes(digest[:8], "big") >> (64 - self.bits)

    def verify(self, can_id: int, counter: int, payload: bytes, tag) -> bool:
        if tag is None:
            return False
        return hmac.compare_digest(self.tag(can_id, counter, payload).to_bytes(8, "big"), int(tag).to_bytes(8, "big"))
