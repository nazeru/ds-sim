from __future__ import annotations

from dataclasses import dataclass
from math import cos, inf, pi, sin

import networkx as nx

from src.dissemination import (
    DisseminationTraceEvent,
    DisseminationTraceFrame,
    DisseminationTraceResult,
)
from src.topology import Topology, TopologyKind


GRAPH_BASE_WIDTH = 920
GRAPH_BASE_HEIGHT = 620
GRAPH_MARGIN = 80
GRAPH_MAX_WIDTH = 18_000
GRAPH_MAX_HEIGHT = 12_000


@dataclass(frozen=True, slots=True)
class GraphRenderMetrics:
    scene_width: float
    scene_height: float
    margin: float
    node_radius: float
    label_mode: str
    show_footers: bool


@dataclass(frozen=True, slots=True)
class PlaybackNode:
    node_id: str
    center_x: float
    center_y: float
    radius: float
    label_x: float
    label_y: float
    footer_x: float
    footer_y: float
    has_label: bool
    has_footer: bool


@dataclass(frozen=True, slots=True)
class PlaybackLink:
    source_id: str
    target_id: str
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    arrow_x1: float
    arrow_y1: float
    arrow_x2: float
    arrow_y2: float


@dataclass(frozen=True, slots=True)
class PlaybackNodeState:
    node_id: str
    fill_color: str
    border_color: str
    border_width: int
    label_visible: bool
    footer_text: str


@dataclass(frozen=True, slots=True)
class PlaybackLinkState:
    source_id: str
    target_id: str
    color: str
    width: int
    dashed: bool


@dataclass(frozen=True, slots=True)
class PlaybackFrame:
    index: int
    time: int
    category: str
    event_type: str
    summary: str
    header_text: str
    stats_text: str
    details_text: str
    node_states: tuple[PlaybackNodeState, ...]
    link_states: tuple[PlaybackLinkState, ...]


@dataclass(frozen=True, slots=True)
class PlaybackTrace:
    topology_signature: tuple[tuple[str, tuple[str, ...]], ...]
    scene_width: float
    scene_height: float
    nodes: tuple[PlaybackNode, ...]
    links: tuple[PlaybackLink, ...]
    frames: tuple[PlaybackFrame, ...]


def topology_links(topology: Topology) -> list[tuple[str, str]]:
    return [
        (source_id, target_id)
        for source_id, neighbors in topology.adjacency.items()
        for target_id in neighbors
    ]


def topology_signature(
    topology: Topology,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (node_id, tuple(topology.adjacency[node_id]))
        for node_id in topology.node_ids
    )


def prepare_static_playback(
    topology: Topology,
    *,
    source_id: str | None,
) -> PlaybackTrace:
    return _prepare_playback(
        topology,
        source_id=source_id,
        trace_frames=(),
        target_count=len(topology.node_ids),
    )


def prepare_trace_playback(
    trace_result: DisseminationTraceResult,
) -> PlaybackTrace:
    return _prepare_playback(
        trace_result.topology,
        source_id=trace_result.config.source_id,
        trace_frames=trace_result.frames,
        target_count=trace_result.run_result.target_count,
    )


