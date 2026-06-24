from __future__ import annotations

import json
from functools import lru_cache
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class TopologyKind(StrEnum):
    FULL_MESH = "full_mesh"
    HYPERCUBE = "hypercube"
    LINE = "line"
    RING = "ring"
    STAR = "star"
    TREE = "tree"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Topology:
    adjacency: dict[str, tuple[str, ...]]
    kind: str = TopologyKind.MANUAL

    def __post_init__(self) -> None:
        node_ids = set(self.adjacency)

        for node_id, neighbors in self.adjacency.items():
            if len(set(neighbors)) != len(neighbors):
                raise ValueError(
                    f"Узел {node_id!r} содержит дублирующиеся связи"
                )

            if node_id in neighbors:
                raise ValueError(
                    f"Узел {node_id!r} не должен ссылаться сам на себя"
                )

            missing_neighbors = [
                neighbor_id
                for neighbor_id in neighbors
                if neighbor_id not in node_ids
            ]

            if missing_neighbors:
                missing_list = ", ".join(sorted(missing_neighbors))
                raise ValueError(
                    f"Узел {node_id!r} ссылается на отсутствующие узлы: "
                    f"{missing_list}"
                )

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(self.adjacency)

    def neighbors(self, node_id: str) -> tuple[str, ...]:
        return self.adjacency.get(node_id, ())

    def has_link(self, source_id: str, target_id: str) -> bool:
        return target_id in self.adjacency.get(source_id, ())

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": str(self.kind),
            "adjacency": {
                node_id: list(neighbors)
                for node_id, neighbors in self.adjacency.items()
            },
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> Topology:
        raw_adjacency = data.get("adjacency")

        if not isinstance(raw_adjacency, dict):
            raise ValueError("Topology JSON должен содержать объект adjacency")

        adjacency: dict[str, tuple[str, ...]] = {}

        for node_id, raw_neighbors in raw_adjacency.items():
            if not isinstance(raw_neighbors, list):
                raise ValueError(
                    f"Список соседей для узла {node_id!r} должен быть массивом"
                )

            adjacency[str(node_id)] = tuple(
                str(neighbor_id)
                for neighbor_id in raw_neighbors
            )

        raw_kind = data.get("kind", TopologyKind.MANUAL.value)
        kind = str(raw_kind)

        return cls(
            adjacency=adjacency,
            kind=kind,
        )


def get_topology_presets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "topology_presets"


def list_topology_presets() -> tuple[str, ...]:
    presets_dir = get_topology_presets_dir()

    if not presets_dir.exists():
        return ()

    return tuple(
        path.stem
        for path in sorted(presets_dir.glob("*.json"))
    )


@lru_cache(maxsize=None)
def load_topology(name: str) -> Topology:
    preset_path = get_topology_presets_dir() / f"{name}.json"

    if not preset_path.exists():
        raise FileNotFoundError(
            f"Файл пресета topology не найден: {preset_path}"
        )

    data = json.loads(
        preset_path.read_text(encoding="utf-8")
    )

    if not isinstance(data, dict):
        raise ValueError(
            f"Некорректный формат пресета topology: {preset_path}"
        )

    return Topology.from_dict(data)
