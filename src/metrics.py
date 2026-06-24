from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import mean

from .network_events import NetworkEvent, NetworkEventType


@dataclass(frozen=True, slots=True)
class RunMetrics:
    coverage: float
    completion_time: int | None
    time_to_50_percent: int | None
    time_to_90_percent: int | None
    time_to_100_percent: int | None
    messages_sent: int
    messages_delivered: int
    messages_lost: int
    messages_duplicated: int
    message_overhead: float

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "coverage": self.coverage,
            "completion_time": self.completion_time,
            "time_to_50_percent": self.time_to_50_percent,
            "time_to_90_percent": self.time_to_90_percent,
            "time_to_100_percent": self.time_to_100_percent,
            "messages_sent": self.messages_sent,
            "messages_delivered": self.messages_delivered,
            "messages_lost": self.messages_lost,
            "messages_duplicated": self.messages_duplicated,
            "message_overhead": self.message_overhead,
        }


@dataclass(frozen=True, slots=True)
class StudyMetrics:
    success_rate: float
    mean_coverage: float
    mean_completion_time: float | None
    mean_time_to_50_percent: float | None
    mean_time_to_90_percent: float | None
    mean_time_to_100_percent: float | None
    mean_messages_sent: float
    mean_messages_delivered: float
    mean_messages_lost: float
    mean_messages_duplicated: float
    mean_message_overhead: float

    def to_dict(self) -> dict[str, float | None]:
        return {
            "success_rate": self.success_rate,
            "mean_coverage": self.mean_coverage,
            "mean_completion_time": self.mean_completion_time,
            "mean_time_to_50_percent": self.mean_time_to_50_percent,
            "mean_time_to_90_percent": self.mean_time_to_90_percent,
            "mean_time_to_100_percent": self.mean_time_to_100_percent,
            "mean_messages_sent": self.mean_messages_sent,
            "mean_messages_delivered": self.mean_messages_delivered,
            "mean_messages_lost": self.mean_messages_lost,
            "mean_messages_duplicated": self.mean_messages_duplicated,
            "mean_message_overhead": self.mean_message_overhead,
        }


@dataclass(slots=True)
class NetworkMetricCollector:
    messages_delivered: int = 0
    messages_lost: int = 0
    messages_duplicated: int = 0

    def record(self, event: NetworkEvent) -> None:
        if event.event_type == NetworkEventType.MESSAGE_DELIVERED:
            self.messages_delivered += 1
            return

        if event.event_type in {
            NetworkEventType.MESSAGE_LOST,
            NetworkEventType.MESSAGE_DROPPED,
        }:
            self.messages_lost += 1
            return

        if event.event_type == NetworkEventType.MESSAGE_DUPLICATED:
            self.messages_duplicated += 1


def coverage(
    *,
    informed_count: int,
    target_count: int,
) -> float:
    if target_count == 0:
        return 1.0

    return informed_count / target_count


def completion_time(
    *,
    informed_at: dict[str, int],
    target_count: int,
) -> int | None:
    if len(informed_at) != target_count or not informed_at:
        return None

    return max(informed_at.values())


def time_to_percent(
    informed_at: dict[str, int],
    *,
    target_count: int,
    percent: float,
) -> int | None:
    if not 0 < percent <= 1:
        raise ValueError("percent должен быть в диапазоне (0, 1]")

    if target_count == 0:
        return 0

    required_count = ceil(target_count * percent)

    if len(informed_at) < required_count:
        return None

    return sorted(informed_at.values())[required_count - 1]


def message_overhead(
    *,
    messages_sent: int,
    informed_count: int,
) -> float:
    if informed_count <= 1:
        return float(messages_sent)

    return messages_sent / (informed_count - 1)


def mean_optional(values: list[int | None]) -> float | None:
    concrete_values = [
        value
        for value in values
        if value is not None
    ]

    if not concrete_values:
        return None

    return mean(concrete_values)