def _prepare_playback(
    topology: Topology,
    *,
    source_id: str | None,
    trace_frames: tuple[DisseminationTraceFrame, ...],
    target_count: int,
) -> PlaybackTrace:
    if not topology.node_ids:
        return PlaybackTrace(
            topology_signature=topology_signature(topology),
            scene_width=GRAPH_BASE_WIDTH,
            scene_height=GRAPH_BASE_HEIGHT,
            nodes=(),
            links=(),
            frames=(
                PlaybackFrame(
                    index=0,
                    time=0,
                    category="initial",
                    event_type="initial",
                    summary="Добавьте хотя бы один узел.",
                    header_text="Добавьте хотя бы один узел.",
                    stats_text="Нет узлов.",
                    details_text="Добавьте хотя бы один узел.",
                    node_states=(),
                    link_states=(),
                ),
            ),
        )

    positions = compute_layout(topology)
    metrics = compute_graph_render_metrics(topology, positions)
    inner_width = max(1.0, metrics.scene_width - metrics.margin * 2)
    inner_height = max(1.0, metrics.scene_height - metrics.margin * 2)
    pixel_positions = {
        node_id: (
            metrics.margin + x * inner_width,
            metrics.margin + y * inner_height,
        )
        for node_id, (x, y) in positions.items()
    }

    important_label_nodes = {source_id} if source_id is not None else set()
    important_label_nodes.update(
        frame.event.node_id
        for frame in trace_frames
        if frame.event is not None and frame.event.node_id is not None
    )

    nodes = tuple(
        PlaybackNode(
            node_id=node_id,
            center_x=pixel_positions[node_id][0],
            center_y=pixel_positions[node_id][1],
            radius=metrics.node_radius,
            label_x=pixel_positions[node_id][0],
            label_y=pixel_positions[node_id][1],
            footer_x=pixel_positions[node_id][0],
            footer_y=pixel_positions[node_id][1] + metrics.node_radius + 8,
            has_label=(
                metrics.label_mode == "all"
                or (
                    metrics.label_mode == "important"
                    and node_id in important_label_nodes
                )
            ),
            has_footer=metrics.show_footers,
        )
        for node_id in topology.node_ids
    )

    links = tuple(
        _build_playback_link(
            source_id=source_id_value,
            target_id=target_id,
            start=pixel_positions[source_id_value],
            end=pixel_positions[target_id],
            node_radius=metrics.node_radius,
        )
        for source_id_value, target_id in topology_links(topology)
    )

    if trace_frames:
        frames = tuple(
            _build_playback_frame(
                topology=topology,
                source_id=source_id,
                trace_frame=frame,
                metrics=metrics,
                target_count=target_count,
            )
            for frame in trace_frames
        )
    else:
        frames = (
            _build_static_frame(
                topology=topology,
                source_id=source_id,
                metrics=metrics,
            ),
        )

    return PlaybackTrace(
        topology_signature=topology_signature(topology),
        scene_width=metrics.scene_width,
        scene_height=metrics.scene_height,
        nodes=nodes,
        links=links,
        frames=frames,
    )


def _build_playback_link(
    *,
    source_id: str,
    target_id: str,
    start: tuple[float, float],
    end: tuple[float, float],
    node_radius: float,
) -> PlaybackLink:
    start_x, start_y = start
    end_x, end_y = end
    dx = end_x - start_x
    dy = end_y - start_y
    length = (dx * dx + dy * dy) ** 0.5

    if length < 4:
        return PlaybackLink(
            source_id=source_id,
            target_id=target_id,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            arrow_x1=end_x,
            arrow_y1=end_y,
            arrow_x2=end_x,
            arrow_y2=end_y,
        )

    trim_distance = min(node_radius + 2, max(0.0, length / 2 - 1))
    unit_x = dx / length
    unit_y = dy / length
    trimmed_start_x = start_x + unit_x * trim_distance
    trimmed_start_y = start_y + unit_y * trim_distance
    trimmed_end_x = end_x - unit_x * trim_distance
    trimmed_end_y = end_y - unit_y * trim_distance
    angle = _qt_line_angle(dx, dy)
    arrow_size = max(4.0, min(12.0, node_radius * 0.8))
    arrow_x1 = trimmed_end_x + sin(angle + pi / 3) * arrow_size
    arrow_y1 = trimmed_end_y + cos(angle + pi / 3) * arrow_size
    arrow_x2 = trimmed_end_x + sin(angle + pi - pi / 3) * arrow_size
    arrow_y2 = trimmed_end_y + cos(angle + pi - pi / 3) * arrow_size

    return PlaybackLink(
        source_id=source_id,
        target_id=target_id,
        start_x=trimmed_start_x,
        start_y=trimmed_start_y,
        end_x=trimmed_end_x,
        end_y=trimmed_end_y,
        arrow_x1=arrow_x1,
        arrow_y1=arrow_y1,
        arrow_x2=arrow_x2,
        arrow_y2=arrow_y2,
    )


def _qt_line_angle(dx: float, dy: float) -> float:
    # QLineF.angle() использует ось Y, направленную вниз.
    from math import atan2

    degrees = (-atan2(dy, dx) * 180.0 / pi) % 360.0
    return degrees * pi / 180.0


