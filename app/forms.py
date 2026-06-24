from __future__ import annotations

from dataclasses import dataclass

from app.launch import (
    ComparisonLaunchConfig,
    DEFAULT_ALGORITHMS,
)
from src.dissemination import DisseminationAlgorithm
from src.topology import list_topology_presets


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    key: str
    label: str
    help_text: str


@dataclass(slots=True)
class LaunchFormState:
    runs: str
    seed: str
    source_id: str
    algorithms: str
    topologies: str
    latency_ms: str
    jitter_ms: str
    loss_probabilities: str
    duplicate_probabilities: str
    reorder_probabilities: str
    failed_node_counts: str
    failed_channel_counts: str
    ttl_hops: str
    max_simulation_time: str
    gossip_fanout: str
    gossip_rounds: str
    gossip_interval_ms: str
    multicast_branching_factor: str


FIELD_DEFINITIONS = (
    FieldDefinition("runs", "runs", "Число повторов серии."),
    FieldDefinition("seed", "seed", "Базовый seed сценария."),
    FieldDefinition("source_id", "source_id", "Исходный узел, например node-0."),
    FieldDefinition(
        "algorithms",
        "algorithms",
        "Алгоритмы через запятую: unicast, broadcast, multicast, gossip.",
    ),
    FieldDefinition(
        "topologies",
        "topologies",
        "Пресеты через запятую: full_mesh, line, ring, star, tree.",
    ),
    FieldDefinition("latency_ms", "latency_ms", "Базовая задержка канала в мс."),
    FieldDefinition("jitter_ms", "jitter_ms", "Разброс задержки в мс."),
    FieldDefinition(
        "loss_probabilities",
        "loss_probs",
        "Вероятности потерь через запятую, например 0, 0.1, 0.3.",
    ),
    FieldDefinition(
        "duplicate_probabilities",
        "dup_probs",
        "Вероятности дублирования через запятую.",
    ),
    FieldDefinition(
        "reorder_probabilities",
        "reorder_probs",
        "Вероятности переупорядочивания через запятую.",
    ),
    FieldDefinition(
        "failed_node_counts",
        "failed_nodes",
        "Количество отказавших узлов через запятую.",
    ),
    FieldDefinition(
        "failed_channel_counts",
        "failed_channels",
        "Количество отказавших каналов через запятую.",
    ),
    FieldDefinition(
        "ttl_hops",
        "ttl_hops",
        "TTL в хопах. Пусто, чтобы использовать значение по умолчанию.",
    ),
    FieldDefinition(
        "max_simulation_time",
        "max_time",
        "Лимит времени симуляции в мс. Пусто, чтобы не ограничивать.",
    ),
    FieldDefinition("gossip_fanout", "gossip_fanout", "Fanout для gossip."),
    FieldDefinition("gossip_rounds", "gossip_rounds", "Количество gossip-раундов."),
    FieldDefinition(
        "gossip_interval_ms",
        "gossip_interval",
        "Интервал между gossip-раундами в мс.",
    ),
    FieldDefinition(
        "multicast_branching_factor",
        "multicast_branch",
        "Branching factor для multicast.",
    ),
)
OPTIONAL_FIELD_KEYS = {"ttl_hops", "max_simulation_time"}


def default_form_state() -> LaunchFormState:
    defaults = ComparisonLaunchConfig()
    return LaunchFormState(
        runs=str(defaults.runs),
        seed=str(defaults.seed),
        source_id=defaults.source_id,
        algorithms=_join_algorithms(defaults.algorithms),
        topologies=", ".join(defaults.topologies),
        latency_ms=str(defaults.latency_ms),
        jitter_ms=str(defaults.jitter_ms),
        loss_probabilities=_join_scalars(defaults.loss_probabilities),
        duplicate_probabilities=_join_scalars(defaults.duplicate_probabilities),
        reorder_probabilities=_join_scalars(defaults.reorder_probabilities),
        failed_node_counts=_join_scalars(defaults.failed_node_counts),
        failed_channel_counts=_join_scalars(defaults.failed_channel_counts),
        ttl_hops="",
        max_simulation_time="",
        gossip_fanout=str(defaults.gossip_fanout),
        gossip_rounds=str(defaults.gossip_rounds),
        gossip_interval_ms=str(defaults.gossip_interval_ms),
        multicast_branching_factor=str(defaults.multicast_branching_factor),
    )


def _join_algorithms(values: tuple[DisseminationAlgorithm, ...]) -> str:
    return ", ".join(value.value for value in values)


