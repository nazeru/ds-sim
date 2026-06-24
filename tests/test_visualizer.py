from __future__ import annotations

import unittest
from math import inf

from app.qt.main import compute_graph_render_metrics, compute_layout
from src.dissemination import (
    DisseminationAlgorithm,
    DisseminationStudyConfig,
    run_dissemination_trace,
)
from src.topology import load_topology
from src.topology import Topology


class VisualizationTraceTests(unittest.TestCase):
    def test_compute_layout_keeps_line_topology_readable(self) -> None:
        topology = load_topology("line")
        positions = compute_layout(topology)
        ordered_xs = [positions[node_id][0] for node_id in topology.node_ids]
        ordered_ys = [positions[node_id][1] for node_id in topology.node_ids]

        self.assertEqual(ordered_xs, sorted(ordered_xs))
        self.assertAlmostEqual(max(ordered_ys) - min(ordered_ys), 0.0)

    def test_compute_layout_spreads_hypercube_nodes(self) -> None:
        positions = compute_layout(load_topology("hypercube"))
        min_distance = inf
        points = list(positions.values())

        for index, (x1, y1) in enumerate(points):
            for other_index, (x2, y2) in enumerate(points):
                if index == other_index:
                    continue

                distance = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
                min_distance = min(min_distance, distance)

        self.assertGreater(min_distance, 0.055)

    def test_graph_render_metrics_shrinks_nodes_for_large_topologies(self) -> None:
        small_topology = load_topology("ring")
        small_metrics = compute_graph_render_metrics(
            small_topology,
            compute_layout(small_topology),
        )
        large_topology = Topology(
            adjacency={
                f"node-{index}": ()
                for index in range(500)
            }
        )
        large_positions = {
            f"node-{index}": (
                0.12 + (index % 25) * 0.76 / 24,
                0.12 + (index // 25) * 0.76 / 19,
            )
            for index in range(500)
        }
        large_metrics = compute_graph_render_metrics(
            large_topology,
            large_positions,
        )

        self.assertLess(large_metrics.node_radius, small_metrics.node_radius)
        self.assertNotEqual(large_metrics.label_mode, "all")

    def test_graph_render_metrics_expands_long_line_topology(self) -> None:
        node_count = 500
        topology = Topology(
            adjacency={
                f"node-{index}": ()
                for index in range(node_count)
            }
        )
        positions = {
            f"node-{index}": (
                0.12 + index * 0.76 / (node_count - 1),
                0.5,
            )
            for index in range(node_count)
        }
        metrics = compute_graph_render_metrics(topology, positions)

        self.assertGreater(metrics.scene_width, 5_000)
        self.assertLessEqual(metrics.node_radius, 5)

    def test_load_topology_supports_hypercube_preset(self) -> None:
        topology = load_topology("hypercube")

        self.assertEqual(topology.kind, "hypercube")
        self.assertEqual(len(topology.node_ids), 64)
        self.assertEqual(len(topology.neighbors("node-0")), 6)

    def test_run_dissemination_trace_collects_frames_and_events(self) -> None:
        trace = run_dissemination_trace(
            DisseminationStudyConfig(
                algorithm=DisseminationAlgorithm.BROADCAST,
                topology=load_topology("line"),
                seed=7,
                latency_ms=0,
                jitter_ms=0,
            )
        )

        self.assertGreater(len(trace.frames), 1)
        self.assertIsNone(trace.frames[0].event)
        self.assertEqual(trace.final_frame.informed_count, trace.run_result.informed_count)
        self.assertTrue(
            any(
                event.category == "network"
                and event.event_type == "message_scheduled"
                for event in trace.events
            )
        )

    def test_trace_contains_failed_node_lifecycle_events(self) -> None:
        trace = run_dissemination_trace(
            DisseminationStudyConfig(
                algorithm=DisseminationAlgorithm.BROADCAST,
                topology=load_topology("line"),
                seed=11,
                latency_ms=0,
                jitter_ms=0,
                failed_node_count=1,
            )
        )

        self.assertTrue(
            any(event.event_type == "node_failed" for event in trace.events)
        )


if __name__ == "__main__":
    unittest.main()
