from __future__ import annotations

from typing import Any

from ..messages import Message, MessageType
from ..protocol import NodeProtocol
from .config import DisseminationAlgorithm
from .routing import neighbor_targets
from .state import DisseminationState


class DisseminationProtocol(NodeProtocol):
    def __init__(self, state: DisseminationState) -> None:
        super().__init__()
        self._state = state
        self._seen_rumors: set[str] = set()
        self._rumor_ttl_hops: dict[str, int] = {}

    def start(self) -> None:
        self._mark_informed(
            self._state.rumor_id,
            ttl_hops=self._state.message_ttl_hops,
        )
        self._forward(
            rumor_id=self._state.rumor_id,
            received_from=None,
        )

    def on_message(self, message: Message) -> None:
        rumor_id = str(message.metadata.get("rumor_id", ""))

        if not rumor_id or rumor_id in self._seen_rumors:
            return

        ttl_hops = message.ttl_hops

        if ttl_hops is None:
            return

        self._mark_informed(
            rumor_id,
            ttl_hops=ttl_hops,
        )
        self._forward(
            rumor_id=rumor_id,
            received_from=message.source_id,
        )

    def on_timer(
        self,
        timer_name: str,
        details: dict[str, Any],
    ) -> None:
        if timer_name != "gossip_round":
            return

        rumor_id = str(details.get("rumor_id", ""))

        if rumor_id not in self._seen_rumors:
            return

        self._gossip_once(rumor_id)

    def _mark_informed(
        self,
        rumor_id: str,
        *,
        ttl_hops: int,
    ) -> None:
        self._seen_rumors.add(rumor_id)
        self._state.local_informed_at.setdefault(
            self.node_id,
            self.current_time,
        )
        self._rumor_ttl_hops[rumor_id] = ttl_hops

    def _forward(
        self,
        *,
        rumor_id: str,
        received_from: str | None,
    ) -> None:
        ttl_hops = self._rumor_ttl_hops.get(rumor_id, 0)

        if ttl_hops <= 0:
            return

        algorithm = self._state.config.algorithm

        if algorithm == DisseminationAlgorithm.GOSSIP:
            self._gossip_once(
                rumor_id,
                received_from=received_from,
            )

            for round_number in range(2, self._state.config.gossip_rounds + 1):
                self.runtime.schedule_timer(
                    self._state.config.gossip_interval_ms * (round_number - 1),
                    "gossip_round",
                    details={
                        "rumor_id": rumor_id,
                        "round": round_number,
                    },
                )

            return

        children = self._state.children_by_node.get(
            self.node_id,
            (),
        )

        if not children:
            return

        if algorithm == DisseminationAlgorithm.UNICAST:
            target_id = children[0]
            self.runtime.send_message(
                message_type=MessageType.EVENT,
                target_id=target_id,
                payload={"rumor_id": rumor_id},
                metadata={"rumor_id": rumor_id},
                ttl_hops=ttl_hops,
            )
            return

        if algorithm == DisseminationAlgorithm.BROADCAST:
            neighbors = neighbor_targets(
                self.runtime.get_neighbors(),
                active_node_ids=self._state.active_node_ids,
                exclude_ids=(received_from,),
            )

            if not neighbors:
                return

            self.runtime.multicast(
                message_type=MessageType.EVENT,
                target_ids=neighbors,
                payload={"rumor_id": rumor_id},
                metadata={"rumor_id": rumor_id},
                ttl_hops=ttl_hops,
            )
            return

        self.runtime.multicast(
            message_type=MessageType.EVENT,
            target_ids=children,
            payload={"rumor_id": rumor_id},
            metadata={"rumor_id": rumor_id},
            ttl_hops=ttl_hops,
        )

    def _gossip_once(
        self,
        rumor_id: str,
        *,
        received_from: str | None = None,
    ) -> None:
        ttl_hops = self._rumor_ttl_hops.get(rumor_id, 0)

        if ttl_hops <= 0:
            return

        exclude_ids = [received_from] if received_from is not None else None

        self.runtime.gossip(
            message_type=MessageType.EVENT,
            fanout=self._state.config.gossip_fanout,
            payload={"rumor_id": rumor_id},
            metadata={"rumor_id": rumor_id},
            ttl_hops=ttl_hops,
            candidate_ids=neighbor_targets(
                self.runtime.get_neighbors(),
                active_node_ids=self._state.active_node_ids,
            ),
            exclude_ids=exclude_ids,
        )
