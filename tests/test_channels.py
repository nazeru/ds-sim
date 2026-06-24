from __future__ import annotations

import unittest

from src.engine import Engine
from src.fault import FaultEvent, FaultEventType, FaultPlan, apply_fault_plan
from src.messages import Message, MessageType
from src.channel import ChannelConfig
from src.network import Network
from src.network_events import NetworkEventType
from src.node import Node, NodeClock
from src.protocol import NodeProtocol
from src.dissemination import (
    ChannelProfile,
    ComparisonScenario,
    DisseminationAlgorithm,
    DisseminationStudyConfig,
    FailureProfile,
    run_comparison_scenario,
    run_dissemination_study,
)
from src.scheduler import Scheduler
from src.topology import Topology, TopologyKind


class DirectedChannelTests(unittest.TestCase):
    def test_topology_creates_directed_channels(self) -> None:
        scheduler = Scheduler()
        events = []
        network = Network(
            scheduler,
            channel_config=ChannelConfig(latency_ms=0, jitter_ms=0),
            event_handler=events.append,
        )
        network.register_node(Node(node_id="a"))
        network.register_node(Node(node_id="b"))
        network.set_topology(
            Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "a": ("b",),
                    "b": (),
                },
            )
        )

        self.assertTrue(network.has_channel("a", "b"))
        self.assertFalse(network.has_channel("b", "a"))

        delivered = network.send(
            Message.create(
                message_type=MessageType.EVENT,
                source_id="b",
                target_id="a",
                created_at=0,
            )
        )

        self.assertFalse(delivered)
        self.assertEqual(events[-1].event_type, NetworkEventType.MESSAGE_LOST)
        self.assertEqual(events[-1].details["reason"], "topology_blocked")

    def test_blocked_channel_affects_only_one_direction(self) -> None:
        scheduler = Scheduler()
        network = Network(
            scheduler,
            channel_config=ChannelConfig(latency_ms=0, jitter_ms=0),
        )
        node_a = Node(node_id="a")
        node_b = Node(node_id="b")
        network.register_node(node_a)
        network.register_node(node_b)
        network.set_topology(
            Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "a": ("b",),
                    "b": ("a",),
                },
            )
        )

        network.block_link("a", "b")

        self.assertTrue(network.is_link_blocked("a", "b"))
        self.assertFalse(network.is_link_blocked("b", "a"))

        self.assertFalse(
            network.send(
                Message.create(
                    message_type=MessageType.EVENT,
                    source_id="a",
                    target_id="b",
                    created_at=0,
                )
            )
        )
        self.assertTrue(
            network.send(
                Message.create(
                    message_type=MessageType.EVENT,
                    source_id="b",
                    target_id="a",
                    created_at=0,
                )
            )
        )

        scheduler.run()

        self.assertEqual(node_a.inbox_size, 1)
        self.assertEqual(node_b.inbox_size, 0)

    def test_channel_state_survives_topology_reapply(self) -> None:
        scheduler = Scheduler()
        network = Network(scheduler)
        network.register_node(Node(node_id="a"))
        network.register_node(Node(node_id="b"))
        topology = Topology(
            kind=TopologyKind.MANUAL,
            adjacency={
                "a": ("b",),
                "b": ("a",),
            },
        )
        network.set_topology(topology)
        network.block_link("a", "b")

        network.set_topology(topology)

        self.assertTrue(network.is_link_blocked("a", "b"))
        self.assertFalse(network.is_link_blocked("b", "a"))

    def test_reorder_probability_can_overtake_pending_delivery(self) -> None:
        scheduler = Scheduler()
        delivery_order: list[int] = []

        def latency_provider(message, _channel, _randomizer) -> int:
            return int(message.payload["delay"])

        def delivery_handler(_node: Node, message: Message, _duplicate: bool) -> None:
            delivery_order.append(int(message.payload["seq"]))

        network = Network(
            scheduler,
            channel_config=ChannelConfig(
                latency_ms=0,
                jitter_ms=0,
                reorder_probability=1.0,
            ),
            seed=7,
            latency_provider=latency_provider,
            delivery_handler=delivery_handler,
        )
        network.register_node(Node(node_id="a"))
        network.register_node(Node(node_id="b"))
        network.set_topology(
            Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "a": ("b",),
                    "b": (),
                },
            )
        )

        network.send(
            Message.create(
                message_type=MessageType.EVENT,
                source_id="a",
                target_id="b",
                created_at=0,
                payload={"seq": 1, "delay": 20},
            )
        )
        network.send(
            Message.create(
                message_type=MessageType.EVENT,
                source_id="a",
                target_id="b",
                created_at=0,
                payload={"seq": 2, "delay": 30},
            )
        )

        scheduler.run()

        self.assertEqual(delivery_order, [2, 1])


