"""
CAN bus emulator with arbitration and bit-accurate frame timing.

Classical CAN 2.0A (11-bit IDs). When the bus is idle the pending frame with the
lowest identifier wins arbitration; transmission is non-preemptive. Frame length
uses the worst-case bit-stuffing formula from the CAN response-time literature:

    bits = 8*dlc + 47 + floor((34 + 8*dlc - 1) / 4)

This is an emulation, not a physical bus: it is used so that delays emerge from
queueing, load and attacker traffic instead of being drawn from a range.
"""
import math

import config
from sdv.schemas import CanFrame
from sdv.sim.engine import Simulator


def frame_bits(dlc: int) -> int:
    return 8 * dlc + 47 + (34 + 8 * dlc - 1) // 4


class CanBus:
    def __init__(self, sim: Simulator, bitrate_bps: int = None):
        self.sim = sim
        self.bitrate = bitrate_bps or config.get("bus.bitrate_bps", 500000)
        self._pending = []          # (arrival_order, frame)
        self._order = 0
        self._busy = False
        self._arb_scheduled = False
        self._subscribers = []
        self.log = []               # every frame that completed transmission

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def tx_time_us(self, dlc: int) -> int:
        return math.ceil(frame_bits(dlc) * 1_000_000 / self.bitrate)

    def send(self, frame: CanFrame):
        frame.t_enqueued_us = self.sim.now
        self._pending.append((self._order, frame))
        self._order += 1
        # Frames queued in the same instant must compete in arbitration, so the
        # decision is deferred to the end of the current time step.
        if not self._busy and not self._arb_scheduled:
            self._arb_scheduled = True
            self.sim.schedule(0, self._arbitrate)

    def _arbitrate(self):
        self._arb_scheduled = False
        if self._busy or not self._pending:
            return
        winner = min(self._pending, key=lambda item: (item[1].can_id, item[0]))
        self._pending.remove(winner)
        frame = winner[1]
        self._busy = True
        frame.t_tx_start_us = self.sim.now
        self.sim.schedule(self.tx_time_us(frame.dlc), self._finish, frame)

    def _finish(self, frame: CanFrame):
        frame.t_rx_us = self.sim.now
        self.log.append(frame)
        self._busy = False
        for callback in self._subscribers:
            callback(frame)
        self._arbitrate()

    def utilisation(self, window_us: int) -> float:
        """Fraction of the last window_us the bus spent transmitting."""
        start = self.sim.now - window_us
        busy = sum(
            f.t_rx_us - max(f.t_tx_start_us, start)
            for f in self.log
            if f.t_rx_us is not None and f.t_rx_us > start
        )
        return busy / window_us if window_us else 0.0
