from __future__ import annotations

import unittest

from app.forms import (
    build_launch_config,
    default_form_state,
    parse_optional_int,
    parse_topologies,
)
from app.launch import build_comparison_scenario, build_visualization_config
from src.dissemination import DisseminationAlgorithm


class TuiConfigTests(unittest.TestCase):
    def test_build_launch_config_parses_form_values(self) -> None:
        form = default_form_state()
        form.runs = "5"
        form.seed = "99"
        form.algorithms = "broadcast, gossip"
        form.topologies = "ring, star"
        form.ttl_hops = "7"
        form.max_simulation_time = ""
        form.failed_node_counts = "0, 1"
        form.failed_channel_counts = "0, 2"

        config = build_launch_config(form)

        self.assertEqual(config.runs, 5)
        self.assertEqual(config.seed, 99)
        self.assertEqual(
            config.algorithms,
            (
                DisseminationAlgorithm.BROADCAST,
                DisseminationAlgorithm.GOSSIP,
            ),
        )
        self.assertEqual(config.topologies, ("ring", "star"))
        self.assertEqual(config.ttl_hops, 7)
        self.assertIsNone(config.max_simulation_time)
        self.assertEqual(config.failed_node_counts, (0, 1))
        self.assertEqual(config.failed_channel_counts, (0, 2))

    def test_parse_optional_int_accepts_empty_string(self) -> None:
        self.assertIsNone(
            parse_optional_int("", field_name="max_simulation_time")
        )

    def test_parse_topologies_rejects_unknown_preset(self) -> None:
        with self.assertRaisesRegex(ValueError, "Неизвестная topology"):
            parse_topologies("ring, unknown-topology")

    def test_build_comparison_scenario_uses_same_form_config(self) -> None:
        form = default_form_state()
        form.algorithms = "broadcast, gossip"
        form.topologies = "line, ring"
        form.loss_probabilities = "0, 0.2"
        form.failed_node_counts = "0"
        form.failed_channel_counts = "0, 1"

        launch_config = build_launch_config(form)
        scenario = build_comparison_scenario(launch_config, name="test-tui")

        self.assertEqual(scenario.name, "test-tui")
        self.assertEqual(len(scenario.algorithms), 2)
        self.assertEqual(len(scenario.topologies), 2)
        self.assertEqual(len(scenario.channel_profiles), 2)
        self.assertEqual(len(scenario.failure_profiles), 2)

    def test_build_visualization_config_uses_first_selected_values(self) -> None:
        form = default_form_state()
        form.algorithms = "gossip, broadcast"
        form.topologies = "star, ring"
        form.loss_probabilities = "0.3, 0.1"
        form.failed_node_counts = "2, 0"

        launch_config = build_launch_config(form)
        visualization_config = build_visualization_config(launch_config)

        self.assertEqual(
            visualization_config.algorithm,
            DisseminationAlgorithm.GOSSIP,
        )
        self.assertEqual(visualization_config.topology.kind, "star")
        self.assertEqual(visualization_config.loss_probability, 0.3)
        self.assertEqual(visualization_config.failed_node_count, 2)


if __name__ == "__main__":
    unittest.main()
