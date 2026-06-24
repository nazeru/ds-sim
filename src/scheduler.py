from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Callable


EventCallback = Callable[..., None]


@dataclass(order=True, slots=True)
class ScheduledEvent:
    execute_at: int
    sequence: int

    callback: EventCallback = field(
        compare=False,
        repr=False,
    )
    args: tuple[Any, ...] = field(
        default_factory=tuple,
        compare=False,
        repr=False,
    )
    kwargs: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    cancelled: bool = field(
        default=False,
        compare=False,
    )

    def cancel(self) -> None:
        self.cancelled = True


class Scheduler:
    def __init__(self) -> None:
        self._current_time: int = 0
        self._events: list[ScheduledEvent] = []
        self._sequence = count()

    @property
    def current_time(self) -> int:
        return self._current_time

    @property
    def pending_events(self) -> int:
        return sum(not event.cancelled for event in self._events)

    @property
    def is_empty(self) -> bool:
        self._discard_cancelled_events()
        return not self._events

    @property
    def next_event_time(self) -> int | None:
        self._discard_cancelled_events()

        if not self._events:
            return None

        return self._events[0].execute_at

    def schedule(
        self,
        delay: int,
        callback: EventCallback,
        *args: Any,
        **kwargs: Any,
    ) -> ScheduledEvent:
        if delay < 0:
            raise ValueError("Задержка события не может быть отрицательной")

        return self.schedule_at(
            self._current_time + delay,
            callback,
            *args,
            **kwargs,
        )

    def schedule_at(
        self,
        execute_at: int,
        callback: EventCallback,
        *args: Any,
        **kwargs: Any,
    ) -> ScheduledEvent:
        if execute_at < self._current_time:
            raise ValueError(
                "Нельзя запланировать событие в прошлом: "
                f"current_time={self._current_time}, "
                f"execute_at={execute_at}"
            )

        event = ScheduledEvent(
            execute_at=execute_at,
            sequence=next(self._sequence),
            callback=callback,
            args=args,
            kwargs=kwargs,
        )

        heapq.heappush(self._events, event)

        return event

    def cancel(self, event: ScheduledEvent) -> None:
        event.cancel()

    def step(self) -> bool:
        """
        Выполняет одно ближайшее событие.

        Возвращает:
            True — событие было выполнено.
            False — очередь событий пуста.
        """
        event = self._pop_next_event()

        if event is None:
            return False

        self._execute(event)

        return True

    def run(
        self,
        *,
        until: int | None = None,
        max_events: int | None = None,
    ) -> int:
        """
        Выполняет события до указанного виртуального времени.

        Args:
            until:
                Конечное виртуальное время. Если None,
                выполняются все события.
            max_events:
                Максимальное число событий за один запуск.

        Returns:
            Количество выполненных событий.
        """
        if until is not None and until < self._current_time:
            raise ValueError("until не может быть меньше текущего времени")

        if max_events is not None and max_events < 0:
            raise ValueError("max_events не может быть отрицательным")

        processed = 0

        while True:
            self._discard_cancelled_events()

            if not self._events:
                break

            if max_events is not None and processed >= max_events:
                break

            next_event = self._events[0]

            if until is not None and next_event.execute_at > until:
                break

            event = heapq.heappop(self._events)
            self._execute(event)

            processed += 1

        stopped_by_limit = (
            max_events is not None and processed >= max_events and not self.is_empty
        )

        if until is not None and not stopped_by_limit and self._current_time < until:
            self._current_time = until

        return processed

    def clear(self) -> None:
        self._events.clear()

    def reset(self) -> None:
        self._events.clear()
        self._current_time = 0
        self._sequence = count()

    def _execute(self, event: ScheduledEvent) -> None:
        self._current_time = event.execute_at
        event.callback(*event.args, **event.kwargs)

    def _pop_next_event(self) -> ScheduledEvent | None:
        self._discard_cancelled_events()

        if not self._events:
            return None

        return heapq.heappop(self._events)

    def _discard_cancelled_events(self) -> None:
        while self._events and self._events[0].cancelled:
            heapq.heappop(self._events)
