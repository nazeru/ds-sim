from __future__ import annotations

from bisect import insort
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    latency_ms: int = 10
    jitter_ms: int = 0

    loss_probability: float = 0.0
    duplicate_probability: float = 0.0
    reorder_probability: float = 0.0

    duplicate_extra_delay_ms: int = 1

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms не может быть отрицательным")

        if self.jitter_ms < 0:
            raise ValueError("jitter_ms не может быть отрицательным")

        if not 0 <= self.loss_probability <= 1:
            raise ValueError("loss_probability должен быть в диапазоне [0, 1]")

        if not 0 <= self.duplicate_probability <= 1:
            raise ValueError("duplicate_probability должен быть в диапазоне [0, 1]")

        if not 0 <= self.reorder_probability <= 1:
            raise ValueError("reorder_probability должен быть в диапазоне [0, 1]")

        if self.duplicate_extra_delay_ms < 0:
            raise ValueError("duplicate_extra_delay_ms не может быть отрицательным")


@dataclass(slots=True)
class DirectedChannel:
    source_id: str
    target_id: str
    config: ChannelConfig = field(default_factory=ChannelConfig)
    is_available: bool = True
    pending_delivery_times: list[int] = field(default_factory=list, repr=False)

    def block(self) -> None:
        self.is_available = False

    def restore(self) -> None:
        self.is_available = True

    def schedule_delivery(self, execute_at: int) -> None:
        insort(self.pending_delivery_times, execute_at)

    def complete_delivery(self, execute_at: int) -> None:
        try:
            self.pending_delivery_times.remove(execute_at)
        except ValueError:
            return

    @property
    def latest_pending_delivery_time(self) -> int | None:
        if not self.pending_delivery_times:
            return None

        return self.pending_delivery_times[-1]
