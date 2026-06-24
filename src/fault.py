from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import Engine


class FaultEventType(StrEnum):
    NODE_FAIL = "node_fail"
    NODE_RECOVER = "node_recover"
    CHANNEL_BLOCK = "channel_block"
    CHANNEL_RESTORE = "channel_restore"


@dataclass(frozen=True, slots=True)
class FaultEvent:
    execute_at: int
    event_type: FaultEventType
    node_id: str | None = None
    source_id: str | None = None
    target_id: str | None = None

    def __post_init__(self) -> None:
        if self.execute_at < 0:
            raise ValueError("execute_at не может быть отрицательным")

        if self.event_type in {
            FaultEventType.NODE_FAIL,
            FaultEventType.NODE_RECOVER,
        }:
            if self.node_id is None:
                raise ValueError("Для события узла требуется node_id")

            return

        if self.source_id is None or self.target_id is None:
            raise ValueError("Для события канала требуются source_id и target_id")


@dataclass(frozen=True, slots=True)
class FaultPlan:
    failed_node_ids: tuple[str, ...] = ()
    isolated_node_ids: tuple[str, ...] = ()
    blocked_links: tuple[tuple[str, str], ...] = ()
    unavailable_channels: tuple[tuple[str, str], ...] = ()
    events: tuple[FaultEvent, ...] = ()


def select_faulted_nodes(
    node_ids: tuple[str, ...],
    *,
    source_id: str,
    count: int,
    randomizer: random.Random,
) -> tuple[str, ...]:
    if count < 0:
        raise ValueError("count не может быть отрицательным")

    candidates = [
        node_id
        for node_id in node_ids
        if node_id != source_id
    ]

    if count > len(candidates):
        raise ValueError("count больше числа доступных узлов")

    if count == 0:
        return ()

    selected = randomizer.sample(
        candidates,
        count,
    )
    selected.sort()
    return tuple(selected)


def select_faulted_channels(
    channel_ids: tuple[tuple[str, str], ...],
    *,
    count: int,
    randomizer: random.Random,
) -> tuple[tuple[str, str], ...]:
    if count < 0:
        raise ValueError("count не может быть отрицательным")

    if count > len(channel_ids):
        raise ValueError("count больше числа доступных каналов")

    if count == 0:
        return ()

    selected = randomizer.sample(
        list(channel_ids),
        count,
    )
    selected.sort()
    return tuple(selected)


def apply_fault_plan(engine: Engine, plan: FaultPlan) -> None:
    for node_id in plan.failed_node_ids:
        engine.fail_node(node_id)

    for node_id in plan.isolated_node_ids:
        engine.isolate_node(node_id)

    for source_id, target_id in plan.blocked_links:
        engine.network.block_link(source_id, target_id)

    for source_id, target_id in plan.unavailable_channels:
        engine.network.block_link(source_id, target_id)

    for event in sorted(plan.events, key=lambda item: item.execute_at):
        engine.scheduler.schedule_at(
            event.execute_at,
            _apply_fault_event,
            engine,
            event,
        )


def _apply_fault_event(engine: Engine, event: FaultEvent) -> None:
    if event.event_type == FaultEventType.NODE_FAIL:
        engine.fail_node(_require_node_id(event))
        return

    if event.event_type == FaultEventType.NODE_RECOVER:
        engine.recover_node(_require_node_id(event))
        return

    if event.event_type == FaultEventType.CHANNEL_BLOCK:
        engine.network.block_link(
            _require_source_id(event),
            _require_target_id(event),
        )
        return

    if event.event_type == FaultEventType.CHANNEL_RESTORE:
        engine.network.restore_link(
            _require_source_id(event),
            _require_target_id(event),
        )
        return

    raise ValueError(f"Неизвестный тип fault event: {event.event_type}")


def _require_node_id(event: FaultEvent) -> str:
    if event.node_id is None:
        raise ValueError("Ожидался node_id")

    return event.node_id


def _require_source_id(event: FaultEvent) -> str:
    if event.source_id is None:
        raise ValueError("Ожидался source_id")

    return event.source_id


def _require_target_id(event: FaultEvent) -> str:
    if event.target_id is None:
        raise ValueError("Ожидался target_id")

    return event.target_id
