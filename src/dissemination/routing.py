from __future__ import annotations

from ..topology import Topology
from .config import DisseminationAlgorithm


def build_children_map(
    algorithm: DisseminationAlgorithm,
    *,
    source_id: str,
    active_node_ids: tuple[str, ...],
    branching_factor: int,
    topology: Topology,
) -> dict[str, tuple[str, ...]]:
    if algorithm == DisseminationAlgorithm.GOSSIP:
        return {}

    effective_branching_factor = 1

    if algorithm == DisseminationAlgorithm.MULTICAST:
        effective_branching_factor = branching_factor

    if algorithm == DisseminationAlgorithm.BROADCAST:
        effective_branching_factor = 10**9

    return build_forwarding_tree(
        source_id=source_id,
        active_node_ids=active_node_ids,
        topology=topology,
        branching_factor=effective_branching_factor,
    )


def build_forwarding_tree(
    *,
    source_id: str,
    active_node_ids: tuple[str, ...],
    topology: Topology,
    branching_factor: int,
) -> dict[str, tuple[str, ...]]:
    if source_id not in active_node_ids:
        return {}

    visited = {source_id}
    queue = [source_id]
    children_by_node: dict[str, tuple[str, ...]] = {}
    active_node_set = set(active_node_ids)

    while queue:
        node_id = queue.pop(0)
        selected_children: list[str] = []

        for neighbor_id in topology.neighbors(node_id):
            if neighbor_id not in active_node_set or neighbor_id in visited:
                continue

            visited.add(neighbor_id)
            selected_children.append(neighbor_id)
            queue.append(neighbor_id)

            if len(selected_children) >= branching_factor:
                break

        if selected_children:
            children_by_node[node_id] = tuple(selected_children)

    return children_by_node


def neighbor_targets(
    neighbor_ids: tuple[str, ...],
    *,
    active_node_ids: tuple[str, ...],
    exclude_ids: tuple[str | None, ...] = (),
) -> tuple[str, ...]:
    active_node_set = set(active_node_ids)
    excluded = {
        node_id
        for node_id in exclude_ids
        if node_id is not None
    }

    return tuple(
        neighbor_id
        for neighbor_id in neighbor_ids
        if neighbor_id in active_node_set and neighbor_id not in excluded
    )
