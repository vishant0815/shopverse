"""A small circuit breaker per service.

When a service stops answering, every request to it would otherwise wait out the full
timeout, tie up a gateway connection, and pile more load onto a service that is already
struggling. After a run of failures the breaker "opens": requests to that service get an
immediate 503 for a short cool-down. Then one trial request is let through ("half open");
if it works the breaker closes, if not it opens again.

Only failures to get any answer count (refused connection, timeout). A 500 from the
service is still an answer and is passed on as it is.

State is per gateway process. That's deliberate: each worker learns about a dead
service within a few requests, and there's no shared state to go wrong.
"""

import time
from dataclasses import dataclass, field


@dataclass
class Breaker:
    threshold: int
    reset_seconds: float
    clock: callable = time.monotonic
    failures: int = 0
    opened_at: float | None = None
    trial_running: bool = field(default=False)

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock() - self.opened_at >= self.reset_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self.trial_running:
            self.trial_running = True
            return True
        return False

    def retry_after(self) -> int:
        if self.opened_at is None:
            return 0
        return max(1, round(self.reset_seconds - (self.clock() - self.opened_at)))

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.trial_running = False

    def failure(self) -> None:
        self.trial_running = False
        self.failures += 1
        if self.opened_at is not None or self.failures >= self.threshold:
            self.opened_at = self.clock()


class Breakers:
    def __init__(self, threshold: int, reset_seconds: float, clock=time.monotonic):
        self._make = lambda: Breaker(threshold, reset_seconds, clock)
        self._by_service: dict[str, Breaker] = {}

    def __getitem__(self, service: str) -> Breaker:
        if service not in self._by_service:
            self._by_service[service] = self._make()
        return self._by_service[service]

    def states(self) -> dict[str, str]:
        return {name: b.state for name, b in self._by_service.items()}