def _build_static_frame(
    *,
    topology: Topology,
    source_id: str | None,
    metrics: GraphRenderMetrics,
) -> PlaybackFrame:
    node_states = tuple(
        PlaybackNodeState(
            node_id=node_id,
            fill_color="#2f4858",
            border_color="#38bdf8" if node_id == source_id else "#e2e8f0",
            border_width=(
                max(2, round(metrics.node_radius / 7))
                if node_id == source_id
                else max(1, round(metrics.node_radius / 12))
            ),
            label_visible=(
                metrics.label_mode == "all"
                or (
                    metrics.label_mode == "important"
                    and node_id == source_id
                )
            ),
            footer_text="",
        )
        for node_id in topology.node_ids
    )
    link_states = tuple(
        PlaybackLinkState(
            source_id=source,
            target_id=target,
            color="#64748b",
            width=1,
            dashed=False,
        )
        for source, target in topology_links(topology)
    )

    return PlaybackFrame(
        index=0,
        time=0,
        category="initial",
        event_type="initial",
        summary="Топология подготовлена.",
        header_text="Топология подготовлена.",
        stats_text=f"nodes={len(topology.node_ids)} | links={len(link_states)}",
        details_text="Топология подготовлена к запуску симуляции.",
        node_states=node_states,
        link_states=link_states,
    )


def _build_playback_frame(
    *,
    topology: Topology,
    source_id: str | None,
    trace_frame: DisseminationTraceFrame,
    metrics: GraphRenderMetrics,
    target_count: int,
) -> PlaybackFrame:
    event = trace_frame.event
    node_state_map = {
        state.node_id: state
        for state in trace_frame.node_states
    }
    link_state_map = {
        (state.source_id, state.target_id): state.is_available
        for state in trace_frame.link_states
    }

    node_states: list[PlaybackNodeState] = []

    for node_id in topology.node_ids:
        state = node_state_map.get(node_id)
        fill_color = _node_fill_color(state.status if state is not None else None, state.informed_at if state is not None else None)
        border_color = "#e2e8f0"
        border_width = max(1, round(metrics.node_radius / 12))

        if source_id == node_id:
            border_color = "#38bdf8"
            border_width = max(2, round(metrics.node_radius / 7))

        if event is not None and event.node_id == node_id:
            border_color = "#facc15"
            border_width = max(2, round(metrics.node_radius / 5))

        label_visible = metrics.label_mode == "all" or (
            metrics.label_mode == "important"
            and (
                source_id == node_id
                or (event is not None and event.node_id == node_id)
            )
        )
        footer_text = ""

        if metrics.show_footers and state is not None:
            footer_text = (
                f"{state.status} | inbox={state.inbox_size} | "
                f"t={state.local_time}"
            )

        node_states.append(
            PlaybackNodeState(
                node_id=node_id,
                fill_color=fill_color,
                border_color=border_color,
                border_width=border_width,
                label_visible=label_visible,
                footer_text=footer_text,
            )
        )

    link_states: list[PlaybackLinkState] = []

    for source_node, target_node in topology_links(topology):
        is_available = link_state_map.get((source_node, target_node), True)
        is_highlighted = event_route_matches(
            event,
            source_node,
            target_node,
        )

        if not is_available:
            link_states.append(
                PlaybackLinkState(
                    source_id=source_node,
                    target_id=target_node,
                    color="#ef4444",
                    width=1,
                    dashed=True,
                )
            )
            continue

        link_states.append(
            PlaybackLinkState(
                source_id=source_node,
                target_id=target_node,
                color="#f59e0b" if is_highlighted else "#64748b",
                width=(
                    max(1, round(metrics.node_radius / 8))
                    if is_highlighted
                    else 1
                ),
                dashed=False,
            )
        )

    category = event.category if event is not None else "initial"
    event_type = event.event_type if event is not None else "initial"
    summary = event.summary if event is not None else "Исходное состояние"
    header_text = (
        "Исходное состояние перед стартом источника."
        if event is None
        else f"[{event.category}] {event.event_type} | {event.summary}"
    )
    stats_text = " | ".join(
        [
            f"frame={trace_frame.index + 1}",
            f"time={trace_frame.time} ms",
            f"informed={trace_frame.informed_count}/{target_count}",
            f"blocked_links={trace_frame.blocked_link_count}",
        ]
    )

    return PlaybackFrame(
        index=trace_frame.index,
        time=trace_frame.time,
        category=category,
        event_type=event_type,
        summary=summary,
        header_text=header_text,
        stats_text=stats_text,
        details_text=_frame_details_text(trace_frame),
        node_states=tuple(node_states),
        link_states=tuple(link_states),
    )


