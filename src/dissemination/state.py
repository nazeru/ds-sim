from __future__ import annotations

from dataclasses import dataclass, field

from .config import DisseminationStudyConfig
from .results import DisseminationRunResult
from .trace_types import DisseminationTraceResult


@dataclass(slots=True)
class DisseminationState:
    config: DisseminationStudyConfig
    rumor_id: str
    source_id: str
    message_ttl_hops: int
    active_node_ids: tuple[str, ...]
    children_by_node: dict[str, tuple[str, ...]]
    informed_at: dict[str, int] = field(default_factory=dict)
    local_informed_at: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class SingleRunOutcome:
    result: DisseminationRunResult
    trace: DisseminationTraceResult | None = None
