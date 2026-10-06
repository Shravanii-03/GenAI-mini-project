"""Structured timing specification produced from a natural-language requirement."""
from typing import List, Optional

from pydantic import BaseModel, Field

COMPONENTS = (
    "braking_system", "steering_ecu", "alert_module", "lane_departure_system",
    "acc_system", "safety_monitor", "ecu_watchdog", "other",
)

FIELDS_HELP = """\
{
  "deadline_ms": <number in milliseconds, or null>,
  "unresolved": <true if timing is requested only vaguely, e.g. "promptly"; else false>,
  "component": one of %s,
  "trigger": "<snake_case event that starts the clock, e.g. obstacle_detected>",
  "response": "<snake_case event that must follow, e.g. brake_applied>",
  "vss_signals": [<VSS signal paths the requirement names>],
  "can_ids": [<CAN IDs such as "0x1A0" the requirement names>],
  "formula": "G(trigger -> F[0,<deadline_ms> ms] response)" or null
}""" % (list(COMPONENTS),)


class TimingSpec(BaseModel):
    deadline_ms: Optional[float] = None
    unresolved: bool = False
    component: str = "other"
    trigger: str = ""
    response: str = ""
    vss_signals: List[str] = Field(default_factory=list)
    can_ids: List[str] = Field(default_factory=list)
    formula: Optional[str] = None
