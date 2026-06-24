from __future__ import annotations

import argparse
import json
import sys

from app.launch import (
    ComparisonLaunchConfig,
    DisseminationAlgorithm,
    build_visualization_config,
    render_case_table,
)
from app.use_cases import run_comparison
from src.topology import list_topology_presets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run reproducible dissemination comparison scenarios.",
    )
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--source-id", default="node-0")
    parser.add_argument(
        "--algorithms",
        nargs="+",
        choices=[algorithm.value for algorithm in DisseminationAlgorithm],
        default=[
            DisseminationAlgorithm.UNICAST.value,
            DisseminationAlgorithm.BROADCAST.value,
            DisseminationAlgorithm.MULTICAST.value,
            DisseminationAlgorithm.GOSSIP.value,
        ],
    )
    parser.add_argument(
        "--topologies",
        nargs="+",
        choices=list_topology_presets(),
        default=["full_mesh", "ring", "star", "tree"],
    )
    parser.add_argument("--latency-ms", type=int, default=10)
    parser.add_argument("--jitter-ms", type=int, default=40)
    parser.add_argument(
        "--loss-probabilities",
        nargs="+",
        type=float,
        default=[0.0, 0.1, 0.3],
    )
    parser.add_argument(
        "--duplicate-probabilities",
        nargs="+",
        type=float,
        default=[0.0],
    )
    parser.add_argument(
        "--reorder-probabilities",
        nargs="+",
        type=float,
        default=[0.0],
    )
    parser.add_argument(
        "--failed-node-counts",
        nargs="+",
        type=int,
        default=[0, 2, 4],
    )
    parser.add_argument(
        "--failed-channel-counts",
        nargs="+",
        type=int,
        default=[0],
    )
    parser.add_argument("--ttl-hops", type=int)
    parser.add_argument("--max-simulation-time", type=int)
    parser.add_argument("--gossip-fanout", type=int, default=3)
    parser.add_argument("--gossip-rounds", type=int, default=4)
    parser.add_argument("--gossip-interval-ms", type=int, default=10)
    parser.add_argument("--multicast-branching-factor", type=int, default=3)
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run non-interactive CLI output mode.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable comparison result.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Open interactive terminal UI.",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Open interactive visualization for one run.",
    )
    return parser.parse_args()


def should_launch_tui(args: argparse.Namespace, argv: list[str]) -> bool:
    if args.visualize:
        return False

    if args.tui:
        return True

    if args.cli or args.json:
        return False

    return len(argv) == 0


def main() -> None:
    argv = sys.argv[1:]
    args = parse_args()

    algorithms = tuple(
        DisseminationAlgorithm(raw_algorithm)
        for raw_algorithm in args.algorithms
    )
    launch_config = ComparisonLaunchConfig(
        runs=args.runs,
        seed=args.seed,
        source_id=args.source_id,
        algorithms=algorithms,
        topologies=tuple(args.topologies),
        latency_ms=args.latency_ms,
        jitter_ms=args.jitter_ms,
        loss_probabilities=tuple(args.loss_probabilities),
        duplicate_probabilities=tuple(args.duplicate_probabilities),
        reorder_probabilities=tuple(args.reorder_probabilities),
        failed_node_counts=tuple(args.failed_node_counts),
        failed_channel_counts=tuple(args.failed_channel_counts),
        ttl_hops=args.ttl_hops,
        max_simulation_time=args.max_simulation_time,
        multicast_branching_factor=args.multicast_branching_factor,
        gossip_fanout=args.gossip_fanout,
        gossip_rounds=args.gossip_rounds,
        gossip_interval_ms=args.gossip_interval_ms,
    )

    if args.visualize:
        from app.terminal.visualizer import launch_visualization

        try:
            launch_visualization(
                build_visualization_config(launch_config)
            )
        except RuntimeError as error:
            raise SystemExit(str(error)) from error
        return

    if should_launch_tui(args, argv):
        from app.terminal.tui import launch_tui

        try:
            launch_tui()
        except RuntimeError as error:
            raise SystemExit(str(error)) from error
        return

    result = run_comparison(launch_config, name="cli-comparison")
    result_data = result.to_dict()

    if args.json:
        print(json.dumps(result_data, indent=2, ensure_ascii=False))
        return

    for line in render_case_table(result_data["cases"]):
        print(line)


if __name__ == "__main__":
    main()
