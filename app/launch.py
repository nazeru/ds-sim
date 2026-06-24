from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from src.dissemination import (
    ChannelProfile,
    ComparisonScenario,
    DisseminationAlgorithm,
    DisseminationStudyConfig,
    FailureProfile,
)
from src.topology import load_topology

DEFAULT_ALGORITHMS = (
    DisseminationAlgorithm.UNICAST,
    DisseminationAlgorithm.BROADCAST,
    DisseminationAlgorithm.MULTICAST,
    DisseminationAlgorithm.GOSSIP,
)
DEFAULT_TOPOLOGIES = ("full_mesh", "ring", "star", "tree")
_ValueT = TypeVar("_ValueT")


@dataclass(frozen=True, slots=True)
class ComparisonLaunchConfig:
    runs: int = 20
    seed: int = 42
    source_id: str = "node-0"
    algorithms: tuple[DisseminationAlgorithm, ...] = DEFAULT_ALGORITHMS
    topologies: tuple[str, ...] = DEFAULT_TOPOLOGIES
    latency_ms: int = 10
    jitter_ms: int = 40
    loss_probabilities: tuple[float, ...] = (0.0, 0.1, 0.3)
    duplicate_probabilities: tuple[float, ...] = (0.0,)
    reorder_probabilities: tuple[float, ...] = (0.0,)
    failed_node_counts: tuple[int, ...] = (0, 2, 4)
    failed_channel_counts: tuple[int, ...] = (0,)
    ttl_hops: int | None = None
    max_simulation_time: int | None = None
    gossip_fanout: int = 3
    gossip_rounds: int = 4
    gossip_interval_ms: int = 10
    multicast_branching_factor: int = 3


def format_optional(value: float | int | None) -> str:
    if value is None:
        return "-"

    if isinstance(value, int):
        return str(value)

    return f"{value:.2f}"


def build_channel_profiles(
    config: ComparisonLaunchConfig,
) -> tuple[ChannelProfile, ...]:
    profiles: list[ChannelProfile] = []

    for loss_probability in config.loss_probabilities:
        for duplicate_probability in config.duplicate_probabilities:
            for reorder_probability in config.reorder_probabilities:
                name = (
                    f"loss={loss_probability:g},"
                    f"dup={duplicate_probability:g},"
                    f"reorder={reorder_probability:g}"
                )
                profiles.append(
                    ChannelProfile(
                        name=name,
                        latency_ms=config.latency_ms,
                        jitter_ms=config.jitter_ms,
                        loss_probability=loss_probability,
                        duplicate_probability=duplicate_probability,
                        reorder_probability=reorder_probability,
                    )
                )

    return tuple(profiles)


def build_failure_profiles(
    config: ComparisonLaunchConfig,
) -> tuple[FailureProfile, ...]:
    profiles: list[FailureProfile] = []

    for failed_node_count in config.failed_node_counts:
        for failed_channel_count in config.failed_channel_counts:
            profiles.append(
                FailureProfile(
                    name=(
                        f"failed_nodes={failed_node_count},"
                        f"failed_channels={failed_channel_count}"
                    ),
                    failed_node_count=failed_node_count,
                    failed_channel_count=failed_channel_count,
                )
            )

    return tuple(profiles)


def build_comparison_scenario(
    config: ComparisonLaunchConfig,
    *,
    name: str = "comparison",
) -> ComparisonScenario:
    topologies = tuple(load_topology(topology_name) for topology_name in config.topologies)
    base_config = DisseminationStudyConfig(
        algorithm=config.algorithms[0],
        runs=config.runs,
        seed=config.seed,
        source_id=config.source_id,
        topology=topologies[0],
        message_ttl_hops=config.ttl_hops,
        max_simulation_time=config.max_simulation_time,
        multicast_branching_factor=config.multicast_branching_factor,
        gossip_fanout=config.gossip_fanout,
        gossip_rounds=config.gossip_rounds,
        gossip_interval_ms=config.gossip_interval_ms,
    )

    return ComparisonScenario(
        name=name,
        base_config=base_config,
        algorithms=config.algorithms,
        topologies=topologies,
        channel_profiles=build_channel_profiles(config),
        failure_profiles=build_failure_profiles(config),
    )


def build_visualization_config(
    config: ComparisonLaunchConfig,
) -> DisseminationStudyConfig:
    topology_name = _first_or_raise(config.topologies, field_name="topologies")

    return DisseminationStudyConfig(
        algorithm=_first_or_raise(config.algorithms, field_name="algorithms"),
        runs=1,
        seed=config.seed,
        source_id=config.source_id,
        topology=load_topology(topology_name),
        latency_ms=config.latency_ms,
        jitter_ms=config.jitter_ms,
        loss_probability=_first_or_raise(
            config.loss_probabilities,
            field_name="loss_probabilities",
        ),
        duplicate_probability=_first_or_raise(
            config.duplicate_probabilities,
            field_name="duplicate_probabilities",
        ),
        reorder_probability=_first_or_raise(
            config.reorder_probabilities,
            field_name="reorder_probabilities",
        ),
        failed_node_count=_first_or_raise(
            config.failed_node_counts,
            field_name="failed_node_counts",
        ),
        failed_channel_count=_first_or_raise(
            config.failed_channel_counts,
            field_name="failed_channel_counts",
        ),
        message_ttl_hops=config.ttl_hops,
        max_simulation_time=config.max_simulation_time,
        multicast_branching_factor=config.multicast_branching_factor,
        gossip_fanout=config.gossip_fanout,
        gossip_rounds=config.gossip_rounds,
        gossip_interval_ms=config.gossip_interval_ms,
    )


def _first_or_raise(
    values: tuple[_ValueT, ...],
    *,
    field_name: str,
) -> _ValueT:
    if not values:
        raise ValueError(
            f"Поле {field_name} должно содержать хотя бы одно значение"
        )

    return values[0]


def render_case_table(rows: list[dict[str, object]]) -> tuple[str, ...]:
    lines = [
        (
            "algorithm  topology   channel                       failures"
            "                         success  coverage  completion  t50"
            "  t90  sent  deliv  lost  dup  overhead"
        )
    ]

    for row in rows:
        lines.append(
            f"{row['algorithm']:<10} "
            f"{row['topology']:<10} "
            f"{row['channel_profile']:<29} "
            f"{row['failure_profile']:<32} "
            f"{format_optional(row['success_rate']):<8} "
            f"{format_optional(row['mean_coverage']):<9} "
            f"{format_optional(row['mean_completion_time']):<10} "
            f"{format_optional(row['mean_time_to_50_percent']):<4} "
            f"{format_optional(row['mean_time_to_90_percent']):<4} "
            f"{format_optional(row['mean_messages_sent']):<5} "
            f"{format_optional(row['mean_messages_delivered']):<6} "
            f"{format_optional(row['mean_messages_lost']):<5} "
            f"{format_optional(row['mean_messages_duplicated']):<4} "
            f"{format_optional(row['mean_message_overhead'])}"
        )

    return tuple(lines)