class DisseminationConfigTests(unittest.TestCase):
    def test_channel_parameters_map_to_channel_config(self) -> None:
        config = DisseminationStudyConfig(
            algorithm=DisseminationAlgorithm.BROADCAST,
            topology=Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "node-0": ("node-1",),
                    "node-1": ("node-0",),
                },
            ),
            latency_ms=5,
            jitter_ms=4,
            loss_probability=0.2,
            duplicate_probability=0.3,
            reorder_probability=0.4,
        )

        channel_config = config.resolve_channel_config()

        self.assertEqual(channel_config.latency_ms, 5)
        self.assertEqual(channel_config.jitter_ms, 4)
        self.assertAlmostEqual(channel_config.loss_probability, 0.2)
        self.assertEqual(channel_config.duplicate_probability, 0.3)
        self.assertEqual(channel_config.reorder_probability, 0.4)

    def test_default_ttl_comes_from_topology_size(self) -> None:
        config = DisseminationStudyConfig(
            algorithm=DisseminationAlgorithm.BROADCAST,
            topology=Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "node-0": ("node-1", "node-2"),
                    "node-1": ("node-0",),
                    "node-2": ("node-0",),
                },
            ),
        )

        self.assertEqual(config.resolve_message_ttl_hops(), 2)


class TtlTests(unittest.TestCase):
    def test_message_ttl_zero_is_dropped_before_send(self) -> None:
        scheduler = Scheduler()
        events = []
        network = Network(
            scheduler,
            channel_config=ChannelConfig(latency_ms=0, jitter_ms=0),
            event_handler=events.append,
        )
        network.register_node(Node(node_id="a"))
        network.register_node(Node(node_id="b"))
        network.set_topology(
            Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "a": ("b",),
                    "b": (),
                },
            )
        )

        delivered = network.send(
            Message.create(
                message_type=MessageType.EVENT,
                source_id="a",
                target_id="b",
                created_at=0,
                ttl_hops=0,
            )
        )

        self.assertFalse(delivered)
        self.assertEqual(events[-1].event_type, NetworkEventType.MESSAGE_DROPPED)
        self.assertEqual(events[-1].details["reason"], "ttl_expired")

    def test_ttl_limits_dissemination_in_cycle(self) -> None:
        result = run_dissemination_study(
            DisseminationStudyConfig(
                algorithm=DisseminationAlgorithm.BROADCAST,
                runs=1,
                seed=7,
                source_id="a",
                topology=Topology(
                    kind=TopologyKind.MANUAL,
                    adjacency={
                        "a": ("b", "d"),
                        "b": ("a", "c"),
                        "c": ("b", "d"),
                        "d": ("a", "c"),
                    },
                ),
                latency_ms=0,
                jitter_ms=0,
                message_ttl_hops=1,
            )
        )

        run = result.runs[0]

        self.assertEqual(run.informed_count, 3)
        self.assertNotIn("c", run.informed_at)


