from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product

from ..fault import FaultPlan
from ..topology import Topology
from .config import DisseminationAlgorithm, DisseminationStudyConfig
from .results import DisseminationStudyResult


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    name: str
    latency_ms: int = 10
    jitter_ms: int = 0
    loss_probability: float = 0.0
    duplicate_probability: float = 0.0
    reorder_probability: float = 0.0


@dataclass(frozen=True, slots=True)
class FailureProfile:
    name: str
    failed_node_count: int = 0
    failed_channel_count: int = 0
    fault_plan: FaultPlan | None = None


@dataclass(frozen=True, slots=True)
class ComparisonCase:
    name: str
    config: DisseminationStudyConfig
    algorithm: DisseminationAlgorithm
    topology_name: str
    channel_profile: ChannelProfile
    failure_profile: FailureProfile


@dataclass(frozen=True, slots=True)
class ComparisonCaseResult:
    case: ComparisonCase
    result: DisseminationStudyResult


@dataclass(frozen=True, slots=True)
class ComparisonScenario:
    name: str
    base_config: DisseminationStudyConfig
    algorithms: tuple[DisseminationAlgorithm, ...]
    topologies: tuple[Topology, ...]
    channel_profiles: tuple[ChannelProfile, ...] = (
        ChannelProfile(name="baseline"),
    )
    failure_profiles: tuple[FailureProfile, ...] = (
        FailureProfile(name="none"),
    )

    def build_cases(self) -> tuple[ComparisonCase, ...]:
        cases: list[ComparisonCase] = []

        for algorithm, topology, channel_profile, failure_profile in product(
            self.algorithms,
            self.topologies,
            self.channel_profiles,
            self.failure_profiles,
        ):
            topology_name = topology.kind
            case_name = (
                f"{algorithm.value}/"
                f"{topology_name}/"
                f"{channel_profile.name}/"
                f"{failure_profile.name}"
            )
            config = replace(
                self.base_config,
                algorithm=algorithm,
                topology=topology,
                latency_ms=channel_profile.latency_ms,
                jitter_ms=channel_profile.jitter_ms,
                loss_probability=channel_profile.loss_probability,
                duplicate_probability=channel_profile.duplicate_probability,
                reorder_probability=channel_profile.reorder_probability,
                failed_node_count=failure_profile.failed_node_count,
                failed_channel_count=failure_profile.failed_channel_count,
                fault_plan=failure_profile.fault_plan,
            )

            cases.append(
                ComparisonCase(
                    name=case_name,
                    config=config,
                    algorithm=algorithm,
                    topology_name=topology_name,
                    channel_profile=channel_profile,
                    failure_profile=failure_profile,
                )
            )

        return tuple(cases)


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    scenario: ComparisonScenario
    cases: tuple[ComparisonCaseResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.scenario.name,
            "cases": [
                {
                    "name": item.case.name,
                    "algorithm": item.case.algorithm.value,
                    "topology": item.case.topology_name,
                    "channel_profile": item.case.channel_profile.name,
                    "failure_profile": item.case.failure_profile.name,
                    **item.result.metrics.to_dict(),
                }
                for item in self.cases
            ],
        }


def run_comparison_scenario(
    scenario: ComparisonScenario,
) -> ComparisonResult:
    from .runner import run_dissemination_study

    return ComparisonResult(
        scenario=scenario,
        cases=tuple(
            ComparisonCaseResult(
                case=case,
                result=run_dissemination_study(case.config),
            )
            for case in scenario.build_cases()
        ),
    )
