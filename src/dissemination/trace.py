from __future__ import annotations

from dataclasses import dataclass, field

from ..engine import Engine
from ..events import SimulationEvent, SimulationEventType
from ..messages import Message
from ..network_events import NetworkEvent, NetworkEventType
from ..topology import Topology
from .config import DisseminationStudyConfig
from .results import DisseminationRunResult
from .state import DisseminationState
from .trace_types import (
    DisseminationTraceEvent,
    DisseminationTraceFrame,
    DisseminationTraceLinkState,
    DisseminationTraceNodeState,
    DisseminationTraceResult,
)


@dataclass(slots=True)
class TraceRecorder:
    config: DisseminationStudyConfig
    topology: Topology
    events: list[DisseminationTraceEvent] = field(default_factory=list)
    frames: list[DisseminationTraceFrame] = field(default_factory=list)

    def capture_initial_frame(
        self,
        engine: Engine,
        state: DisseminationState,
    ) -> None:
        self._append_frame(
            engine,
            state,
            event=None,
        )

    def capture_annotation(
        self,
        engine: Engine,
        state: DisseminationState,
        *,
        event_type: str,
        summary: str,
        node_id: str | None = None,
    ) -> None:
        event = DisseminationTraceEvent(
            index=len(self.events),
            time=engine.current_time,
            category="study",
            event_type=event_type,
            summary=summary,
            node_id=node_id,
            local_time=(
                engine.get_node(node_id).local_time_at(engine.current_time)
                if node_id is not None
                else None
            ),
        )
        self.events.append(event)
        self._append_frame(
            engine,
            state,
            event=event,
        )

    def record_network_event(
        self,
        engine: Engine,
        state: DisseminationState,
        event: NetworkEvent,
    ) -> None:
        trace_event = DisseminationTraceEvent(
            index=len(self.events),
            time=event.time,
            category="network",
            event_type=event.event_type.value,
            summary=describe_network_event(event),
            source_id=event.source_id,
            target_id=event.target_id,
            message_id=event.message_id,
        )
        self.events.append(trace_event)
        self._append_frame(engine, state, event=trace_event)

    def record_simulation_event(
        self,
        engine: Engine,
        state: DisseminationState,
        event: SimulationEvent,
    ) -> None:
        trace_event = DisseminationTraceEvent(
            index=len(self.events),
            time=event.time,
            category="simulation",
            event_type=event.event_type.value,
            summary=describe_simulation_event(event),
            node_id=event.node_id,
            source_id=event.message.source_id if event.message is not None else None,
            target_id=event.message.target_id if event.message is not None else None,
            message_id=event.message.message_id if event.message is not None else None,
            local_time=event.local_time,
        )
        self.events.append(trace_event)
        self._append_frame(engine, state, event=trace_event)

    def build_result(
        self,
        result: DisseminationRunResult,
    ) -> DisseminationTraceResult:
        return DisseminationTraceResult(
            config=self.config,
            topology=self.topology,
            run_result=result,
            frames=tuple(self.frames),
            events=tuple(self.events),
        )

    def _append_frame(
        self,
        engine: Engine,
        state: DisseminationState,
        *,
        event: DisseminationTraceEvent | None,
    ) -> None:
        node_states = tuple(
            DisseminationTraceNodeState(
                node_id=node_id,
                status=node.status.value,
                informed_at=state.informed_at.get(node_id),
                inbox_size=node.inbox_size,
                local_time=node.local_time_at(engine.current_time),
                messages_sent=node.metrics.messages_sent,
                messages_received=node.metrics.messages_received,
                messages_processed=node.metrics.messages_processed,
            )
            for node_id in self.topology.node_ids
            for node in [engine.get_node(node_id)]
        )
        link_states = tuple(
            DisseminationTraceLinkState(
                source_id=source_id,
                target_id=target_id,
                is_available=channel.is_available,
            )
            for (source_id, target_id), channel in sorted(
                engine.network.channels.items()
            )
        )
        blocked_link_count = sum(
            1
            for link_state in link_states
            if not link_state.is_available
        )

        self.frames.append(
            DisseminationTraceFrame(
                index=len(self.frames),
                time=engine.current_time,
                event=event,
                node_states=node_states,
                link_states=link_states,
                informed_count=len(state.informed_at),
                blocked_link_count=blocked_link_count,
            )
        )


