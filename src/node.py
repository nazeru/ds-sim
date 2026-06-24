from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .messages import Message


class NodeStatus(StrEnum):
    ACTIVE = "active"
    FAILED = "failed"
    ISOLATED = "isolated"
    STOPPED = "stopped"


class NodeRole(StrEnum):
    DEFAULT = "default"
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


class NodeFailureModel(StrEnum):
    CRASH_STOP = "crash-stop"
    CRASH_RECOVER_VOLATILE_LOSS = "crash-recover-volatile-loss"
    CRASH_RECOVER_PERSISTENT_STATE = "crash-recover-persistent-state"


@dataclass(frozen=True, slots=True)
class NodeClock:
    offset_ms: int = 0
    drift_ratio: float = 0.0

    def __post_init__(self) -> None:
        if self.drift_ratio <= -1.0:
            raise ValueError("drift_ratio должен быть больше -1.0")

    def local_time_at(self, simulation_time: int) -> int:
        adjusted_time = round(simulation_time * (1 + self.drift_ratio))
        return adjusted_time + self.offset_ms

    def simulation_time_at(self, local_time: int) -> int:
        adjusted_time = local_time - self.offset_ms

        if self.drift_ratio == 0:
            return adjusted_time

        return round(adjusted_time / (1 + self.drift_ratio))


@dataclass(slots=True)
class NodeMetrics:
    messages_sent: int = 0
    messages_received: int = 0
    messages_processed: int = 0
    messages_rejected: int = 0
    failures: int = 0


@dataclass(slots=True)
class Node:
    node_id: str
    status: NodeStatus = NodeStatus.ACTIVE
    role: NodeRole = NodeRole.DEFAULT
    failure_model: NodeFailureModel = NodeFailureModel.CRASH_STOP

    state: dict[str, Any] = field(default_factory=dict)
    inbox: deque[Message] = field(default_factory=deque)
    metrics: NodeMetrics = field(default_factory=NodeMetrics)
    clock: NodeClock = field(default_factory=NodeClock)

    started_at: int = 0
    failed_at: int | None = None
    recovered_at: int | None = None

    @property
    def is_available(self) -> bool:
        return self.status == NodeStatus.ACTIVE

    @property
    def inbox_size(self) -> int:
        return len(self.inbox)

    def enqueue_message(self, message: Message) -> bool:
        if message.target_id != self.node_id:
            raise ValueError(
                f"Сообщение предназначено узлу {message.target_id}, "
                f"но было передано узлу {self.node_id}"
            )

        if not self.is_available:
            self.metrics.messages_rejected += 1
            return False

        self.inbox.append(message)
        self.metrics.messages_received += 1
        return True

    def dequeue_message(self) -> Message | None:
        if not self.is_available or not self.inbox:
            return None

        message = self.inbox.popleft()
        self.metrics.messages_processed += 1
        return message

    def mark_message_sent(self) -> None:
        self.metrics.messages_sent += 1

    def local_time_at(self, simulation_time: int) -> int:
        return self.clock.local_time_at(simulation_time)

    def fail(self, at: int) -> None:
        if self.status == NodeStatus.FAILED:
            return

        self.status = NodeStatus.FAILED
        self.failed_at = at
        self.metrics.failures += 1

    def recover(self, at: int) -> bool:
        if self.failure_model == NodeFailureModel.CRASH_STOP:
            return False

        if self.failure_model == NodeFailureModel.CRASH_RECOVER_VOLATILE_LOSS:
            self.state.clear()
            self.inbox.clear()

        self.status = NodeStatus.ACTIVE
        self.recovered_at = at
        self.failed_at = None
        return True

    def isolate(self) -> None:
        self.status = NodeStatus.ISOLATED

    def stop(self) -> None:
        self.status = NodeStatus.STOPPED

    def set_role(self, role: NodeRole) -> None:
        self.role = role

    def update_state(self, key: str, value: Any) -> None:
        self.state[key] = value
