from __future__ import annotations

import random

from ..engine import Engine
from ..events import SimulationEvent, SimulationEventType
from ..fault import (
    FaultPlan,
    apply_fault_plan,
    select_faulted_channels,
    select_faulted_nodes,
)
from ..metrics import NetworkMetricCollector, completion_time, time_to_percent
from ..network_events import NetworkEvent
from ..node import Node, NodeClock
from .config import DisseminationStudyConfig
from .protocol import DisseminationProtocol
from .results import DisseminationRunResult, DisseminationStudyResult
from .routing import build_children_map
from .state import DisseminationState, SingleRunOutcome
from .trace import TraceRecorder
from .trace_types import DisseminationTraceResult


def run_dissemination_study(
    config: DisseminationStudyConfig,
) -> DisseminationStudyResult:
    study_random = random.Random(config.seed)
    run_results: list[DisseminationRunResult] = []

    for run_index in range(config.runs):
        run_seed = study_random.randrange(10**9)
        run_results.append(
            run_single_dissemination(
                config,
                run_index=run_index,
                run_seed=run_seed,
            ).result
        )

    return DisseminationStudyResult(
        config=config,
        runs=run_results,
    )


def run_dissemination_trace(
    config: DisseminationStudyConfig,
) -> DisseminationTraceResult:
    run_seed = random.Random(config.seed).randrange(10**9)
    outcome = run_single_dissemination(
        config,
        run_index=0,
        run_seed=run_seed,
        trace_recorder=TraceRecorder(
            config=config,
            topology=config.topology,
        ),
    )

    if outcome.trace is None:
        raise RuntimeError("Не удалось собрать trace симуляции")

    return outcome.trace


def merge_fault_plans(
    base: FaultPlan,
    override: FaultPlan | None,
) -> FaultPlan:
    if override is None:
        return base

    return FaultPlan(
        failed_node_ids=base.failed_node_ids + override.failed_node_ids,
        isolated_node_ids=base.isolated_node_ids + override.isolated_node_ids,
        blocked_links=base.blocked_links + override.blocked_links,
        unavailable_channels=(
            base.unavailable_channels + override.unavailable_channels
        ),
        events=base.events + override.events,
    )


def track_dissemination_event(
    state: DisseminationState,
    event: SimulationEvent,
) -> None:
    if event.event_type != SimulationEventType.NODE_MESSAGE_PROCESSED:
        return

    if event.message is None:
        return

    rumor_id = str(event.message.metadata.get("rumor_id", ""))

    if rumor_id != state.rumor_id:
        return

    state.informed_at.setdefault(
        event.node_id,
        event.time,
    )


