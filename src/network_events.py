from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import Callable
from typing import Any


class NetworkEventType(StrEnum):
    MESSAGE_SCHEDULED = "message_scheduled"
    MESSAGE_DELIVERED = "message_delivered"
    MESSAGE_LOST = "message_lost"
    MESSAGE_DROPPED = "message_dropped"
    MESSAGE_DUPLICATED = "message_duplicated"

    LINK_BLOCKED = "link_blocked"
    LINK_RESTORED = "link_restored"


@dataclass(frozen=True, slots=True)
class NetworkEvent:
    time: int
    event_type: NetworkEventType

    source_id: str
    target_id: str

    message_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


NetworkEventHandler = Callable[[NetworkEvent], None]