def _join_scalars(values: tuple[object, ...]) -> str:
    return ", ".join(str(value) for value in values)


def _parse_csv(raw_value: str, *, field_name: str) -> tuple[str, ...]:
    values = tuple(
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    )

    if not values:
        raise ValueError(f"{field_name} должен содержать хотя бы одно значение")

    return values


def parse_int_list(raw_value: str, *, field_name: str) -> tuple[int, ...]:
    values = _parse_csv(raw_value, field_name=field_name)

    try:
        return tuple(int(value) for value in values)
    except ValueError as error:
        raise ValueError(
            f"{field_name} должен содержать целые числа через запятую"
        ) from error


def parse_float_list(raw_value: str, *, field_name: str) -> tuple[float, ...]:
    values = _parse_csv(raw_value, field_name=field_name)

    try:
        return tuple(float(value) for value in values)
    except ValueError as error:
        raise ValueError(
            f"{field_name} должен содержать числа через запятую"
        ) from error


def parse_optional_int(raw_value: str, *, field_name: str) -> int | None:
    stripped = raw_value.strip()

    if not stripped:
        return None

    try:
        return int(stripped)
    except ValueError as error:
        raise ValueError(f"{field_name} должен быть целым числом") from error


def parse_int_value(raw_value: str, *, field_name: str) -> int:
    stripped = raw_value.strip()

    if not stripped:
        raise ValueError(f"{field_name} должен быть целым числом")

    try:
        return int(stripped)
    except ValueError as error:
        raise ValueError(f"{field_name} должен быть целым числом") from error


def parse_algorithms(raw_value: str) -> tuple[DisseminationAlgorithm, ...]:
    values = _parse_csv(raw_value, field_name="algorithms")
    algorithms: list[DisseminationAlgorithm] = []
    valid_values = {algorithm.value for algorithm in DisseminationAlgorithm}

    for value in values:
        if value not in valid_values:
            supported = ", ".join(algorithm.value for algorithm in DEFAULT_ALGORITHMS)
            raise ValueError(
                f"Неизвестный алгоритм {value!r}. Допустимо: {supported}"
            )

        algorithms.append(DisseminationAlgorithm(value))

    return tuple(algorithms)


def parse_topologies(raw_value: str) -> tuple[str, ...]:
    values = _parse_csv(raw_value, field_name="topologies")
    available = set(list_topology_presets())

    for value in values:
        if value not in available:
            supported = ", ".join(sorted(available))
            raise ValueError(
                f"Неизвестная topology {value!r}. Допустимо: {supported}"
            )

    return values


def build_launch_config(form: LaunchFormState) -> ComparisonLaunchConfig:
    return ComparisonLaunchConfig(
        runs=parse_int_value(form.runs, field_name="runs"),
        seed=parse_int_value(form.seed, field_name="seed"),
        source_id=form.source_id.strip(),
        algorithms=parse_algorithms(form.algorithms),
        topologies=parse_topologies(form.topologies),
        latency_ms=parse_int_value(form.latency_ms, field_name="latency_ms"),
        jitter_ms=parse_int_value(form.jitter_ms, field_name="jitter_ms"),
        loss_probabilities=parse_float_list(
            form.loss_probabilities,
            field_name="loss_probabilities",
        ),
        duplicate_probabilities=parse_float_list(
            form.duplicate_probabilities,
            field_name="duplicate_probabilities",
        ),
        reorder_probabilities=parse_float_list(
            form.reorder_probabilities,
            field_name="reorder_probabilities",
        ),
        failed_node_counts=parse_int_list(
            form.failed_node_counts,
            field_name="failed_node_counts",
        ),
        failed_channel_counts=parse_int_list(
            form.failed_channel_counts,
            field_name="failed_channel_counts",
        ),
        ttl_hops=parse_optional_int(form.ttl_hops, field_name="ttl_hops"),
        max_simulation_time=parse_optional_int(
            form.max_simulation_time,
            field_name="max_simulation_time",
        ),
        gossip_fanout=parse_int_value(
            form.gossip_fanout,
            field_name="gossip_fanout",
        ),
        gossip_rounds=parse_int_value(
            form.gossip_rounds,
            field_name="gossip_rounds",
        ),
        gossip_interval_ms=parse_int_value(
            form.gossip_interval_ms,
            field_name="gossip_interval_ms",
        ),
        multicast_branching_factor=parse_int_value(
            form.multicast_branching_factor,
            field_name="multicast_branching_factor",
        ),
    )