def _node_fill_color(status: str | None, informed_at: int | None) -> str:
    if status == "failed":
        return "#b91c1c"
    if status == "isolated":
        return "#d97706"
    if status == "stopped":
        return "#475569"
    if informed_at is not None:
        return "#15803d"
    if status is None:
        return "#2f4858"
    return "#2563eb"


def event_route_matches(
    event: DisseminationTraceEvent | None,
    source_id: str,
    target_id: str,
) -> bool:
    return bool(
        event is not None
        and event.source_id == source_id
        and event.target_id == target_id
    )


def _frame_details_text(frame: DisseminationTraceFrame) -> str:
    lines = [
        f"Кадр: {frame.index}",
        f"Время: {frame.time} ms",
        f"Осведомлено узлов: {frame.informed_count}",
        f"Заблокировано каналов: {frame.blocked_link_count}",
    ]

    if frame.event is not None:
        lines.extend(
            [
                "",
                "Событие",
                f"category: {frame.event.category}",
                f"type: {frame.event.event_type}",
                f"summary: {frame.event.summary}",
                f"node_id: {frame.event.node_id or '-'}",
                f"source_id: {frame.event.source_id or '-'}",
                f"target_id: {frame.event.target_id or '-'}",
                f"message_id: {frame.event.message_id or '-'}",
                f"local_time: {frame.event.local_time if frame.event.local_time is not None else '-'}",
            ]
        )

    lines.extend(["", "Узлы"])
    for node_state in frame.node_states:
        lines.append(
            " | ".join(
                [
                    node_state.node_id,
                    f"status={node_state.status}",
                    f"informed_at={_format_optional(node_state.informed_at)}",
                    f"inbox={node_state.inbox_size}",
                    f"sent={node_state.messages_sent}",
                    f"recv={node_state.messages_received}",
                    f"proc={node_state.messages_processed}",
                ]
            )
        )

    return "\n".join(lines)


def _format_optional(value: int | float | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    return f"{value:.3f}"


def compute_layout(topology: Topology) -> dict[str, tuple[float, float]]:
    node_ids = topology.node_ids

    if not node_ids:
        return {}

    if len(node_ids) == 1:
        return {node_ids[0]: (0.5, 0.5)}

    graph = nx.DiGraph()
    graph.add_nodes_from(node_ids)
    graph.add_edges_from(topology_links(topology))
    undirected_graph = graph.to_undirected()

    try:
        raw_positions = _select_layout(topology, undirected_graph)
    except Exception:
        raw_positions = nx.circular_layout(graph)

    return _normalize_layout(raw_positions)


def compute_graph_render_metrics(
    topology: Topology,
    positions: dict[str, tuple[float, float]] | None = None,
) -> GraphRenderMetrics:
    positions = compute_layout(topology) if positions is None else positions
    node_count = len(topology.node_ids)

    if node_count <= 1:
        return GraphRenderMetrics(
            scene_width=GRAPH_BASE_WIDTH,
            scene_height=GRAPH_BASE_HEIGHT,
            margin=GRAPH_MARGIN,
            node_radius=26,
            label_mode="all",
            show_footers=True,
        )

    one_dimensional_axis = _one_dimensional_axis(positions)
    density_scale = max(1.0, (node_count / 120) ** 0.5)
    scene_width = GRAPH_BASE_WIDTH * density_scale
    scene_height = GRAPH_BASE_HEIGHT * density_scale

    if one_dimensional_axis == "x":
        scene_width = max(scene_width, GRAPH_MARGIN * 2 + node_count * 11)
        scene_height = GRAPH_BASE_HEIGHT
    elif one_dimensional_axis == "y":
        scene_width = GRAPH_BASE_WIDTH
        scene_height = max(scene_height, GRAPH_MARGIN * 2 + node_count * 11)

    scene_width = min(GRAPH_MAX_WIDTH, scene_width)
    scene_height = min(GRAPH_MAX_HEIGHT, scene_height)

    min_pixel_distance = _minimum_pixel_distance(
        positions,
        scene_width=scene_width,
        scene_height=scene_height,
        margin=GRAPH_MARGIN,
    )
    distance_radius = (
        26
        if min_pixel_distance == inf
        else max(3.0, min(26.0, min_pixel_distance * 0.34))
    )
    count_radius_cap = max(
        3.0,
        min(26.0, 28 / max(1.0, (node_count / 36) ** 0.46)),
    )
    node_radius = min(distance_radius, count_radius_cap)

    if node_count <= 120 and node_radius >= 10:
        label_mode = "all"
    elif node_count <= 500 and node_radius >= 6:
        label_mode = "important"
    else:
        label_mode = "none"

    return GraphRenderMetrics(
        scene_width=scene_width,
        scene_height=scene_height,
        margin=GRAPH_MARGIN,
        node_radius=node_radius,
        label_mode=label_mode,
        show_footers=node_count <= 60 and node_radius >= 14,
    )


def _one_dimensional_axis(
    positions: dict[str, tuple[float, float]],
) -> str | None:
    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]

    if max(ys) - min(ys) < 0.02:
        return "x"
    if max(xs) - min(xs) < 0.02:
        return "y"
    return None


