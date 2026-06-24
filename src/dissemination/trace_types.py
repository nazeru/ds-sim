from __future__ import annotations

from dataclasses import dataclass

from ..topology import Topology
from .config import DisseminationStudyConfig
from .results import DisseminationRunResult


@dataclass(frozen=True, slots=True)
class DisseminationTraceEvent:
    index: int
    time: int
    category: str
    event_type: str
    summary: str
    node_id: str | None = None
    source_id: str | None = None
    target_id: str | None = None
    message_id: str | None = None
    local_time: int | None = None


@dataclass(frozen=True, slots=True)
class DisseminationTraceNodeState:
    node_id: str
    status: str
    informed_at: int | None
    inbox_size: int
    local_time: int
    messages_sent: int
    messages_received: int
    messages_processed: int


@dataclass(frozen=True, slots=True)
class DisseminationTraceLinkState:
    source_id: str
    target_id: str
    is_available: bool


@dataclass(frozen=True, slots=True)
class DisseminationTraceFrame:
    index: int
    time: int
    event: DisseminationTraceEvent | None
    node_states: tuple[DisseminationTraceNodeState, ...]
    link_states: tuple[DisseminationTraceLinkState, ...]
    informed_count: int
    blocked_link_count: int


@dataclass(frozen=True, slots=True)
class DisseminationTraceResult:
    config: DisseminationStudyConfig
    topology: Topology
    run_result: DisseminationRunResult
    frames: tuple[DisseminationTraceFrame, ...]
    events: tuple[DisseminationTraceEvent, ...]

    @property
    def final_frame(self) -> DisseminationTraceFrame:
        return self.frames[-1]