class DisseminationMetricsTests(unittest.TestCase):
    def test_run_metrics_include_thresholds_and_network_counters(self) -> None:
        result = run_dissemination_study(
            DisseminationStudyConfig(
                algorithm=DisseminationAlgorithm.UNICAST,
                runs=1,
                seed=11,
                source_id="a",
                topology=Topology(
                    kind=TopologyKind.MANUAL,
                    adjacency={
                        "a": ("b",),
                        "b": ("a", "c"),
                        "c": ("b",),
                    },
                ),
                latency_ms=5,
                jitter_ms=0,
            )
        )

        run = result.runs[0]

        self.assertEqual(run.coverage, 1.0)
        self.assertEqual(run.completion_time, 10)
        self.assertEqual(run.time_to_50_percent, 5)
        self.assertEqual(run.time_to_90_percent, 10)
        self.assertEqual(run.time_to_100_percent, 10)
        self.assertEqual(run.messages_sent, 2)
        self.assertEqual(run.messages_delivered, 2)
        self.assertEqual(run.messages_lost, 0)
        self.assertEqual(run.messages_duplicated, 0)
        self.assertEqual(run.message_overhead, 1.0)

        self.assertEqual(result.success_rate, 1.0)
        self.assertEqual(result.mean_coverage, 1.0)
        self.assertEqual(result.mean_completion_time, 10)
        self.assertEqual(result.metrics.mean_messages_sent, 2)

    def test_duplicate_messages_are_counted_without_changing_coverage(self) -> None:
        result = run_dissemination_study(
            DisseminationStudyConfig(
                algorithm=DisseminationAlgorithm.BROADCAST,
                runs=1,
                seed=5,
                source_id="a",
                topology=Topology(
                    kind=TopologyKind.MANUAL,
                    adjacency={
                        "a": ("b",),
                        "b": ("a",),
                    },
                ),
                latency_ms=1,
                jitter_ms=0,
                duplicate_probability=1.0,
            )
        )

        run = result.runs[0]

        self.assertEqual(run.coverage, 1.0)
        self.assertEqual(run.messages_sent, 1)
        self.assertEqual(run.messages_delivered, 2)
        self.assertEqual(run.messages_duplicated, 1)
        self.assertEqual(run.messages_lost, 0)

    def test_study_is_reproducible_with_fixed_seed(self) -> None:
        config = DisseminationStudyConfig(
            algorithm=DisseminationAlgorithm.GOSSIP,
            runs=5,
            seed=123,
            topology=Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "node-0": ("node-1", "node-2"),
                    "node-1": ("node-0", "node-2"),
                    "node-2": ("node-0", "node-1"),
                },
            ),
            latency_ms=1,
            jitter_ms=3,
            loss_probability=0.2,
            duplicate_probability=0.1,
            gossip_fanout=1,
            gossip_rounds=3,
        )

        first = run_dissemination_study(config)
        second = run_dissemination_study(config)

        self.assertEqual(first.to_dict(), second.to_dict())


class ComparisonScenarioTests(unittest.TestCase):
    def test_comparison_scenario_builds_cross_product(self) -> None:
        topologies = (
            Topology(
                kind=TopologyKind.LINE,
                adjacency={
                    "node-0": ("node-1",),
                    "node-1": ("node-0",),
                },
            ),
            Topology(
                kind=TopologyKind.FULL_MESH,
                adjacency={
                    "node-0": ("node-1",),
                    "node-1": ("node-0",),
                },
            ),
        )
        scenario = ComparisonScenario(
            name="test",
            base_config=DisseminationStudyConfig(
                algorithm=DisseminationAlgorithm.BROADCAST,
                runs=2,
                seed=3,
                topology=topologies[0],
                latency_ms=0,
                jitter_ms=0,
            ),
            algorithms=(
                DisseminationAlgorithm.BROADCAST,
                DisseminationAlgorithm.GOSSIP,
            ),
            topologies=topologies,
            channel_profiles=(
                ChannelProfile(name="clean", latency_ms=0),
                ChannelProfile(name="lossy", latency_ms=0, loss_probability=0.5),
            ),
            failure_profiles=(
                FailureProfile(name="none"),
                FailureProfile(name="one-node", failed_node_count=1),
            ),
        )

        comparison = run_comparison_scenario(scenario)

        self.assertEqual(len(comparison.cases), 16)
        self.assertIn("cases", comparison.to_dict())


