from __future__ import annotations

from dataclasses import dataclass, replace

from app.launch import (
    ComparisonLaunchConfig,
    build_comparison_scenario,
    build_visualization_config,
)
from app.playback import PlaybackTrace, prepare_trace_playback
from src.dissemination import (
    ComparisonResult,
    DisseminationStudyConfig,
    DisseminationStudyResult,
    DisseminationTraceResult,
    run_comparison_scenario,
    run_dissemination_study,
    run_dissemination_trace,
)


@dataclass(frozen=True, slots=True)
class DisseminationPlaybackSession:
    trace_result: DisseminationTraceResult
    study_result: DisseminationStudyResult
    playback_trace: PlaybackTrace


def run_comparison(
    config: ComparisonLaunchConfig,
    *,
    name: str = "comparison",
) -> ComparisonResult:
    return run_comparison_scenario(
        build_comparison_scenario(config, name=name)
    )


def build_trace(config: ComparisonLaunchConfig) -> DisseminationTraceResult:
    return run_dissemination_trace(
        build_visualization_config(config)
    )


def build_playback_session(
    config: DisseminationStudyConfig,
) -> DisseminationPlaybackSession:
    """Полностью рассчитывает симуляцию и готовит immutable-модель воспроизведения."""
    trace_result = run_dissemination_trace(replace(config, runs=1))
    study_result = run_dissemination_study(config)
    playback_trace = prepare_trace_playback(trace_result)

    return DisseminationPlaybackSession(
        trace_result=trace_result,
        study_result=study_result,
        playback_trace=playback_trace,
    )