def run_single_dissemination(
    config: DisseminationStudyConfig,
    *,
    run_index: int,
    run_seed: int,
    trace_recorder: TraceRecorder | None = None,
) -> SingleRunOutcome:
    node_ids = config.resolve_node_ids()
    run_random = random.Random(run_seed)
    topology = config.topology
    message_ttl_hops = config.resolve_message_ttl_hops()

    failed_node_ids = select_faulted_nodes(
        node_ids,
        source_id=config.source_id,
        count=config.failed_node_count,
        randomizer=run_random,
    )

    failed_channel_ids = select_faulted_channels(
        tuple(
            (source_id, target_id)
            for source_id, neighbors in topology.adjacency.items()
            for target_id in neighbors
        ),
        count=config.failed_channel_count,
        randomizer=run_random,
    )

    initial_fault_plan = merge_fault_plans(
        FaultPlan(
            failed_node_ids=failed_node_ids,
            unavailable_channels=failed_channel_ids,
        ),
        config.fault_plan,
    )

    initially_unavailable_node_ids = set(initial_fault_plan.failed_node_ids)
    initially_unavailable_node_ids.update(initial_fault_plan.isolated_node_ids)

    state = DisseminationState(
        config=config,
        rumor_id=f"rumor-{run_index}",
        source_id=config.source_id,
        message_ttl_hops=message_ttl_hops,
        active_node_ids=tuple(
            node_id
            for node_id in node_ids
            if node_id not in initially_unavailable_node_ids
        ),
        children_by_node={},
    )

    network_metrics = NetworkMetricCollector()
    engine: Engine | None = None

    def on_network_event(event: NetworkEvent) -> None:
        network_metrics.record(event)

        if trace_recorder is not None and engine is not None:
            trace_recorder.record_network_event(engine, state, event)

    def on_simulation_event(event: SimulationEvent) -> None:
        track_dissemination_event(state, event)

        if trace_recorder is not None and engine is not None:
            trace_recorder.record_simulation_event(engine, state, event)

    engine = Engine(
        channel_config=config.resolve_channel_config(),
        seed=run_seed,
        network_event_handler=on_network_event,
        event_handler=on_simulation_event,
    )

    state.children_by_node = build_children_map(
        config.algorithm,
        source_id=config.source_id,
        active_node_ids=state.active_node_ids,
        branching_factor=config.multicast_branching_factor,
        topology=topology,
    )

    protocols: dict[str, DisseminationProtocol] = {}

    for node_id in node_ids:
        clock_offset = run_random.randint(
            config.clock_offset_min_ms,
            config.clock_offset_max_ms,
        )
        protocol = DisseminationProtocol(state)
        protocols[node_id] = protocol
        engine.register_node(
            Node(
                node_id=node_id,
                failure_model=config.node_failure_model,
                clock=NodeClock(offset_ms=clock_offset),
            ),
            protocol=protocol,
        )

    engine.set_topology(topology)

    if trace_recorder is not None:
        trace_recorder.capture_initial_frame(engine, state)

    apply_fault_plan(engine, initial_fault_plan)

    if engine.get_node(config.source_id).is_available:
        state.informed_at[config.source_id] = 0
        if trace_recorder is not None:
            trace_recorder.capture_annotation(
                engine,
                state,
                event_type="source_started",
                summary=f"Источник {config.source_id} инициировал распространение",
                node_id=config.source_id,
            )
        protocols[config.source_id].start()

    if config.max_simulation_time is None:
        engine.run()
    else:
        engine.run(until=config.max_simulation_time)

    target_count = len(state.active_node_ids)
    informed_count = len(state.informed_at)
    reached_all = informed_count == target_count

    messages_sent = sum(
        node.metrics.messages_sent
        for node in engine.network.nodes.values()
    )

    result = DisseminationRunResult(
        algorithm=config.algorithm,
        run_index=run_index,
        seed=run_seed,
        informed_count=informed_count,
        target_count=target_count,
        reached_all=reached_all,
        completion_time=completion_time(
            informed_at=state.informed_at,
            target_count=target_count,
        ),
        time_to_50_percent=time_to_percent(
            state.informed_at,
            target_count=target_count,
            percent=0.5,
        ),
        time_to_90_percent=time_to_percent(
            state.informed_at,
            target_count=target_count,
            percent=0.9,
        ),
        time_to_100_percent=time_to_percent(
            state.informed_at,
            target_count=target_count,
            percent=1.0,
        ),
        messages_sent=messages_sent,
        messages_delivered=network_metrics.messages_delivered,
        messages_lost=network_metrics.messages_lost,
        messages_duplicated=network_metrics.messages_duplicated,
        informed_at=dict(state.informed_at),
        failed_node_ids=tuple(sorted(initially_unavailable_node_ids)),
    )

    if trace_recorder is not None:
        trace_recorder.capture_annotation(
            engine,
            state,
            event_type="simulation_finished",
            summary=(
                f"Симуляция завершена: coverage={informed_count}/{target_count}, "
                f"sent={messages_sent}, delivered={network_metrics.messages_delivered}, "
                f"lost={network_metrics.messages_lost}"
            ),
        )
        return SingleRunOutcome(
            result=result,
            trace=trace_recorder.build_result(result),
        )

    return SingleRunOutcome(result=result)
