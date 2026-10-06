"""
Minimal discrete-event simulation engine.

Time is an integer number of microseconds, so there is no floating-point drift
and runs are exactly reproducible for a given seed.
"""
import heapq
import itertools


class Simulator:
    def __init__(self):
        self.now = 0
        self._queue = []
        self._seq = itertools.count()
        self._stopped = False

    def schedule(self, delay_us, callback, *args):
        """Run callback(*args) delay_us microseconds from now."""
        if delay_us < 0:
            raise ValueError("delay must be non-negative")
        self.schedule_at(self.now + int(delay_us), callback, *args)

    def schedule_at(self, time_us, callback, *args):
        if time_us < self.now:
            raise ValueError("cannot schedule in the past")
        heapq.heappush(self._queue, (int(time_us), next(self._seq), callback, args))

    def run(self, until_us=None):
        """Process events in time order (ties in scheduling order)."""
        while self._queue and not self._stopped:
            time_us, _, callback, args = self._queue[0]
            if until_us is not None and time_us > until_us:
                break
            heapq.heappop(self._queue)
            self.now = time_us
            callback(*args)
        if until_us is not None and not self._stopped:
            self.now = max(self.now, until_us)

    def stop(self):
        """Stop processing events after the current one."""
        self._stopped = True

    def pending(self):
        return len(self._queue)
