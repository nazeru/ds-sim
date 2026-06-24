from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..channel import ChannelConfig
from ..fault import FaultPlan
from ..node import NodeFailureModel
from ..topology import Topology


class DisseminationAlgorithm(StrEnum):
    UNICAST = "unicast"
    BROADCAST = "broadcast"
    MULTICAST = "multicast"
    GOSSIP = "gossip"


@dataclass(frozen=True, slots=True)
class DisseminationStudyConfig:
    algorithm: DisseminationAlgorithm
    topology: Topology

    runs: int = 10
    seed: int = 0

    source_id: str = "node-0"

    latency_ms: int = 10
    jitter_ms: int = 0
    loss_probability: float = 0.0
    duplicate_probability: float = 0.0
    reorder_probability: float = 0.0

    message_ttl_hops: int | None = None

    clock_offset_min_ms: int = 0
    clock_offset_max_ms: int = 0

    node_failure_model: NodeFailureModel = NodeFailureModel.CRASH_STOP

    failed_node_count: int = 0
    failed_channel_count: int = 0
    fault_plan: FaultPlan | None = None

    multicast_branching_factor: int = 2
    gossip_fanout: int = 3
    gossip_rounds: int = 3
    gossip_interval_ms: int = 15

    max_simulation_time: int | None = None

    def __post_init__(self) -> None:
        topology_node_total = len(self.topology.node_ids)

        if self.source_id not in self.topology.adjacency:
            raise ValueError("source_id должен присутствовать в topology")

        if topology_node_total < 2:
            raise ValueError("topology должна содержать хотя бы 2 узла")

        if self.runs < 1:
            raise ValueError("runs должен быть больше или равен 1")

        if self.failed_node_count < 0:
            raise ValueError("failed_node_count не может быть отрицательным")

        if self.failed_node_count >= topology_node_total:
            raise ValueError("failed_node_count должен быть меньше числа узлов")

        if self.failed_channel_count < 0:
            raise ValueError("failed_channel_count не может быть отрицательным")

        if self.multicast_branching_factor < 1:
            raise ValueError(
                "multicast_branching_factor должен быть больше или равен 1"
            )

        if self.gossip_fanout < 1:
            raise ValueError("gossip_fanout должен быть больше или равен 1")

        if self.gossip_rounds < 1:
            raise ValueError("gossip_rounds должен быть больше или равен 1")

        if self.gossip_interval_ms < 0:
            raise ValueError("gossip_interval_ms не может быть отрицательным")

        if self.latency_ms < 0:
            raise ValueError("latency_ms не может быть отрицательным")

        if self.jitter_ms < 0:
            raise ValueError("jitter_ms не может быть отрицательным")

        if not 0 <= self.loss_probability <= 1:
            raise ValueError("loss_probability должен быть в диапазоне [0, 1]")

        if not 0 <= self.duplicate_probability <= 1:
            raise ValueError("duplicate_probability должен быть в диапазоне [0, 1]")

        if not 0 <= self.reorder_probability <= 1:
            raise ValueError("reorder_probability должен быть в диапазоне [0, 1]")

        if self.message_ttl_hops is not None and self.message_ttl_hops < 0:
            raise ValueError("message_ttl_hops не может быть отрицательным")

        if self.clock_offset_min_ms > self.clock_offset_max_ms:
            raise ValueError(
                "clock_offset_max_ms должен быть не меньше clock_offset_min_ms"
            )

        available_channel_count = sum(
            len(neighbors)
            for neighbors in self.topology.adjacency.values()
        )

        if self.failed_channel_count > available_channel_count:
            raise ValueError(
                "failed_channel_count больше числа доступных направленных каналов"
            )

    def resolve_node_ids(self) -> tuple[str, ...]:
        return self.topology.node_ids

    def resolve_channel_config(self) -> ChannelConfig:
        return ChannelConfig(
            latency_ms=self.latency_ms,
            jitter_ms=self.jitter_ms,
            loss_probability=self.loss_probability,
            duplicate_probability=self.duplicate_probability,
            reorder_probability=self.reorder_probability,
        )

    def resolve_message_ttl_hops(self) -> int:
        if self.message_ttl_hops is not None:
            return self.message_ttl_hops

        return max(1, len(self.resolve_node_ids()) - 1)
