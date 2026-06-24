from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class MessageType(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    HEARTBEAT = "heartbeat"
    ACKNOWLEDGEMENT = "acknowledgement"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    message_type: MessageType

    source_id: str
    target_id: str

    created_at: int
    payload: dict[str, Any] = field(default_factory=dict)

    correlation_id: str | None = None
    attempt: int = 1
    ttl_hops: int | None = None
    hop_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        message_type: MessageType,
        source_id: str,
        target_id: str,
        created_at: int,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
    ) -> Message:
        if attempt < 1:
            raise ValueError("attempt должен быть больше или равен 1")

        if ttl_hops is not None and ttl_hops < 0:
            raise ValueError("ttl_hops не может быть отрицательным")

        return cls(
            message_id=str(uuid4()),
            message_type=message_type,
            source_id=source_id,
            target_id=target_id,
            created_at=created_at,
            payload=deepcopy(payload) if payload is not None else {},
            correlation_id=correlation_id,
            attempt=attempt,
            ttl_hops=ttl_hops,
            metadata=deepcopy(metadata) if metadata is not None else {},
        )

    def create_response(
        self,
        *,
        created_at: int,
        payload: dict[str, Any] | None = None,
    ) -> Message:
        return Message.create(
            message_type=MessageType.RESPONSE,
            source_id=self.target_id,
            target_id=self.source_id,
            created_at=created_at,
            payload=payload,
            correlation_id=self.message_id,
        )

    def clone(self) -> Message:
        return Message(
            message_id=self.message_id,
            message_type=self.message_type,
            source_id=self.source_id,
            target_id=self.target_id,
            created_at=self.created_at,
            payload=deepcopy(self.payload),
            correlation_id=self.correlation_id,
            attempt=self.attempt,
            ttl_hops=self.ttl_hops,
            hop_count=self.hop_count,
            metadata=deepcopy(self.metadata),
        )

    def can_traverse_next_hop(self) -> bool:
        return self.ttl_hops is None or self.ttl_hops > 0

    def prepare_for_delivery(self) -> Message:
        ttl_hops = None if self.ttl_hops is None else self.ttl_hops - 1

        return Message(
            message_id=self.message_id,
            message_type=self.message_type,
            source_id=self.source_id,
            target_id=self.target_id,
            created_at=self.created_at,
            payload=deepcopy(self.payload),
            correlation_id=self.correlation_id,
            attempt=self.attempt,
            ttl_hops=ttl_hops,
            hop_count=self.hop_count + 1,
            metadata=deepcopy(self.metadata),
        )