def describe_network_event(event: NetworkEvent) -> str:
    route = f"{event.source_id} -> {event.target_id}"
    details = event.details

    if event.event_type == NetworkEventType.MESSAGE_SCHEDULED:
        suffix = format_detail_suffix(
            delay_ms=details.get("delay_ms"),
            duplicate=details.get("duplicate"),
            reordered=details.get("reordered"),
        )
        return f"{route}: доставка запланирована{suffix}"

    if event.event_type == NetworkEventType.MESSAGE_DELIVERED:
        suffix = format_detail_suffix(
            duplicate=details.get("duplicate"),
        )
        return f"{route}: сообщение доставлено{suffix}"

    if event.event_type == NetworkEventType.MESSAGE_LOST:
        suffix = format_detail_suffix(
            reason=details.get("reason"),
            duplicate=details.get("duplicate"),
        )
        return f"{route}: сообщение потеряно{suffix}"

    if event.event_type == NetworkEventType.MESSAGE_DROPPED:
        suffix = format_detail_suffix(
            reason=details.get("reason"),
            duplicate=details.get("duplicate"),
        )
        return f"{route}: сообщение отброшено{suffix}"

    if event.event_type == NetworkEventType.MESSAGE_DUPLICATED:
        suffix = format_detail_suffix(
            duplicate_delay_ms=details.get("duplicate_delay_ms"),
        )
        return f"{route}: создан дубликат{suffix}"

    if event.event_type == NetworkEventType.LINK_BLOCKED:
        return f"{route}: канал заблокирован"

    if event.event_type == NetworkEventType.LINK_RESTORED:
        return f"{route}: канал восстановлен"

    return f"{route}: {event.event_type.value}"


def describe_simulation_event(event: SimulationEvent) -> str:
    if event.event_type == SimulationEventType.NODE_MESSAGE_ARRIVED:
        return (
            f"{event.node_id}: сообщение получено "
            f"({describe_message(event.message)})"
        )

    if event.event_type == SimulationEventType.NODE_MESSAGE_PROCESSED:
        return (
            f"{event.node_id}: сообщение обработано "
            f"({describe_message(event.message)})"
        )

    if event.event_type == SimulationEventType.NODE_TIMER_FIRED:
        suffix = format_detail_suffix(
            timer=event.timer_name,
            round=event.details.get("round"),
            rumor_id=event.details.get("rumor_id"),
        )
        return f"{event.node_id}: сработал таймер{suffix}"

    if event.event_type == SimulationEventType.NODE_FAILED:
        return f"{event.node_id}: узел перешел в состояние failed"

    if event.event_type == SimulationEventType.NODE_RECOVERED:
        return f"{event.node_id}: узел восстановлен"

    if event.event_type == SimulationEventType.NODE_ISOLATED:
        return f"{event.node_id}: узел изолирован"

    if event.event_type == SimulationEventType.NODE_STOPPED:
        return f"{event.node_id}: узел остановлен"

    return f"{event.node_id}: {event.event_type.value}"


def describe_message(message: Message | None) -> str:
    if message is None:
        return "без сообщения"

    rumor_id = (
        message.metadata.get("rumor_id")
        or message.payload.get("rumor_id")
    )
    parts = [message.message_type.value]

    if rumor_id:
        parts.append(f"rumor={rumor_id}")

    parts.append(f"ttl={message.ttl_hops}")
    parts.append(f"hop={message.hop_count}")
    return ", ".join(parts)


def format_detail_suffix(**details: object) -> str:
    rendered = [
        f"{key}={value}"
        for key, value in details.items()
        if value is not None and value is not False
    ]

    if not rendered:
        return ""

    return " [" + ", ".join(rendered) + "]"
