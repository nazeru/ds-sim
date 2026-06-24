from __future__ import annotations

import curses

from app.forms import (
    FIELD_DEFINITIONS,
    OPTIONAL_FIELD_KEYS,
    build_launch_config,
    default_form_state,
)
from app.launch import render_case_table
from app.use_cases import run_comparison


class TuiApp:
    def __init__(self) -> None:
        self.form = default_form_state()
        self.selected_index = 0
        self.form_scroll = 0
        self.result_scroll = 0
        self.result_lines: tuple[str, ...] = ()
        self.mode = "form"
        self.status = "Enter: редактировать | r: запуск | d: сброс | q: выход"

    def run(self, stdscr: curses.window) -> None:
        stdscr.keypad(True)
        curses.cbreak()
        curses.noecho()

        try:
            curses.curs_set(0)
        except curses.error:
            pass

        while True:
            if self.mode == "form":
                self._draw_form(stdscr)
                key = stdscr.getch()

                if key in (ord("q"), 27):
                    return
                if key in (curses.KEY_UP, ord("k")):
                    self.selected_index = max(0, self.selected_index - 1)
                    continue
                if key in (curses.KEY_DOWN, ord("j")):
                    self.selected_index = min(
                        len(FIELD_DEFINITIONS) - 1,
                        self.selected_index + 1,
                    )
                    continue
                if key in (10, 13, curses.KEY_ENTER):
                    self._edit_selected_field(stdscr)
                    continue
                if key == ord("d"):
                    self.form = default_form_state()
                    self.status = "Параметры сброшены к значениям по умолчанию."
                    continue
                if key == ord("r"):
                    self._run_simulation(stdscr)
                    continue
                if key == curses.KEY_RESIZE:
                    continue
                self.status = f"Неизвестная клавиша: {key}"
                continue

            self._draw_results(stdscr)
            key = stdscr.getch()

            if key in (ord("q"), 27):
                return
            if key == ord("b"):
                self.mode = "form"
                self.status = "Возврат к параметрам."
                continue
            if key == ord("r"):
                self.mode = "form"
                self._run_simulation(stdscr)
                continue
            if key in (curses.KEY_UP, ord("k")):
                self.result_scroll = max(0, self.result_scroll - 1)
                continue
            if key in (curses.KEY_DOWN, ord("j")):
                self.result_scroll = min(
                    max(0, len(self.result_lines) - 1),
                    self.result_scroll + 1,
                )
                continue
            if key == curses.KEY_NPAGE:
                self.result_scroll = min(
                    max(0, len(self.result_lines) - 1),
                    self.result_scroll + 10,
                )
                continue
            if key == curses.KEY_PPAGE:
                self.result_scroll = max(0, self.result_scroll - 10)
                continue
            if key == curses.KEY_RESIZE:
                continue
            self.status = f"Неизвестная клавиша: {key}"

    def _draw_form(self, stdscr: curses.window) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if height < 8 or width < 60:
            _safe_addnstr(
                stdscr,
                0,
                0,
                "Окно слишком маленькое для TUI. Увеличьте терминал.",
                width - 1,
                curses.A_BOLD,
            )
            stdscr.refresh()
            return

        _safe_addnstr(
            stdscr,
            0,
            0,
            "DSSim TUI: настройка запуска симуляции",
            width - 1,
            curses.A_BOLD,
        )
        _safe_addnstr(
            stdscr,
            1,
            0,
            "Стрелки/jk: навигация | Enter: редактировать | r: запуск | d: сброс | q: выход",
            width - 1,
        )

        visible_height = max(1, height - 5)

        if self.selected_index < self.form_scroll:
            self.form_scroll = self.selected_index
        elif self.selected_index >= self.form_scroll + visible_height:
            self.form_scroll = self.selected_index - visible_height + 1

        for screen_row, field_index in enumerate(
            range(
                self.form_scroll,
                min(len(FIELD_DEFINITIONS), self.form_scroll + visible_height),
            ),
            start=2,
        ):
            field = FIELD_DEFINITIONS[field_index]
            value = getattr(self.form, field.key)
            prefix = ">" if field_index == self.selected_index else " "
            line = f"{prefix} {field.label:<18} {value}"
            attr = curses.A_REVERSE if field_index == self.selected_index else 0
            _safe_addnstr(stdscr, screen_row, 0, line, width - 1, attr)

        selected_field = FIELD_DEFINITIONS[self.selected_index]
        _safe_addnstr(
            stdscr,
            height - 2,
            0,
            selected_field.help_text,
            width - 1,
            curses.A_DIM,
        )
        _safe_addnstr(stdscr, height - 1, 0, self.status, width - 1)
        stdscr.refresh()

    def _draw_results(self, stdscr: curses.window) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        _safe_addnstr(
            stdscr,
            0,
            0,
            "DSSim TUI: результаты симуляции",
            width - 1,
            curses.A_BOLD,
        )
        _safe_addnstr(
            stdscr,
            1,
            0,
            "Стрелки/jk: прокрутка | PgUp/PgDn: быстрее | b: назад | r: перезапуск | q: выход",
            width - 1,
        )

        visible_height = max(1, height - 4)
        max_scroll = max(0, len(self.result_lines) - visible_height)
        self.result_scroll = min(self.result_scroll, max_scroll)

        for screen_row, line in enumerate(
            self.result_lines[
                self.result_scroll:self.result_scroll + visible_height
            ],
            start=2,
        ):
            _safe_addnstr(stdscr, screen_row, 0, line, width - 1)

        footer = (
            f"Строки {self.result_scroll + 1}-"
            f"{min(len(self.result_lines), self.result_scroll + visible_height)}"
            f" из {len(self.result_lines)}"
        )
        _safe_addnstr(stdscr, height - 1, 0, footer, width - 1)
        stdscr.refresh()

    def _edit_selected_field(self, stdscr: curses.window) -> None:
        field = FIELD_DEFINITIONS[self.selected_index]
        current_value = getattr(self.form, field.key)
        new_value = _prompt_input(
            stdscr,
            f"{field.label} [{current_value}]",
        )

        if new_value is None:
            self.status = "Редактирование отменено."
            return

        if new_value.strip():
            setattr(self.form, field.key, new_value)
            self.status = f"Поле {field.label} обновлено."
        elif field.key in OPTIONAL_FIELD_KEYS:
            setattr(self.form, field.key, "")
            self.status = f"Поле {field.label} очищено."
        else:
            self.status = f"Поле {field.label} оставлено без изменений."

    def _run_simulation(self, stdscr: curses.window) -> None:
        self.status = "Выполняется симуляция..."
        self._draw_form(stdscr)

        try:
            result = run_comparison(
                build_launch_config(self.form),
                name="tui-comparison",
            )
        except ValueError as error:
            self.status = f"Ошибка конфигурации: {error}"
            return
        except Exception as error:
            self.status = f"Ошибка запуска: {error}"
            return

        result_data = result.to_dict()
        self.result_lines = render_case_table(result_data["cases"])
        self.result_scroll = 0
        self.mode = "results"
        self.status = f"Готово: {len(result_data['cases'])} кейсов."

def _prompt_input(
    stdscr: curses.window,
    prompt: str,
) -> str | None:
    height, width = stdscr.getmaxyx()
    line = f"{prompt}: "
    _safe_addnstr(stdscr, height - 1, 0, line, width - 1)
    stdscr.clrtoeol()
    stdscr.refresh()

    curses.echo()

    try:
        curses.curs_set(1)
    except curses.error:
        pass

    try:
        raw_value = stdscr.getstr(
            height - 1,
            min(len(line), max(0, width - 1)),
            max(1, width - len(line) - 1),
        )
    except KeyboardInterrupt:
        return None
    finally:
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    return raw_value.decode("utf-8")


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


def launch_tui() -> None:
    try:
        curses.wrapper(lambda stdscr: TuiApp().run(stdscr))
    except curses.error as error:
        raise RuntimeError(
            "Не удалось запустить TUI: нужен совместимый интерактивный терминал."
        ) from error
