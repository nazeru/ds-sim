from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .messages import Message


class SimulationEventType(StrEnum):
    NODE_MESSAGE_ARRIVED = "node_message_arrived"
    NODE_MESSAGE_PROCESSED = "node_message_processed"
    NODE_TIMER_FIRED = "node_timer_fired"
    NODE_FAILED = "node_failed"
    NODE_RECOVERED = "node_recovered"
    NODE_ISOLATED = "node_isolated"
    NODE_STOPPED = "node_stopped"


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    time: int
    event_type: SimulationEventType
    node_id: str

    message: Message | None = None
    timer_name: str | None = None
    local_time: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
