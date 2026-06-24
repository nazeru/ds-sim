from __future__ import annotations

import curses

from src.dissemination import (
    DisseminationStudyConfig,
    DisseminationTraceEvent,
    DisseminationTraceFrame,
    DisseminationTraceLinkState,
    DisseminationTraceNodeState,
    DisseminationTraceResult,
    run_dissemination_trace,
)


class SimulationVisualizerApp:
    def __init__(self, trace: DisseminationTraceResult) -> None:
        self.trace = trace
        self.frame_index = 0
        self.playing = False
        self.status = (
            "space: play/pause | <-/->: шаг | PgUp/PgDn: прыжок | g/G: начало/конец | q: выход"
        )

    def run(self, stdscr: curses.window) -> None:
        stdscr.keypad(True)
        curses.cbreak()
        curses.noecho()

        try:
            curses.curs_set(0)
        except curses.error:
            pass

        while True:
            self._draw(stdscr)
            stdscr.timeout(150 if self.playing else -1)
            key = stdscr.getch()

            if key == -1:
                if not self.playing:
                    continue

                if self.frame_index >= len(self.trace.frames) - 1:
                    self.playing = False
                    self.status = "Достигнут конец trace."
                    continue

                self.frame_index += 1
                continue

            if key in (ord("q"), 27):
                return
            if key == ord(" "):
                self.playing = not self.playing
                self.status = "Автопрокрутка включена." if self.playing else "Пауза."
                continue
            if key in (curses.KEY_RIGHT, ord("l"), ord("j")):
                self.playing = False
                self.frame_index = min(len(self.trace.frames) - 1, self.frame_index + 1)
                continue
            if key in (curses.KEY_LEFT, ord("h"), ord("k")):
                self.playing = False
                self.frame_index = max(0, self.frame_index - 1)
                continue
            if key == curses.KEY_NPAGE:
                self.playing = False
                self.frame_index = min(len(self.trace.frames) - 1, self.frame_index + 10)
                continue
            if key == curses.KEY_PPAGE:
                self.playing = False
                self.frame_index = max(0, self.frame_index - 10)
                continue
            if key in (ord("g"), curses.KEY_HOME):
                self.playing = False
                self.frame_index = 0
                continue
            if key in (ord("G"), curses.KEY_END):
                self.playing = False
                self.frame_index = len(self.trace.frames) - 1
                continue
            if key == curses.KEY_RESIZE:
                continue

            self.playing = False
            self.status = f"Неизвестная клавиша: {key}"

    def _draw(self, stdscr: curses.window) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if height < 18 or width < 80:
            _safe_addnstr(
                stdscr,
                0,
                0,
                "Окно слишком маленькое для visualizer. Увеличьте терминал.",
                width - 1,
                curses.A_BOLD,
            )
            stdscr.refresh()
            return

        frame = self.trace.frames[self.frame_index]
        event = frame.event
        run = self.trace.run_result

        header = (
            "DSSim Visualizer: "
            f"{self.trace.config.algorithm.value} | "
            f"{self.trace.topology.kind} | "
            f"кадр {self.frame_index + 1}/{len(self.trace.frames)} | "
            f"t={frame.time}ms"
        )
        _safe_addnstr(stdscr, 0, 0, header, width - 1, curses.A_BOLD)
        _safe_addnstr(stdscr, 1, 0, self.status, width - 1)

        summary = (
            f"coverage={frame.informed_count}/{run.target_count} | "
            f"sent={run.messages_sent} | delivered={run.messages_delivered} | "
            f"lost={run.messages_lost} | dup={run.messages_duplicated} | "
            f"blocked_links={frame.blocked_link_count}"
        )
        _safe_addnstr(stdscr, 2, 0, summary, width - 1)

        event_line = "Событие: " + (event.summary if event is not None else "Исходное состояние")
        _safe_addnstr(stdscr, 3, 0, event_line, width - 1, curses.A_REVERSE)

        left_width = max(34, width // 2)
        right_x = min(width - 1, left_width + 2)
        panel_height = max(3, height - 12)

        _safe_addnstr(stdscr, 5, 0, "Узлы", left_width - 1, curses.A_BOLD)
        _safe_addnstr(stdscr, 5, right_x, "Каналы", width - right_x - 1, curses.A_BOLD)

        for row_offset, line in enumerate(
            self._render_nodes(frame.node_states, event, panel_height),
            start=6,
        ):
            _safe_addnstr(stdscr, row_offset, 0, line, left_width - 1)

        for row_offset, line in enumerate(
            self._render_links(frame.link_states, event, panel_height),
            start=6,
        ):
            _safe_addnstr(stdscr, row_offset, right_x, line, width - right_x - 1)

        log_start = height - 5
        _safe_addnstr(stdscr, log_start, 0, "Лента событий", width - 1, curses.A_BOLD)

        for row_offset, line in enumerate(
            self._render_event_log(),
            start=log_start + 1,
        ):
            _safe_addnstr(stdscr, row_offset, 0, line, width - 1)

        stdscr.refresh()

    def _render_nodes(
        self,
        node_states: tuple[DisseminationTraceNodeState, ...],
        event: DisseminationTraceEvent | None,
        max_lines: int,
    ) -> list[str]:
        lines: list[str] = []

        for node_state in node_states[:max_lines]:
            informed_marker = "*" if node_state.informed_at is not None else " "
            current_marker = ">" if event is not None and event.node_id == node_state.node_id else " "
            lines.append(
                f"{current_marker}{informed_marker} "
                f"{node_state.node_id:<10} "
                f"{_status_label(node_state.status):<9} "
                f"inf={_format_optional_int(node_state.informed_at):>3} "
                f"in={node_state.inbox_size:<2} "
                f"s/r/p={node_state.messages_sent}/{node_state.messages_received}/{node_state.messages_processed}"
            )

        return lines

    def _render_links(
        self,
        link_states: tuple[DisseminationTraceLinkState, ...],
        event: DisseminationTraceEvent | None,
        max_lines: int,
    ) -> list[str]:
        lines: list[str] = []

        for link_state in link_states[:max_lines]:
            highlighted = (
                event is not None
                and event.source_id == link_state.source_id
                and event.target_id == link_state.target_id
            )
            marker = ">" if highlighted else " "
            status = "up" if link_state.is_available else "down"
            lines.append(
                f"{marker} {link_state.source_id:<10} -> {link_state.target_id:<10} {status}"
            )

        return lines

    def _render_event_log(self) -> list[str]:
        start = max(0, self.frame_index - 3)
        end = min(len(self.trace.frames), start + 4)
        lines: list[str] = []

        for frame in self.trace.frames[start:end]:
            marker = ">" if frame.index == self.frame_index else " "
            event_summary = (
                frame.event.summary
                if frame.event is not None
                else "Исходное состояние"
            )
            lines.append(f"{marker} [{frame.time:>4}ms] {event_summary}")

        return lines


def launch_visualization(config: DisseminationStudyConfig) -> None:
    trace = run_dissemination_trace(config)

    try:
        curses.wrapper(lambda stdscr: SimulationVisualizerApp(trace).run(stdscr))
    except curses.error as error:
        raise RuntimeError(
            "Не удалось запустить visualizer: нужен совместимый интерактивный терминал."
        ) from error


def _safe_addnstr(
    stdscr: curses.window,
    y: int,
    x: int,
    text: str,
    max_length: int,
    attr: int = 0,
) -> None:
    if max_length <= 0:
        return

    try:
        stdscr.addnstr(y, x, text, max_length, attr)
    except curses.error:
        pass


def _format_optional_int(value: int | None) -> str:
    return "-" if value is None else str(value)


def _status_label(status: str) -> str:
    labels = {
        "active": "active",
        "failed": "failed",
        "isolated": "isolated",
        "stopped": "stopped",
    }
    return labels.get(status, status)
