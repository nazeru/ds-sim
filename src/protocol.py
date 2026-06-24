from __future__ import annotations

from typing import Any

from .messages import Message
from .node import Node, NodeRole
from .runtime import NodeRuntime


class NodeProtocol:
    def __init__(self, *, role: NodeRole | None = None) -> None:
        self._runtime: NodeRuntime | None = None
        self._node: Node | None = None
        self._role = role

    @property
    def runtime(self) -> NodeRuntime:
        if self._runtime is None:
            raise RuntimeError("Протокол еще не привязан к runtime")

        return self._runtime

    @property
    def node(self) -> Node:
        if self._node is None:
            raise RuntimeError("Протокол еще не привязан к узлу")

        return self._node

    @property
    def node_id(self) -> str:
        return self.node.node_id

    @property
    def current_time(self) -> int:
        return self.runtime.current_time

    def bind(self, runtime: NodeRuntime, node: Node) -> None:
        if self._runtime is not None or self._node is not None:
            raise RuntimeError("Протокол уже привязан")

        self._runtime = runtime
        self._node = node

        if self._role is not None:
            node.set_role(self._role)

        self.on_registered()

    def on_registered(self) -> None:
        pass

    def on_message(self, message: Message) -> None:
        pass

    def on_timer(
        self,
        timer_name: str,
        details: dict[str, Any],
    ) -> None:
        pass

    def get_state(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        return self.node.state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        self.node.update_state(key, value)