class FaultHandlingTests(unittest.TestCase):
    def test_scheduled_node_failure_drops_message_at_delivery(self) -> None:
        network_events = []
        engine = Engine(
            channel_config=ChannelConfig(latency_ms=10, jitter_ms=0),
            network_event_handler=network_events.append,
        )
        engine.register_node(Node(node_id="a"), protocol=NodeProtocol())
        engine.register_node(Node(node_id="b"), protocol=NodeProtocol())
        engine.set_topology(
            Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "a": ("b",),
                    "b": (),
                },
            )
        )

        apply_fault_plan(
            engine,
            FaultPlan(
                events=(
                    FaultEvent(
                        execute_at=5,
                        event_type=FaultEventType.NODE_FAIL,
                        node_id="b",
                    ),
                ),
            ),
        )

        engine.send_message(
            message_type=MessageType.EVENT,
            source_id="a",
            target_id="b",
            ttl_hops=1,
        )
        engine.run()

        self.assertEqual(engine.get_node("b").inbox_size, 0)
        self.assertEqual(network_events[-1].event_type, NetworkEventType.MESSAGE_DROPPED)
        self.assertEqual(network_events[-1].details["reason"], "target_unavailable")

    def test_scheduled_channel_failure_drops_message_in_transit(self) -> None:
        network_events = []
        engine = Engine(
            channel_config=ChannelConfig(latency_ms=10, jitter_ms=0),
            network_event_handler=network_events.append,
        )
        engine.register_node(Node(node_id="a"), protocol=NodeProtocol())
        engine.register_node(Node(node_id="b"), protocol=NodeProtocol())
        engine.set_topology(
            Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "a": ("b",),
                    "b": (),
                },
            )
        )

        apply_fault_plan(
            engine,
            FaultPlan(
                events=(
                    FaultEvent(
                        execute_at=5,
                        event_type=FaultEventType.CHANNEL_BLOCK,
                        source_id="a",
                        target_id="b",
                    ),
                ),
            ),
        )

        engine.send_message(
            message_type=MessageType.EVENT,
            source_id="a",
            target_id="b",
            ttl_hops=1,
        )
        engine.run()

        self.assertEqual(engine.get_node("b").inbox_size, 0)
        self.assertEqual(network_events[-1].event_type, NetworkEventType.MESSAGE_LOST)
        self.assertEqual(
            network_events[-1].details["reason"],
            "link_blocked_during_delivery",
        )


class LocalTimeTests(unittest.TestCase):
    def test_protocol_observes_local_time_and_local_created_at(self) -> None:
        class SourceProtocol(NodeProtocol):
            def start(self) -> None:
                self.runtime.send_message(
                    message_type=MessageType.EVENT,
                    target_id="b",
                    ttl_hops=1,
                )

        class TargetProtocol(NodeProtocol):
            def __init__(self) -> None:
                super().__init__()
                self.observed_local_time: int | None = None
                self.observed_created_at: int | None = None

            def on_message(self, message: Message) -> None:
                self.observed_local_time = self.current_time
                self.observed_created_at = message.created_at

        target_protocol = TargetProtocol()
        engine = Engine(
            channel_config=ChannelConfig(latency_ms=10, jitter_ms=0),
        )
        source_protocol = SourceProtocol()
        engine.register_node(
            Node(
                node_id="a",
                clock=NodeClock(offset_ms=50),
            ),
            protocol=source_protocol,
        )
        engine.register_node(
            Node(
                node_id="b",
                clock=NodeClock(offset_ms=100),
            ),
            protocol=target_protocol,
        )
        engine.set_topology(
            Topology(
                kind=TopologyKind.MANUAL,
                adjacency={
                    "a": ("b",),
                    "b": (),
                },
            )
        )

        source_protocol.start()
        engine.run()

        self.assertEqual(target_protocol.observed_local_time, 110)
        self.assertEqual(target_protocol.observed_created_at, 50)


if __name__ == "__main__":
    unittest.main()
