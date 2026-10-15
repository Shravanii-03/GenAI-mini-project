"""Typed data models shared across the SDV timing/security pipeline."""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class CanFrame(BaseModel):
    can_id: int
    src: str
    dlc: int = Field(default=8, ge=0, le=8)
    data: Dict = Field(default_factory=dict)
    attack: bool = False
    t_enqueued_us: Optional[int] = None
    t_tx_start_us: Optional[int] = None
    t_rx_us: Optional[int] = None


class Scenario(BaseModel):
    """Obstacle becomes detectable d0_m metres ahead of an ego vehicle at v0."""
    v0_kmh: float = Field(default=60.0, gt=0)
    d0_m: float = Field(default=30.0, gt=0)
    road: Literal["dry", "wet", "icy"] = "dry"
    cpu_load: float = Field(default=0.5, ge=0.0, le=0.95)


class PlantOutcome(BaseModel):
    collision: bool
    impact_speed_ms: float
    stop_distance_m: float
    min_gap_m: float


class RunResult(BaseModel):
    seed: int
    scenario: Scenario
    braked: bool
    e2e_latency_ms: Optional[float]          # None if the vehicle never braked
    timeline_ms: Dict[str, float]            # event times relative to obstacle appearance
    stage_ms: Dict[str, float]               # per-stage durations
    outcome: PlantOutcome
    latest_safe_latency_ms: float            # point of no return; <0 means unavoidable
    margin_ms: Optional[float]               # latest_safe - latency; <0 means hazard
    attacks: List[Dict] = Field(default_factory=list)            # attack name + parameters
    attack_windows_ms: List[Dict] = Field(default_factory=list)  # relative to obstacle appearance
