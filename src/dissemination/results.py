from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from ..metrics import (
    RunMetrics,
    StudyMetrics,
    coverage,
    mean_optional,
    message_overhead,
)
from .config import DisseminationAlgorithm, DisseminationStudyConfig


@dataclass(slots=True)
class DisseminationRunResult:
    algorithm: DisseminationAlgorithm
    run_index: int
    seed: int

    informed_count: int
    target_count: int
    reached_all: bool

    completion_time: int | None
    time_to_50_percent: int | None
    time_to_90_percent: int | None
    time_to_100_percent: int | None

    messages_sent: int
    messages_delivered: int
    messages_lost: int
    messages_duplicated: int

    informed_at: dict[str, int]
    failed_node_ids: tuple[str, ...]

    @property
    def coverage(self) -> float:
        return coverage(
            informed_count=self.informed_count,
            target_count=self.target_count,
        )

    @property
    def message_overhead(self) -> float:
        return message_overhead(
            messages_sent=self.messages_sent,
            informed_count=self.informed_count,
        )

    @property
    def metrics(self) -> RunMetrics:
        return RunMetrics(
            coverage=self.coverage,
            completion_time=self.completion_time,
            time_to_50_percent=self.time_to_50_percent,
            time_to_90_percent=self.time_to_90_percent,
            time_to_100_percent=self.time_to_100_percent,
            messages_sent=self.messages_sent,
            messages_delivered=self.messages_delivered,
            messages_lost=self.messages_lost,
            messages_duplicated=self.messages_duplicated,
            message_overhead=self.message_overhead,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm.value,
            "run_index": self.run_index,
            "seed": self.seed,
            "informed_count": self.informed_count,
            "target_count": self.target_count,
            "reached_all": self.reached_all,
            "failed_node_ids": list(self.failed_node_ids),
            "informed_at": dict(self.informed_at),
            **self.metrics.to_dict(),
        }


@dataclass(slots=True)
class DisseminationStudyResult:
    config: DisseminationStudyConfig
    runs: list[DisseminationRunResult]

    @property
    def success_rate(self) -> float:
        return mean(
            1.0 if run.reached_all else 0.0
            for run in self.runs
        )

    @property
    def mean_coverage(self) -> float:
        return mean(run.coverage for run in self.runs)

    @property
    def mean_completion_time(self) -> float | None:
        successful_runs = [
            run.completion_time
            for run in self.runs
            if run.completion_time is not None
        ]

        if not successful_runs:
            return None

        return mean(successful_runs)

    @property
    def metrics(self) -> StudyMetrics:
        return StudyMetrics(
            success_rate=self.success_rate,
            mean_coverage=self.mean_coverage,
            mean_completion_time=self.mean_completion_time,
            mean_time_to_50_percent=mean_optional(
                [run.time_to_50_percent for run in self.runs]
            ),
            mean_time_to_90_percent=mean_optional(
                [run.time_to_90_percent for run in self.runs]
            ),
            mean_time_to_100_percent=mean_optional(
                [run.time_to_100_percent for run in self.runs]
            ),
            mean_messages_sent=mean(run.messages_sent for run in self.runs),
            mean_messages_delivered=mean(
                run.messages_delivered for run in self.runs
            ),
            mean_messages_lost=mean(run.messages_lost for run in self.runs),
            mean_messages_duplicated=mean(
                run.messages_duplicated for run in self.runs
            ),
            mean_message_overhead=mean(run.message_overhead for run in self.runs),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "metrics": self.metrics.to_dict(),
            "runs": [
                run.to_dict()
                for run in self.runs
            ],
        }
