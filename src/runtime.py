from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .messages import Message, MessageType
from .node import Node
from .scheduler import ScheduledEvent

if TYPE_CHECKING:
    from .engine import Engine


class NodeRuntime:
    def __init__(self, engine: Engine, node: Node) -> None:
        self._engine = engine
        self._node = node

    @property
    def node(self) -> Node:
        return self._node

    @property
    def node_id(self) -> str:
        return self._node.node_id

    @property
    def current_time(self) -> int:
        return self._node.local_time_at(self._engine.current_time)

    def get_neighbors(self) -> tuple[str, ...]:
        return self._engine.get_neighbors(self.node_id)

    def send(self, message: Message) -> bool:
        return self._engine.send(message)

    def send_message(
        self,
        *,
        message_type: MessageType,
        target_id: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
    ) -> bool:
        return self._engine.send_message(
            message_type=message_type,
            source_id=self.node_id,
            target_id=target_id,
            created_at=self.current_time,
            payload=payload,
            correlation_id=correlation_id,
            attempt=attempt,
            metadata=metadata,
            ttl_hops=ttl_hops,
        )

    def multicast(
        self,
        *,
        message_type: MessageType,
        target_ids: Iterable[str],
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
    ) -> dict[str, bool]:
        return self._engine.multicast(
            message_type=message_type,
            source_id=self.node_id,
            target_ids=target_ids,
            created_at=self.current_time,
            payload=payload,
            correlation_id=correlation_id,
            attempt=attempt,
            metadata=metadata,
            ttl_hops=ttl_hops,
        )

    def broadcast(
        self,
        *,
        message_type: MessageType,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
        exclude_ids: Iterable[str] | None = None,
    ) -> dict[str, bool]:
        return self._engine.broadcast(
            message_type=message_type,
            source_id=self.node_id,
            created_at=self.current_time,
            payload=payload,
            correlation_id=correlation_id,
            attempt=attempt,
            metadata=metadata,
            ttl_hops=ttl_hops,
            exclude_ids=exclude_ids,
        )

    def gossip(
        self,
        *,
        message_type: MessageType,
        fanout: int,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
        candidate_ids: Iterable[str] | None = None,
        exclude_ids: Iterable[str] | None = None,
    ) -> dict[str, bool]:
        return self._engine.gossip(
            message_type=message_type,
            source_id=self.node_id,
            created_at=self.current_time,
            fanout=fanout,
            payload=payload,
            correlation_id=correlation_id,
            attempt=attempt,
            metadata=metadata,
            ttl_hops=ttl_hops,
            candidate_ids=candidate_ids,
            exclude_ids=exclude_ids,
        )

    def reply(
        self,
        request: Message,
        *,
        payload: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
    ) -> bool:
        response = request.create_response(
            created_at=self.current_time,
            payload=payload,
        )

        if ttl_hops is None:
            return self.send(response)

        return self.send(
            Message(
                message_id=response.message_id,
                message_type=response.message_type,
                source_id=response.source_id,
                target_id=response.target_id,
                created_at=response.created_at,
                payload=response.payload,
                correlation_id=response.correlation_id,
                attempt=response.attempt,
                ttl_hops=ttl_hops,
                hop_count=response.hop_count,
                metadata=response.metadata,
            )
        )

    def schedule_timer(
        self,
        delay: int,
        timer_name: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> ScheduledEvent:
        target_local_time = self.current_time + delay
        return self.schedule_timer_at(
            target_local_time,
            timer_name,
            details=details,
        )

    def schedule_timer_at(
        self,
        execute_at: int,
        timer_name: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> ScheduledEvent:
        simulation_time = self._node.clock.simulation_time_at(execute_at)
        return self._engine.schedule_timer_at(
            self.node_id,
            simulation_time,
            timer_name,
            details=details,
        )

    def cancel_timer(self, timer: ScheduledEvent) -> None:
        self._engine.scheduler.cancel(timer)