def _minimum_pixel_distance(
    positions: dict[str, tuple[float, float]],
    *,
    scene_width: float,
    scene_height: float,
    margin: float,
) -> float:
    points = list(positions.values())
    min_distance = inf
    inner_width = max(1.0, scene_width - margin * 2)
    inner_height = max(1.0, scene_height - margin * 2)

    for index, (x1, y1) in enumerate(points):
        px1 = margin + x1 * inner_width
        py1 = margin + y1 * inner_height

        for x2, y2 in points[index + 1:]:
            px2 = margin + x2 * inner_width
            py2 = margin + y2 * inner_height
            distance = ((px1 - px2) ** 2 + (py1 - py2) ** 2) ** 0.5
            min_distance = min(min_distance, distance)

    return min_distance


def _select_layout(
    topology: Topology,
    graph: nx.Graph,
) -> dict[str, tuple[float, float] | object]:
    if _is_path_graph(graph):
        return _build_path_layout(graph)
    if _is_cycle_graph(graph) or _is_complete_graph(graph):
        return nx.circular_layout(graph)
    if _is_star_graph(graph):
        return _build_star_layout(graph)
    if topology.kind == TopologyKind.TREE or nx.is_tree(graph):
        return _build_layered_layout(graph)
    return _pick_best_layout_candidate(graph)


def _pick_best_layout_candidate(
    graph: nx.Graph,
) -> dict[str, tuple[float, float] | object]:
    candidates: list[dict[str, tuple[float, float] | object]] = [
        _build_bfs_shell_layout(graph),
    ]
    node_count = max(2, len(graph.nodes))
    spring_k = 1.2 / (node_count ** 0.5)

    for seed in range(8):
        candidates.append(
            nx.spring_layout(
                graph,
                seed=seed,
                k=spring_k,
                iterations=300,
            )
        )

    return max(candidates, key=_layout_score)


def _build_bfs_shell_layout(
    graph: nx.Graph,
) -> dict[str, tuple[float, float] | object]:
    shells: list[list[str]] = []

    for component in nx.connected_components(graph):
        subgraph = graph.subgraph(component)
        anchor = max(
            subgraph.nodes,
            key=lambda node_id: (subgraph.degree[node_id], str(node_id)),
        )
        distance_map = nx.single_source_shortest_path_length(subgraph, anchor)
        grouped: dict[int, list[str]] = {}

        for node_id, distance in distance_map.items():
            grouped.setdefault(distance, []).append(str(node_id))

        for distance in sorted(grouped):
            shells.append(sorted(grouped[distance]))

    return nx.shell_layout(graph, shells)


def _build_layered_layout(
    graph: nx.Graph,
) -> dict[str, tuple[float, float] | object]:
    layered_graph = graph.copy()

    for component_index, component in enumerate(nx.connected_components(graph)):
        subgraph = graph.subgraph(component)
        anchor = max(
            subgraph.nodes,
            key=lambda node_id: (subgraph.degree[node_id], str(node_id)),
        )

        for node_id, distance in nx.single_source_shortest_path_length(
            subgraph,
            anchor,
        ).items():
            layered_graph.nodes[node_id]["subset"] = (
                component_index,
                distance,
            )

    return nx.multipartite_layout(
        layered_graph,
        subset_key="subset",
        align="vertical",
    )


