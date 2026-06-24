from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from typing import Any

from .channel import ChannelConfig, DirectedChannel
from .messages import Message
from .network_events import NetworkEvent, NetworkEventHandler, NetworkEventType
from .node import Node
from .scheduler import Scheduler
from .topology import Topology


LatencyProvider = Callable[[Message, DirectedChannel, random.Random], int]
DeliveryHandler = Callable[[Node, Message, bool], None]


class Network:
    def __init__(
        self,
        scheduler: Scheduler,
        *,
        channel_config: ChannelConfig | None = None,
        seed: int = 0,
        latency_provider: LatencyProvider | None = None,
        event_handler: NetworkEventHandler | None = None,
        delivery_handler: DeliveryHandler | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._channel_config_template = channel_config or ChannelConfig()
        self._random = random.Random(seed)

        self._latency_provider = latency_provider
        self._event_handler = event_handler
        self._delivery_handler = delivery_handler

        self._nodes: dict[str, Node] = {}
        self._channels: dict[tuple[str, str], DirectedChannel] = {}
        self._topology: Topology | None = None

    @property
    def scheduler(self) -> Scheduler:
        return self._scheduler

    @property
    def nodes(self) -> dict[str, Node]:
        return dict(self._nodes)

    @property
    def channels(self) -> dict[tuple[str, str], DirectedChannel]:
        return dict(self._channels)

    @property
    def topology(self) -> Topology | None:
        return self._topology

    def register_node(self, node: Node) -> None:
        if node.node_id in self._nodes:
            raise ValueError(f"Узел {node.node_id!r} уже зарегистрирован")

        self._nodes[node.node_id] = node
        self._sync_channels_with_topology()

    def unregister_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise KeyError(f"Узел {node_id!r} не зарегистрирован")

        del self._nodes[node_id]
        self._sync_channels_with_topology()

    def get_node(self, node_id: str) -> Node:
        return self._get_node(node_id)

    def get_neighbors(self, node_id: str) -> tuple[str, ...]:
        self._get_node(node_id)

        if self._topology is None:
            raise RuntimeError("Topology должна быть задана явно")

        return tuple(
            neighbor_id
            for neighbor_id in self._topology.neighbors(node_id)
            if neighbor_id in self._nodes
        )

    def set_topology(self, topology: Topology | None) -> None:
        if topology is not None:
            missing_node_ids = {
                node_id
                for node_id in topology.adjacency
                if node_id not in self._nodes
            }

            if missing_node_ids:
                missing_list = ", ".join(sorted(missing_node_ids))
                raise ValueError(
                    f"Нельзя применить topology: отсутствуют узлы {missing_list}"
                )

        self._topology = topology
        self._sync_channels_with_topology()

    def get_channel(self, source_id: str, target_id: str) -> DirectedChannel:
        self._get_node(source_id)
        self._get_node(target_id)

        channel = self._channels.get((source_id, target_id))

        if channel is None:
            raise KeyError(
                f"Канал {source_id!r} -> {target_id!r} не существует в текущей topology"
            )

        return channel

    def has_channel(self, source_id: str, target_id: str) -> bool:
        return (source_id, target_id) in self._channels

    def set_channel_config(
        self,
        source_id: str,
        target_id: str,
        config: ChannelConfig,
    ) -> None:
        channel = self.get_channel(source_id, target_id)
        channel.config = config

    def send(self, message: Message) -> bool:
        """
        Передаёт сообщение через модель сети.

        Возвращает:
            True — доставка была запланирована.
            False — сообщение сразу отброшено.
        """
        source = self._get_node(message.source_id)
        self._get_node(message.target_id)

        if not source.is_available:
            self._emit(
                NetworkEventType.MESSAGE_DROPPED,
                message,
                reason="source_unavailable",
            )
            return False

        if not message.can_traverse_next_hop():
            self._emit(
                NetworkEventType.MESSAGE_DROPPED,
                message,
                reason="ttl_expired",
            )
            return False

        source.mark_message_sent()

        channel = self._channels.get((message.source_id, message.target_id))

        if channel is None:
            self._emit(
                NetworkEventType.MESSAGE_LOST,
                message,
                reason="topology_blocked",
            )
            return False

        if not channel.is_available:
            self._emit(
                NetworkEventType.MESSAGE_LOST,
                message,
                reason="link_blocked",
            )
            return False

        if self._should_happen(channel.config.loss_probability):
            self._emit(
                NetworkEventType.MESSAGE_LOST,
                message,
                reason="random_loss",
            )
            return False

        latency = self._get_latency(message, channel)

        self._schedule_delivery(
            channel=channel,
            message=message,
            delay=latency,
            duplicate=False,
        )

        if self._should_happen(channel.config.duplicate_probability):
            duplicate_delay = latency + channel.config.duplicate_extra_delay_ms

            self._emit(
                NetworkEventType.MESSAGE_DUPLICATED,
                message,
                duplicate_delay_ms=duplicate_delay,
            )

            self._schedule_delivery(
                channel=channel,
                message=message,
                delay=duplicate_delay,
                duplicate=True,
            )

        return True

    def block_link(
        self,
        source_id: str,
        target_id: str,
    ) -> None:
        channel = self.get_channel(source_id, target_id)

        if not channel.is_available:
            return

        channel.block()
        self._emit_link_event(
            NetworkEventType.LINK_BLOCKED,
            source_id,
            target_id,
        )

    def restore_link(
        self,
        source_id: str,
        target_id: str,
    ) -> None:
        channel = self.get_channel(source_id, target_id)

        if channel.is_available:
            return

        channel.restore()
        self._emit_link_event(
            NetworkEventType.LINK_RESTORED,
            source_id,
            target_id,
        )

    def block_bidirectional_link(
        self,
        first_node_id: str,
        second_node_id: str,
    ) -> None:
        self.block_link(first_node_id, second_node_id)
        self.block_link(second_node_id, first_node_id)

    def restore_bidirectional_link(
        self,
        first_node_id: str,
        second_node_id: str,
    ) -> None:
        self.restore_link(first_node_id, second_node_id)
        self.restore_link(second_node_id, first_node_id)

    def create_partition(
        self,
        first_group: Iterable[str],
        second_group: Iterable[str],
    ) -> None:
        first_nodes = set(first_group)
        second_nodes = set(second_group)

        for node_id in first_nodes | second_nodes:
            self._get_node(node_id)

        for first_id in first_nodes:
            for second_id in second_nodes:
                if first_id == second_id:
                    continue

                if self.has_channel(first_id, second_id):
                    self.block_link(first_id, second_id)

                if self.has_channel(second_id, first_id):
                    self.block_link(second_id, first_id)

    def heal_partition(
        self,
        first_group: Iterable[str],
        second_group: Iterable[str],
    ) -> None:
        first_nodes = set(first_group)
        second_nodes = set(second_group)

        for first_id in first_nodes:
            for second_id in second_nodes:
                if first_id == second_id:
                    continue

                if self.has_channel(first_id, second_id):
                    self.restore_link(first_id, second_id)

                if self.has_channel(second_id, first_id):
                    self.restore_link(second_id, first_id)

    def restore_all_links(self) -> None:
        for channel in tuple(self._channels.values()):
            if channel.is_available:
                continue

            self.restore_link(
                channel.source_id,
                channel.target_id,
            )

    def is_link_blocked(
        self,
        source_id: str,
        target_id: str,
    ) -> bool:
        channel = self._channels.get((source_id, target_id))

        if channel is None:
            return False

        return not channel.is_available

    def _schedule_delivery(
        self,
        *,
        channel: DirectedChannel,
        message: Message,
        delay: int,
        duplicate: bool,
    ) -> None:
        delivery_message = message.prepare_for_delivery()
        execute_at, reordered = self._resolve_delivery_time(
            channel,
            delay,
        )

        channel.schedule_delivery(execute_at)
        scheduled_delay = execute_at - self._scheduler.current_time

        self._scheduler.schedule_at(
            execute_at,
            self._deliver,
            delivery_message,
            duplicate,
            execute_at,
        )

        self._emit(
            NetworkEventType.MESSAGE_SCHEDULED,
            message,
            delay_ms=scheduled_delay,
            duplicate=duplicate,
            reordered=reordered,
        )

    def _deliver(
        self,
        message: Message,
        duplicate: bool,
        execute_at: int,
    ) -> None:
        channel = self._channels.get((message.source_id, message.target_id))

        if channel is None:
            self._emit(
                NetworkEventType.MESSAGE_LOST,
                message,
                reason="topology_blocked_during_delivery",
                duplicate=duplicate,
            )
            return

        channel.complete_delivery(execute_at)

        if not channel.is_available:
            self._emit(
                NetworkEventType.MESSAGE_LOST,
                message,
                reason="link_blocked_during_delivery",
                duplicate=duplicate,
            )
            return

        target = self._get_node(message.target_id)

        if not target.is_available:
            self._emit(
                NetworkEventType.MESSAGE_DROPPED,
                message,
                reason="target_unavailable",
                duplicate=duplicate,
            )
            return

        accepted = target.enqueue_message(message)

        if not accepted:
            self._emit(
                NetworkEventType.MESSAGE_DROPPED,
                message,
                reason="target_rejected",
                duplicate=duplicate,
            )
            return

        self._emit(
            NetworkEventType.MESSAGE_DELIVERED,
            message,
            duplicate=duplicate,
        )

        if self._delivery_handler is not None:
            self._delivery_handler(
                target,
                message,
                duplicate,
            )

    def _get_latency(
        self,
        message: Message,
        channel: DirectedChannel,
    ) -> int:
        if self._latency_provider is not None:
            latency = self._latency_provider(
                message,
                channel,
                self._random,
            )
        else:
            latency = (
                channel.config.latency_ms
                + self._random.randint(0, channel.config.jitter_ms)
            )

        if latency < 0:
            raise ValueError("Модель задержки вернула отрицательное значение")

        return latency

    def _resolve_delivery_time(
        self,
        channel: DirectedChannel,
        delay: int,
    ) -> tuple[int, bool]:
        current_time = self._scheduler.current_time
        execute_at = current_time + delay
        latest_pending = channel.latest_pending_delivery_time

        if latest_pending is None:
            return execute_at, False

        if execute_at <= latest_pending:
            return execute_at, False

        if not self._should_happen(channel.config.reorder_probability):
            return execute_at, False

        upper_bound = max(current_time, latest_pending - 1)

        if upper_bound < current_time:
            return execute_at, False

        reordered_execute_at = self._random.randint(
            current_time,
            upper_bound,
        )

        if reordered_execute_at >= execute_at:
            return execute_at, False

        return reordered_execute_at, True

    def _should_happen(self, probability: float) -> bool:
        return self._random.random() < probability

    def _sync_channels_with_topology(self) -> None:
        desired_links = self._build_desired_links()
        previous_channels = self._channels
        updated_channels: dict[tuple[str, str], DirectedChannel] = {}

        for source_id, target_id in desired_links:
            previous = previous_channels.get((source_id, target_id))

            if previous is not None:
                updated_channels[(source_id, target_id)] = previous
                continue

            updated_channels[(source_id, target_id)] = DirectedChannel(
                source_id=source_id,
                target_id=target_id,
                config=self._channel_config_template,
            )

        self._channels = updated_channels

    def _build_desired_links(self) -> set[tuple[str, str]]:
        if self._topology is None:
            return set()

        return {
            (source_id, target_id)
            for source_id, neighbors in self._topology.adjacency.items()
            if source_id in self._nodes
            for target_id in neighbors
            if target_id in self._nodes and source_id != target_id
        }

    def _get_node(self, node_id: str) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError as error:
            raise KeyError(f"Узел {node_id!r} не зарегистрирован в сети") from error

    def _emit(
        self,
        event_type: NetworkEventType,
        message: Message,
        **details: Any,
    ) -> None:
        if self._event_handler is None:
            return

        self._event_handler(
            NetworkEvent(
                time=self._scheduler.current_time,
                event_type=event_type,
                source_id=message.source_id,
                target_id=message.target_id,
                message_id=message.message_id,
                details=details,
            )
        )

    def _emit_link_event(
        self,
        event_type: NetworkEventType,
        source_id: str,
        target_id: str,
    ) -> None:
        if self._event_handler is None:
            return

        self._event_handler(
            NetworkEvent(
                time=self._scheduler.current_time,
                event_type=event_type,
                source_id=source_id,
                target_id=target_id,
            )
        )
