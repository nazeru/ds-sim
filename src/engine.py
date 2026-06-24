from __future__ import annotations

import random
from collections.abc import Callable
from collections.abc import Iterable
from typing import TYPE_CHECKING
from typing import Any

from .channel import ChannelConfig
from .events import SimulationEvent, SimulationEventType
from .messages import Message, MessageType
from .network import (
    LatencyProvider,
    Network,
)
from .network_events import NetworkEventHandler
from .node import Node
from .scheduler import ScheduledEvent, Scheduler
from .topology import Topology
from .runtime import NodeRuntime

if TYPE_CHECKING:
    from .protocol import NodeProtocol


SimulationEventHandler = Callable[[SimulationEvent], None]


class Engine:
    def __init__(
        self,
        *,
        scheduler: Scheduler | None = None,
        channel_config: ChannelConfig | None = None,
        seed: int = 0,
        latency_provider: LatencyProvider | None = None,
        network_event_handler: NetworkEventHandler | None = None,
        event_handler: SimulationEventHandler | None = None,
    ) -> None:
        self._scheduler = scheduler or Scheduler()
        self._event_handler = event_handler
        self._random = random.Random(seed)

        self._network = Network(
            self._scheduler,
            channel_config=channel_config,
            seed=seed,
            latency_provider=latency_provider,
            event_handler=network_event_handler,
            delivery_handler=self._on_message_delivered,
        )

        self._nodes: dict[str, Node] = {}
        self._protocols: dict[str, NodeProtocol] = {}

    @property
    def scheduler(self) -> Scheduler:
        return self._scheduler

    @property
    def network(self) -> Network:
        return self._network

    @property
    def current_time(self) -> int:
        return self._scheduler.current_time

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(self._nodes)

    @property
    def active_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node_id
            for node_id, node in self._nodes.items()
            if node.is_available
        )

    @property
    def topology(self) -> Topology | None:
        return self._network.topology

    def get_node(self, node_id: str) -> Node:
        return self._get_node(node_id)

    def get_neighbors(self, node_id: str) -> tuple[str, ...]:
        return self._network.get_neighbors(node_id)

    def set_topology(self, topology: Topology | None) -> None:
        self._network.set_topology(topology)

    def get_protocol(self, node_id: str) -> NodeProtocol:
        try:
            return self._protocols[node_id]
        except KeyError as error:
            raise KeyError(
                f"Протокол для узла {node_id!r} не зарегистрирован"
            ) from error

    def register_node(
        self,
        node: Node,
        *,
        protocol: NodeProtocol,
    ) -> None:
        self._network.register_node(node)
        self._nodes[node.node_id] = node
        self._protocols[node.node_id] = protocol
        protocol.bind(NodeRuntime(self, node), node)

    def unregister_node(self, node_id: str) -> None:
        self._network.unregister_node(node_id)
        self._nodes.pop(node_id, None)
        self._protocols.pop(node_id, None)

    def fail_node(self, node_id: str) -> None:
        node = self._get_node(node_id)
        previous_status = node.status
        node.fail(self.current_time)

        if node.status != previous_status:
            self._emit(
                SimulationEventType.NODE_FAILED,
                node_id=node.node_id,
                local_time=node.local_time_at(self.current_time),
            )

    def recover_node(self, node_id: str) -> bool:
        node = self._get_node(node_id)
        recovered = node.recover(self.current_time)

        if recovered:
            self._emit(
                SimulationEventType.NODE_RECOVERED,
                node_id=node.node_id,
                local_time=node.local_time_at(self.current_time),
            )

        return recovered

    def isolate_node(self, node_id: str) -> None:
        node = self._get_node(node_id)
        previous_status = node.status
        node.isolate()

        if node.status != previous_status:
            self._emit(
                SimulationEventType.NODE_ISOLATED,
                node_id=node.node_id,
                local_time=node.local_time_at(self.current_time),
            )

    def stop_node(self, node_id: str) -> None:
        node = self._get_node(node_id)
        previous_status = node.status
        node.stop()

        if node.status != previous_status:
            self._emit(
                SimulationEventType.NODE_STOPPED,
                node_id=node.node_id,
                local_time=node.local_time_at(self.current_time),
            )

    def send(self, message: Message) -> bool:
        return self._network.send(message)

    def send_message(
        self,
        *,
        message_type: MessageType,
        source_id: str,
        target_id: str,
        created_at: int | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
    ) -> bool:
        return self.send(
            Message.create(
                message_type=message_type,
                source_id=source_id,
                target_id=target_id,
                created_at=self.current_time if created_at is None else created_at,
                payload=payload,
                correlation_id=correlation_id,
                attempt=attempt,
                metadata=metadata,
                ttl_hops=ttl_hops,
            )
        )

    def multicast(
        self,
        *,
        message_type: MessageType,
        source_id: str,
        target_ids: Iterable[str],
        created_at: int | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
    ) -> dict[str, bool]:
        unique_targets = self._normalize_target_ids(
            source_id=source_id,
            target_ids=target_ids,
        )

        return {
            target_id: self.send_message(
                message_type=message_type,
                source_id=source_id,
                target_id=target_id,
                created_at=created_at,
                payload=payload,
                correlation_id=correlation_id,
                attempt=attempt,
                metadata=metadata,
                ttl_hops=ttl_hops,
            )
            for target_id in unique_targets
        }

    def broadcast(
        self,
        *,
        message_type: MessageType,
        source_id: str,
        created_at: int | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
        exclude_ids: Iterable[str] | None = None,
    ) -> dict[str, bool]:
        excluded_ids = set(exclude_ids or ())
        excluded_ids.add(source_id)

        target_ids = [
            node_id
            for node_id in self._nodes
            if node_id not in excluded_ids
        ]

        return self.multicast(
            message_type=message_type,
            source_id=source_id,
            target_ids=target_ids,
            created_at=created_at,
            payload=payload,
            correlation_id=correlation_id,
            attempt=attempt,
            metadata=metadata,
            ttl_hops=ttl_hops,
        )

    def gossip(
        self,
        *,
        message_type: MessageType,
        source_id: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        attempt: int = 1,
        metadata: dict[str, Any] | None = None,
        ttl_hops: int | None = None,
        fanout: int,
        created_at: int | None = None,
        candidate_ids: Iterable[str] | None = None,
        exclude_ids: Iterable[str] | None = None,
    ) -> dict[str, bool]:
        if fanout < 1:
            raise ValueError("fanout должен быть больше или равен 1")

        excluded_ids = set(exclude_ids or ())
        excluded_ids.add(source_id)

        if candidate_ids is None:
            candidates = [
                node_id
                for node_id in self._nodes
                if node_id not in excluded_ids
            ]
        else:
            candidates = [
                node_id
                for node_id in self._normalize_target_ids(
                    source_id=source_id,
                    target_ids=candidate_ids,
                )
                if node_id not in excluded_ids
            ]

        if not candidates:
            return {}

        if fanout >= len(candidates):
            selected_targets = candidates
        else:
            selected_targets = self._random.sample(
                candidates,
                fanout,
            )

        return self.multicast(
            message_type=message_type,
            source_id=source_id,
            target_ids=selected_targets,
            created_at=created_at,
            payload=payload,
            correlation_id=correlation_id,
            attempt=attempt,
            metadata=metadata,
            ttl_hops=ttl_hops,
        )

    def schedule_timer(
        self,
        node_id: str,
        delay: int,
        timer_name: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> ScheduledEvent:
        node = self._get_node(node_id)
        timer_details = dict(details or {})

        return self._scheduler.schedule(
            delay,
            self._fire_timer,
            node.node_id,
            timer_name,
            timer_details,
        )

    def schedule_timer_at(
        self,
        node_id: str,
        execute_at: int,
        timer_name: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> ScheduledEvent:
        node = self._get_node(node_id)
        timer_details = dict(details or {})

        return self._scheduler.schedule_at(
            execute_at,
            self._fire_timer,
            node.node_id,
            timer_name,
            timer_details,
        )

    def step(self) -> bool:
        return self._scheduler.step()

    def run(
        self,
        *,
        until: int | None = None,
        max_events: int | None = None,
    ) -> int:
        return self._scheduler.run(
            until=until,
            max_events=max_events,
        )

    def _on_message_delivered(
        self,
        node: Node,
        message: Message,
        duplicate: bool,
    ) -> None:
        self._emit(
            SimulationEventType.NODE_MESSAGE_ARRIVED,
            node_id=node.node_id,
            message=message,
            duplicate=duplicate,
        )

        self._scheduler.schedule(
            0,
            self._process_next_message,
            node.node_id,
        )

    def _process_next_message(self, node_id: str) -> None:
        node = self._get_node(node_id)
        message = node.dequeue_message()

        if message is None:
            return

        self._emit(
            SimulationEventType.NODE_MESSAGE_PROCESSED,
            node_id=node.node_id,
            message=message,
        )

        self.get_protocol(node.node_id).on_message(message)

    def _fire_timer(
        self,
        node_id: str,
        timer_name: str,
        details: dict[str, Any],
    ) -> None:
        node = self._get_node(node_id)

        self._emit(
            SimulationEventType.NODE_TIMER_FIRED,
            node_id=node.node_id,
            timer_name=timer_name,
            **details,
        )

        self.get_protocol(node.node_id).on_timer(
            timer_name,
            details,
        )

    def _normalize_target_ids(
        self,
        *,
        source_id: str,
        target_ids: Iterable[str],
    ) -> tuple[str, ...]:
        self._get_node(source_id)

        unique_targets: list[str] = []
        seen_targets: set[str] = set()

        for target_id in target_ids:
            if target_id == source_id or target_id in seen_targets:
                continue

            self._get_node(target_id)
            seen_targets.add(target_id)
            unique_targets.append(target_id)

        return tuple(unique_targets)

    def _get_node(self, node_id: str) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError as error:
            raise KeyError(f"Узел {node_id!r} не зарегистрирован в engine") from error

    def _emit(
        self,
        event_type: SimulationEventType,
        *,
        node_id: str,
        message: Message | None = None,
        timer_name: str | None = None,
        **details: Any,
    ) -> None:
        if self._event_handler is None:
            return

        self._event_handler(
            SimulationEvent(
                time=self.current_time,
                event_type=event_type,
                node_id=node_id,
                message=message,
                timer_name=timer_name,
                local_time=self._nodes[node_id].local_time_at(self.current_time),
                details=details,
            )
        )