def _build_path_layout(graph: nx.Graph) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    components = [
        graph.subgraph(component).copy()
        for component in nx.connected_components(graph)
    ]
    component_count = len(components)

    for component_index, subgraph in enumerate(components):
        endpoints = sorted(
            (
                node_id
                for node_id, degree in subgraph.degree()
                if degree <= 1
            ),
            key=str,
        )
        current_node = endpoints[0] if endpoints else sorted(subgraph.nodes, key=str)[0]
        previous_node: str | None = None
        ordered_nodes: list[str] = []

        while True:
            ordered_nodes.append(str(current_node))
            next_nodes = [
                str(node_id)
                for node_id in sorted(subgraph.neighbors(current_node), key=str)
                if node_id != previous_node
            ]

            if not next_nodes:
                break

            previous_node, current_node = current_node, next_nodes[0]

        y = (
            0.5
            if component_count == 1
            else component_index / max(1, component_count - 1)
        )
        denominator = max(1, len(ordered_nodes) - 1)

        for index, node_id in enumerate(ordered_nodes):
            x = 0.5 if len(ordered_nodes) == 1 else index / denominator
            positions[node_id] = (x, y)

    return positions


def _build_star_layout(graph: nx.Graph) -> dict[str, tuple[float, float]]:
    center_node = max(
        graph.nodes,
        key=lambda node_id: (graph.degree[node_id], str(node_id)),
    )
    leaf_nodes = sorted(
        (str(node_id) for node_id in graph.nodes if node_id != center_node),
    )
    positions: dict[str, tuple[float, float]] = {str(center_node): (0.0, 0.0)}
    leaf_count = len(leaf_nodes)

    for index, node_id in enumerate(leaf_nodes):
        angle = 2 * pi * index / max(1, leaf_count)
        positions[node_id] = (cos(angle), sin(angle))

    return positions


def _is_path_graph(graph: nx.Graph) -> bool:
    return (
        nx.is_forest(graph)
        and all(degree <= 2 for _, degree in graph.degree())
        and sum(1 for _, degree in graph.degree() if degree == 1)
        == 2 * nx.number_connected_components(graph)
    )


def _is_cycle_graph(graph: nx.Graph) -> bool:
    return nx.is_connected(graph) and all(
        degree == 2
        for _, degree in graph.degree()
    )


def _is_complete_graph(graph: nx.Graph) -> bool:
    node_count = len(graph.nodes)
    return node_count > 1 and all(
        degree == node_count - 1
        for _, degree in graph.degree()
    )


def _is_star_graph(graph: nx.Graph) -> bool:
    node_count = len(graph.nodes)

    if node_count < 3 or not nx.is_connected(graph):
        return False

    degrees = sorted(degree for _, degree in graph.degree())
    return degrees == [1] * (node_count - 1) + [node_count - 1]


def _layout_score(
    raw_positions: dict[str, tuple[float, float] | object],
) -> tuple[float, float]:
    positions = list(_normalize_layout(raw_positions).values())
    min_distance = inf
    nearest_neighbor_total = 0.0

    for index, (x1, y1) in enumerate(positions):
        nearest_neighbor = inf

        for other_index, (x2, y2) in enumerate(positions):
            if index == other_index:
                continue

            distance = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
            nearest_neighbor = min(nearest_neighbor, distance)

        min_distance = min(min_distance, nearest_neighbor)
        nearest_neighbor_total += nearest_neighbor

    return (
        min_distance,
        nearest_neighbor_total / max(1, len(positions)),
    )


def _normalize_layout(
    raw_positions: dict[str, tuple[float, float] | object],
) -> dict[str, tuple[float, float]]:
    xs = [float(position[0]) for position in raw_positions.values()]
    ys = [float(position[1]) for position in raw_positions.values()]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    def normalize(value: float, lower: float, upper: float) -> float:
        if abs(upper - lower) < 1e-9:
            return 0.5
        return 0.12 + 0.76 * ((value - lower) / (upper - lower))

    return {
        node_id: (
            normalize(float(position[0]), min_x, max_x),
            normalize(float(position[1]), min_y, max_y),
        )
        for node_id, position in raw_positions.items()
    }
