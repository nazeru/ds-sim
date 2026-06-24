from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.playback import (
    PlaybackFrame,
    PlaybackTrace,
    prepare_static_playback,
    topology_links,
)
from app.use_cases import (
    DisseminationPlaybackSession,
    build_playback_session,
)
from src.dissemination import (
    DisseminationAlgorithm,
    DisseminationStudyConfig,
    DisseminationStudyResult,
    DisseminationTraceResult,
)
from src.node import NodeFailureModel
from src.topology import Topology, TopologyKind, list_topology_presets, load_topology


FRAME_TABLE_HEADERS = ("Кадр", "t, мс", "Категория", "Тип", "Описание")
RUN_TABLE_HEADERS = (
    "Run",
    "Seed",
    "Coverage",
    "Completion",
    "T50",
    "T90",
    "Sent",
    "Delivered",
    "Lost",
    "Dup",
)


def format_optional(value: int | float | None) -> str:
    if value is None:
        return "-"

    if isinstance(value, int):
        return str(value)

    return f"{value:.3f}"


def build_topology(
    node_ids: list[str],
    links: list[tuple[str, str]],
    *,
    kind: str,
) -> Topology:
    adjacency = {node_id: [] for node_id in node_ids}

    for source_id, target_id in links:
        if source_id not in adjacency or target_id not in adjacency:
            raise ValueError("Связь ссылается на отсутствующий узел")

        if target_id in adjacency[source_id]:
            raise ValueError(f"Дублирующаяся связь: {source_id} -> {target_id}")

        adjacency[source_id].append(target_id)

    return Topology(
        adjacency={
            node_id: tuple(neighbors)
            for node_id, neighbors in adjacency.items()
        },
        kind=kind,
    )


class GraphView(QGraphicsView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._zoom_level = 0
        self._topology_signature: tuple[tuple[str, tuple[str, ...]], ...] | None = None
        self._node_items: dict[str, object] = {}
        self._node_labels: dict[str, object] = {}
        self._node_footers: dict[str, object] = {}
        self._footer_centers: dict[str, tuple[float, float]] = {}
        self._link_items: dict[tuple[str, str], tuple[object, object]] = {}
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setBackgroundBrush(QColor("#0f172a"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMinimumHeight(360)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter
        )

    def load_playback(self, playback: PlaybackTrace) -> None:
        topology_changed = playback.topology_signature != self._topology_signature
        self._topology_signature = playback.topology_signature
        self._scene.clear()
        self._node_items.clear()
        self._node_labels.clear()
        self._node_footers.clear()
        self._footer_centers.clear()
        self._link_items.clear()
        self._scene.setSceneRect(
            0,
            0,
            playback.scene_width,
            playback.scene_height,
        )

        if not playback.nodes:
            item = self._scene.addText("Добавьте хотя бы один узел.")
            item.setDefaultTextColor(QColor("#e2e8f0"))
            item.setPos(24, 24)
            return

        for link in playback.links:
            line_item = self._scene.addLine(
                link.start_x,
                link.start_y,
                link.end_x,
                link.end_y,
            )
            polygon_item = self._scene.addPolygon(
                QPolygonF(
                    [
                        QPointF(link.end_x, link.end_y),
                        QPointF(link.arrow_x1, link.arrow_y1),
                        QPointF(link.arrow_x2, link.arrow_y2),
                    ]
                )
            )
            self._link_items[(link.source_id, link.target_id)] = (
                line_item,
                polygon_item,
            )

        for node in playback.nodes:
            ellipse = self._scene.addEllipse(
                node.center_x - node.radius,
                node.center_y - node.radius,
                node.radius * 2,
                node.radius * 2,
            )
            ellipse.setZValue(2)
            self._node_items[node.node_id] = ellipse

            if node.has_label:
                label = self._scene.addText(node.node_id)
                label.setDefaultTextColor(QColor("#f8fafc"))
                bounds = label.boundingRect()
                label.setPos(
                    node.label_x - bounds.width() / 2,
                    node.label_y - bounds.height() / 2,
                )
                label.setZValue(3)
                self._node_labels[node.node_id] = label

            if node.has_footer:
                footer = self._scene.addText("")
                footer.setDefaultTextColor(QColor("#94a3b8"))
                footer.setPos(node.footer_x, node.footer_y)
                footer.setZValue(1)
                self._node_footers[node.node_id] = footer
                self._footer_centers[node.node_id] = (
                    node.footer_x,
                    node.footer_y,
                )

        if topology_changed:
            self.fit_to_view()

    def apply_frame(self, frame: PlaybackFrame) -> None:
        for state in frame.link_states:
            items = self._link_items.get((state.source_id, state.target_id))
            if items is None:
                continue

            style = (
                Qt.PenStyle.DashLine
                if state.dashed
                else Qt.PenStyle.SolidLine
            )
            pen = QPen(QColor(state.color), state.width, style)
            line_item, polygon_item = items
            line_item.setPen(pen)
            polygon_item.setPen(pen)
            polygon_item.setBrush(QColor(state.color))

        for state in frame.node_states:
            item = self._node_items.get(state.node_id)
            if item is None:
                continue

            item.setBrush(QColor(state.fill_color))
            item.setPen(
                QPen(QColor(state.border_color), state.border_width)
            )

            label = self._node_labels.get(state.node_id)
            if label is not None:
                label.setVisible(state.label_visible)

            footer = self._node_footers.get(state.node_id)
            if footer is not None:
                footer.setPlainText(state.footer_text)
                bounds = footer.boundingRect()
                center_x, center_y = self._footer_centers[state.node_id]
                footer.setPos(center_x - bounds.width() / 2, center_y)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return

        super().wheelEvent(event)

    def zoom_in(self) -> None:
        self._apply_zoom(1.15)

    def zoom_out(self) -> None:
        self._apply_zoom(1 / 1.15)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom_level = 0

    def fit_to_view(self) -> None:
        self.resetTransform()
        self.fitInView(
            self._scene.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._zoom_level = 0

    def _apply_zoom(self, factor: float) -> None:
        next_zoom_level = self._zoom_level + (1 if factor > 1 else -1)

        if next_zoom_level < -8 or next_zoom_level > 20:
            return

        self.scale(factor, factor)
        self._zoom_level = next_zoom_level


class LinkDialog(QDialog):
    def __init__(
        self,
        node_ids: list[str],
        *,
        initial_source: str | None = None,
        initial_target: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Связь")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.source_combo = QComboBox(self)
        self.source_combo.addItems(node_ids)
        self.target_combo = QComboBox(self)
        self.target_combo.addItems(node_ids)
        self.bidirectional_box = QCheckBox("Сделать связь двунаправленной", self)

        if initial_source is not None:
            self.source_combo.setCurrentText(initial_source)

        if initial_target is not None:
            self.target_combo.setCurrentText(initial_target)

        form.addRow("Источник", self.source_combo)
        form.addRow("Цель", self.target_combo)
        layout.addLayout(form)
        layout.addWidget(self.bidirectional_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, bool]:
        return (
            self.source_combo.currentText().strip(),
            self.target_combo.currentText().strip(),
            self.bidirectional_box.isChecked(),
        )


class ResultsWindow(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Результаты симуляции")
        self.resize(1100, 820)

        layout = QVBoxLayout(self)

        self.summary_label = QLabel("Запустите симуляцию, чтобы увидеть агрегированные результаты.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "QLabel { background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 8px; }"
        )
        layout.addWidget(self.summary_label)

        charts_splitter = QSplitter(Qt.Orientation.Vertical, self)
        layout.addWidget(charts_splitter, 1)

        self.coverage_plot = pg.PlotWidget(self)
        self.completion_plot = pg.PlotWidget(self)
        self.message_plot = pg.PlotWidget(self)

        for plot in (self.coverage_plot, self.completion_plot, self.message_plot):
            plot.setBackground("#111827")
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.getAxis("left").setTextPen("#cbd5e1")
            plot.getAxis("bottom").setTextPen("#cbd5e1")
            plot.setLabel("bottom", "run")
            charts_splitter.addWidget(plot)

        self.coverage_plot.setTitle("Coverage по прогонам", color="#f8fafc")
        self.coverage_plot.setLabel("left", "coverage")
        self.completion_plot.setTitle("Completion time", color="#f8fafc")
        self.completion_plot.setLabel("left", "ms")
        self.message_plot.setTitle("Сообщения по прогонам: sent / delivered / lost", color="#f8fafc")
        self.message_plot.setLabel("left", "count")

        self.run_table = QTableWidget(0, len(RUN_TABLE_HEADERS), self)
        self.run_table.setHorizontalHeaderLabels(RUN_TABLE_HEADERS)
        self.run_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.run_table.setAlternatingRowColors(True)
        self.run_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.run_table, 1)

    def set_results(
        self,
        config: DisseminationStudyConfig,
        result: DisseminationStudyResult,
    ) -> None:
        metrics = result.metrics
        self.summary_label.setText(
            " | ".join(
                [
                    f"algorithm={config.algorithm.value}",
                    f"topology={config.topology.kind}",
                    f"runs={config.runs}",
                    f"success={metrics.success_rate:.2%}",
                    f"coverage={metrics.mean_coverage:.3f}",
                    f"completion={format_optional(metrics.mean_completion_time)}",
                    f"overhead={metrics.mean_message_overhead:.3f}",
                ]
            )
        )

        run_numbers = [run.run_index + 1 for run in result.runs]
        coverages = [run.coverage for run in result.runs]
        completion_points = [
            (run.run_index + 1, run.completion_time)
            for run in result.runs
            if run.completion_time is not None
        ]

        self.coverage_plot.clear()
        self.coverage_plot.plot(
            run_numbers,
            coverages,
            pen=pg.mkPen("#38bdf8", width=3),
            symbol="o",
            symbolBrush="#f8fafc",
        )

        self.completion_plot.clear()
        if completion_points:
            self.completion_plot.plot(
                [item[0] for item in completion_points],
                [item[1] for item in completion_points],
                pen=pg.mkPen("#f59e0b", width=3),
                symbol="o",
                symbolBrush="#fde68a",
            )

        self.message_plot.clear()
        self.message_plot.plot(
            run_numbers,
            [run.messages_sent for run in result.runs],
            pen=pg.mkPen("#60a5fa", width=3),
            symbol="o",
            symbolBrush="#60a5fa",
        )
        self.message_plot.plot(
            run_numbers,
            [run.messages_delivered for run in result.runs],
            pen=pg.mkPen("#22c55e", width=3),
            symbol="o",
            symbolBrush="#22c55e",
        )
        self.message_plot.plot(
            run_numbers,
            [run.messages_lost for run in result.runs],
            pen=pg.mkPen("#ef4444", width=3),
            symbol="o",
            symbolBrush="#ef4444",
        )

        self.run_table.setRowCount(len(result.runs))

        for row_index, run in enumerate(result.runs):
            values = (
                str(run.run_index),
                str(run.seed),
                f"{run.coverage:.3f}",
                format_optional(run.completion_time),
                format_optional(run.time_to_50_percent),
                format_optional(run.time_to_90_percent),
                str(run.messages_sent),
                str(run.messages_delivered),
                str(run.messages_lost),
                str(run.messages_duplicated),
            )
            for column_index, value in enumerate(values):
                self.run_table.setItem(row_index, column_index, QTableWidgetItem(value))


class SimulationWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, config: DisseminationStudyConfig) -> None:
        super().__init__()
        self._config = config

    @Slot()
    def run(self) -> None:
        try:
            session = build_playback_session(self._config)
        except Exception as error:
            self.failed.emit(str(error))
            return

        self.completed.emit(session)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DSSim Qt")
        self.resize(1580, 980)

        self._topology_kind = TopologyKind.MANUAL
        self._node_ids: list[str] = []
        self._links: list[tuple[str, str]] = []
        self._trace_result: DisseminationTraceResult | None = None
        self._study_result: DisseminationStudyResult | None = None
        self._playback_trace: PlaybackTrace | None = None
        self._frame_index = 0
        self._results_window: ResultsWindow | None = None
        self._simulation_thread: QThread | None = None
        self._simulation_worker: SimulationWorker | None = None

        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance_frame)

        self._build_ui()
        self._load_initial_topology()
        self._set_trace_controls_enabled(False)

    def _build_ui(self) -> None:
        self._build_toolbar()

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        layout.addWidget(splitter, 1)

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 1160])

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.statusBar().showMessage("Готово к настройке сценария.")

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Сценарий", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        run_action = QAction("Запустить", self)
        run_action.triggered.connect(self._run_simulation)
        toolbar.addAction(run_action)

        self.results_action = QAction("Результаты", self)
        self.results_action.setEnabled(False)
        self.results_action.triggered.connect(self._show_results_window)
        toolbar.addAction(self.results_action)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        self.run_button = QPushButton("Запустить симуляцию", panel)
        self.run_button.clicked.connect(self._run_simulation)
        self.run_button.setStyleSheet(
            "QPushButton { background: #0f766e; color: white; padding: 10px 14px; border-radius: 8px; font-weight: 600; }"
            "QPushButton:hover { background: #0d9488; }"
        )
        layout.addWidget(self.run_button)

        tabs = QTabWidget(panel)
        tabs.addTab(self._build_topology_tab(), "Топология")
        tabs.addTab(self._build_settings_tab(), "Параметры")
        layout.addWidget(tabs, 1)

        return panel

    def _build_topology_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        preset_box = QGroupBox("Пресет", tab)
        preset_layout = QHBoxLayout(preset_box)
        self.preset_combo = QComboBox(preset_box)
        self.preset_combo.addItems(list_topology_presets())
        self.load_preset_button = QPushButton("Загрузить", preset_box)
        self.load_preset_button.clicked.connect(self._load_selected_preset)
        preset_layout.addWidget(self.preset_combo, 1)
        preset_layout.addWidget(self.load_preset_button)
        layout.addWidget(preset_box)

        self.topology_summary_label = QLabel("", tab)
        self.topology_summary_label.setWordWrap(True)
        self.topology_summary_label.setStyleSheet(
            "QLabel { background: #e2e8f0; color: #0f172a; padding: 8px; border-radius: 6px; }"
        )
        layout.addWidget(self.topology_summary_label)

        nodes_box = QGroupBox("Узлы", tab)
        nodes_layout = QVBoxLayout(nodes_box)
        self.node_list = QListWidget(nodes_box)
        self.node_list.itemDoubleClicked.connect(self._rename_selected_node)
        nodes_layout.addWidget(self.node_list, 1)

        node_buttons = QHBoxLayout()
        add_node_button = QPushButton("Добавить", nodes_box)
        add_node_button.clicked.connect(self._add_node)
        rename_node_button = QPushButton("Переименовать", nodes_box)
        rename_node_button.clicked.connect(self._rename_selected_node)
        remove_node_button = QPushButton("Удалить", nodes_box)
        remove_node_button.clicked.connect(self._remove_selected_node)
        node_buttons.addWidget(add_node_button)
        node_buttons.addWidget(rename_node_button)
        node_buttons.addWidget(remove_node_button)
        nodes_layout.addLayout(node_buttons)
        layout.addWidget(nodes_box, 1)

        links_box = QGroupBox("Связи", tab)
        links_layout = QVBoxLayout(links_box)
        self.link_table = QTableWidget(0, 2, links_box)
        self.link_table.setHorizontalHeaderLabels(("Источник", "Цель"))
        self.link_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.link_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.link_table.setAlternatingRowColors(True)
        self.link_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.link_table.cellDoubleClicked.connect(self._edit_selected_link)
        links_layout.addWidget(self.link_table, 1)

        link_buttons = QHBoxLayout()
        add_link_button = QPushButton("Добавить", links_box)
        add_link_button.clicked.connect(self._add_link)
        edit_link_button = QPushButton("Редактировать", links_box)
        edit_link_button.clicked.connect(self._edit_selected_link)
        remove_link_button = QPushButton("Удалить", links_box)
        remove_link_button.clicked.connect(self._remove_selected_link)
        link_buttons.addWidget(add_link_button)
        link_buttons.addWidget(edit_link_button)
        link_buttons.addWidget(remove_link_button)
        links_layout.addLayout(link_buttons)
        layout.addWidget(links_box, 1)

        return tab

    def _build_settings_tab(self) -> QWidget:
        container = QWidget(self)
        container.setObjectName("settingsTab")
        layout = QVBoxLayout(container)

        scroll = QScrollArea(container)
        scroll.setObjectName("settingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll_content = QWidget(scroll)
        scroll_content.setObjectName("settingsScrollContent")
        form = QFormLayout(scroll_content)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.algorithm_combo = QComboBox(scroll_content)
        for algorithm in DisseminationAlgorithm:
            self.algorithm_combo.addItem(algorithm.value, algorithm)

        self.source_combo = QComboBox(scroll_content)
        self.runs_spin = self._build_spinbox(1, 1000, 20)
        self.seed_spin = self._build_spinbox(0, 2_000_000_000, 42)
        self.latency_spin = self._build_spinbox(0, 100_000, 10)
        self.jitter_spin = self._build_spinbox(0, 100_000, 40)
        self.loss_spin = self._build_double_spinbox(0.0, 1.0, 0.0)
        self.duplicate_spin = self._build_double_spinbox(0.0, 1.0, 0.0)
        self.reorder_spin = self._build_double_spinbox(0.0, 1.0, 0.0)
        self.failed_node_spin = self._build_spinbox(0, 1000, 0)
        self.failed_channel_spin = self._build_spinbox(0, 1000, 0)

        self.auto_ttl_box = QCheckBox("Автоматически", scroll_content)
        self.auto_ttl_box.setChecked(True)
        self.ttl_spin = self._build_spinbox(0, 1000, 3)
        self.auto_ttl_box.toggled.connect(self.ttl_spin.setDisabled)
        self.ttl_spin.setDisabled(True)

        self.unlimited_time_box = QCheckBox("Без лимита", scroll_content)
        self.unlimited_time_box.setChecked(True)
        self.max_time_spin = self._build_spinbox(0, 1_000_000, 1000)
        self.unlimited_time_box.toggled.connect(self.max_time_spin.setDisabled)
        self.max_time_spin.setDisabled(True)

        self.failure_model_combo = QComboBox(scroll_content)
        for model in NodeFailureModel:
            self.failure_model_combo.addItem(model.value, model)

        self.clock_offset_min_spin = self._build_spinbox(-100_000, 100_000, 0)
        self.clock_offset_max_spin = self._build_spinbox(-100_000, 100_000, 0)
        self.multicast_branch_spin = self._build_spinbox(1, 1000, 3)
        self.gossip_fanout_spin = self._build_spinbox(1, 1000, 3)
        self.gossip_rounds_spin = self._build_spinbox(1, 1000, 4)
        self.gossip_interval_spin = self._build_spinbox(0, 100_000, 10)

        form.addRow("Алгоритм", self.algorithm_combo)
        form.addRow("Источник", self.source_combo)
        form.addRow("Повторы runs", self.runs_spin)
        form.addRow("Seed", self.seed_spin)
        form.addRow("Latency, мс", self.latency_spin)
        form.addRow("Jitter, мс", self.jitter_spin)
        form.addRow("Loss probability", self.loss_spin)
        form.addRow("Duplicate probability", self.duplicate_spin)
        form.addRow("Reorder probability", self.reorder_spin)
        form.addRow("Failed nodes", self.failed_node_spin)
        form.addRow("Failed channels", self.failed_channel_spin)
        form.addRow("TTL hops", self._inline_widget(self.auto_ttl_box, self.ttl_spin))
        form.addRow(
            "Max simulation time",
            self._inline_widget(self.unlimited_time_box, self.max_time_spin),
        )
        form.addRow("Node failure model", self.failure_model_combo)
        form.addRow("Clock offset min, мс", self.clock_offset_min_spin)
        form.addRow("Clock offset max, мс", self.clock_offset_max_spin)
        form.addRow("Multicast branching", self.multicast_branch_spin)
        form.addRow("Gossip fanout", self.gossip_fanout_spin)
        form.addRow("Gossip rounds", self.gossip_rounds_spin)
        form.addRow("Gossip interval, мс", self.gossip_interval_spin)

        scroll_content.setLayout(form)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        for widget in (
            self.algorithm_combo,
            self.source_combo,
            self.runs_spin,
            self.seed_spin,
            self.latency_spin,
            self.jitter_spin,
            self.loss_spin,
            self.duplicate_spin,
            self.reorder_spin,
            self.failed_node_spin,
            self.failed_channel_spin,
            self.auto_ttl_box,
            self.ttl_spin,
            self.unlimited_time_box,
            self.max_time_spin,
            self.failure_model_combo,
            self.clock_offset_min_spin,
            self.clock_offset_max_spin,
            self.multicast_branch_spin,
            self.gossip_fanout_spin,
            self.gossip_rounds_spin,
            self.gossip_interval_spin,
        ):
            self._connect_dirty_signal(widget)

        return container

    def _build_right_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        self.graph_view = GraphView(panel)
        layout.addWidget(self.graph_view, 1)

        zoom_controls = QHBoxLayout()
        self.zoom_out_button = QPushButton("-", panel)
        self.zoom_out_button.clicked.connect(self.graph_view.zoom_out)
        self.zoom_reset_button = QPushButton("100%", panel)
        self.zoom_reset_button.clicked.connect(self.graph_view.reset_zoom)
        self.zoom_fit_button = QPushButton("Вписать", panel)
        self.zoom_fit_button.clicked.connect(self.graph_view.fit_to_view)
        self.zoom_in_button = QPushButton("+", panel)
        self.zoom_in_button.clicked.connect(self.graph_view.zoom_in)
        zoom_hint = QLabel("Ctrl+колесо мыши: zoom, drag: pan", panel)
        zoom_hint.setStyleSheet("QLabel { color: #475569; }")
        zoom_controls.addWidget(self.zoom_out_button)
        zoom_controls.addWidget(self.zoom_reset_button)
        zoom_controls.addWidget(self.zoom_fit_button)
        zoom_controls.addWidget(self.zoom_in_button)
        zoom_controls.addWidget(zoom_hint)
        zoom_controls.addStretch(1)
        layout.addLayout(zoom_controls)

        self.trace_header_label = QLabel("Симуляция еще не запускалась.", panel)
        self.trace_header_label.setWordWrap(True)
        self.trace_header_label.setStyleSheet(
            "QLabel { background: #111827; color: #e5e7eb; padding: 10px; border-radius: 8px; }"
        )
        layout.addWidget(self.trace_header_label)

        controls = QHBoxLayout()
        self.first_button = QPushButton("|<", panel)
        self.prev_button = QPushButton("<", panel)
        self.play_button = QPushButton("Play", panel)
        self.next_button = QPushButton(">", panel)
        self.last_button = QPushButton(">|", panel)
        self.speed_combo = QComboBox(panel)
        self.speed_combo.addItem("0.5x", 500)
        self.speed_combo.addItem("1x", 250)
        self.speed_combo.addItem("2x", 120)
        self.speed_combo.addItem("4x", 60)
        self.speed_combo.setCurrentIndex(1)

        self.first_button.clicked.connect(lambda: self._set_frame_index(0))
        self.prev_button.clicked.connect(lambda: self._set_frame_index(self._frame_index - 1))
        self.play_button.clicked.connect(self._toggle_playback)
        self.next_button.clicked.connect(lambda: self._set_frame_index(self._frame_index + 1))
        self.last_button.clicked.connect(self._jump_to_last_frame)

        controls.addWidget(self.first_button)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.last_button)
        controls.addWidget(QLabel("Скорость", panel))
        controls.addWidget(self.speed_combo)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.timeline_slider = QSlider(Qt.Orientation.Horizontal, panel)
        self.timeline_slider.valueChanged.connect(self._set_frame_index)
        layout.addWidget(self.timeline_slider)

        self.frame_stats_label = QLabel("Нет активного trace.", panel)
        self.frame_stats_label.setStyleSheet("QLabel { color: #334155; }")
        layout.addWidget(self.frame_stats_label)

        bottom_tabs = QTabWidget(panel)
        bottom_tabs.addTab(self._build_events_tab(), "События")
        bottom_tabs.addTab(self._build_run_summary_tab(), "Итог")
        layout.addWidget(bottom_tabs, 1)

        return panel

    def _build_events_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        self.frame_table = QTableWidget(0, len(FRAME_TABLE_HEADERS), tab)
        self.frame_table.setHorizontalHeaderLabels(FRAME_TABLE_HEADERS)
        self.frame_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.frame_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.frame_table.setAlternatingRowColors(True)
        self.frame_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.frame_table.itemSelectionChanged.connect(self._on_frame_selected_from_table)
        layout.addWidget(self.frame_table, 1)

        self.event_details = QPlainTextEdit(tab)
        self.event_details.setReadOnly(True)
        self.event_details.setPlaceholderText("Описание текущего шага и состояния узлов появится после запуска.")
        self.event_details.setMinimumHeight(180)
        layout.addWidget(self.event_details)

        return tab

    def _build_run_summary_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        self.run_summary = QPlainTextEdit(tab)
        self.run_summary.setReadOnly(True)
        self.run_summary.setPlaceholderText("Итоги запуска и агрегированные метрики будут показаны здесь.")
        layout.addWidget(self.run_summary, 1)

        self.open_results_button = QPushButton("Открыть окно результатов", tab)
        self.open_results_button.setEnabled(False)
        self.open_results_button.clicked.connect(self._show_results_window)
        layout.addWidget(self.open_results_button)

        return tab

    def _build_spinbox(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        widget = QSpinBox(self)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def _build_double_spinbox(
        self,
        minimum: float,
        maximum: float,
        value: float,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox(self)
        widget.setRange(minimum, maximum)
        widget.setDecimals(3)
        widget.setSingleStep(0.05)
        widget.setValue(value)
        return widget

    def _inline_widget(self, first: QWidget, second: QWidget) -> QWidget:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(first)
        layout.addWidget(second)
        return container

    def _connect_dirty_signal(self, widget: QWidget) -> None:
        if isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self._mark_dirty)
            return

        if isinstance(widget, QSpinBox | QDoubleSpinBox):
            widget.valueChanged.connect(self._mark_dirty)
            return

        if isinstance(widget, QCheckBox):
            widget.toggled.connect(self._mark_dirty)

    def _load_initial_topology(self) -> None:
        preset_names = list_topology_presets()
        preferred_name = "ring" if "ring" in preset_names else (preset_names[0] if preset_names else "")

        if preferred_name:
            self.preset_combo.setCurrentText(preferred_name)
            self._apply_topology(load_topology(preferred_name))
        else:
            self._node_ids = ["node-0", "node-1"]
            self._links = [("node-0", "node-1"), ("node-1", "node-0")]
            self._topology_kind = TopologyKind.MANUAL
            self._refresh_topology_editor()

    def _load_selected_preset(self) -> None:
        preset_name = self.preset_combo.currentText()

        if not preset_name:
            return

        self._apply_topology(load_topology(preset_name))
        self.statusBar().showMessage(f"Загружен пресет topology: {preset_name}")

    def _apply_topology(self, topology: Topology) -> None:
        self._node_ids = list(topology.node_ids)
        self._links = topology_links(topology)
        self._topology_kind = topology.kind
        self._refresh_topology_editor()
        self._mark_dirty()

    def _refresh_topology_editor(self) -> None:
        self.node_list.clear()
        self.node_list.addItems(self._node_ids)

        self.link_table.setRowCount(len(self._links))
        for row_index, (source_id, target_id) in enumerate(self._links):
            self.link_table.setItem(row_index, 0, QTableWidgetItem(source_id))
            self.link_table.setItem(row_index, 1, QTableWidgetItem(target_id))

        self._refresh_source_choices()
        self._refresh_failure_limits()
        self._render_editor_graph()
        self.topology_summary_label.setText(
            " | ".join(
                [
                    f"kind={self._topology_kind}",
                    f"nodes={len(self._node_ids)}",
                    f"links={len(self._links)}",
                ]
            )
        )

    def _refresh_source_choices(self) -> None:
        previous = self.source_combo.currentText()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItems(self._node_ids)

        if previous and previous in self._node_ids:
            self.source_combo.setCurrentText(previous)
        elif self._node_ids:
            self.source_combo.setCurrentIndex(0)

        self.source_combo.blockSignals(False)

    def _refresh_failure_limits(self) -> None:
        max_failed_nodes = max(0, len(self._node_ids) - 1)
        self.failed_node_spin.setMaximum(max_failed_nodes)
        self.failed_node_spin.setValue(min(self.failed_node_spin.value(), max_failed_nodes))

        max_failed_links = len(self._links)
        self.failed_channel_spin.setMaximum(max_failed_links)
        self.failed_channel_spin.setValue(
            min(self.failed_channel_spin.value(), max_failed_links)
        )

        max_ttl = max(1, len(self._node_ids) * 2 if self._node_ids else 1)
        self.ttl_spin.setMaximum(max_ttl)

    def _render_editor_graph(self) -> None:
        try:
            topology = self._current_topology()
        except ValueError:
            topology = build_topology(
                self._node_ids,
                [],
                kind=self._topology_kind,
            )
        playback = prepare_static_playback(
            topology,
            source_id=self.source_combo.currentText() or None,
        )
        self.graph_view.load_playback(playback)
        self.graph_view.apply_frame(playback.frames[0])

    def _current_topology(self) -> Topology:
        return build_topology(
            self._node_ids,
            self._links,
            kind=self._topology_kind,
        )

    def _add_node(self) -> None:
        node_id, accepted = QInputDialog.getText(
            self,
            "Новый узел",
            "ID узла:",
            QLineEdit.EchoMode.Normal,
            f"node-{len(self._node_ids)}",
        )

        if not accepted:
            return

        node_id = node_id.strip()

        if not node_id:
            self._show_error("ID узла не может быть пустым.")
            return

        if node_id in self._node_ids:
            self._show_error(f"Узел {node_id!r} уже существует.")
            return

        self._node_ids.append(node_id)
        self._topology_kind = TopologyKind.MANUAL
        self._refresh_topology_editor()
        self._mark_dirty()

    def _rename_selected_node(self) -> None:
        current_item = self.node_list.currentItem()

        if current_item is None:
            self._show_error("Сначала выберите узел.")
            return

        old_node_id = current_item.text()
        new_node_id, accepted = QInputDialog.getText(
            self,
            "Переименование узла",
            "Новый ID:",
            QLineEdit.EchoMode.Normal,
            old_node_id,
        )

        if not accepted:
            return

        new_node_id = new_node_id.strip()

        if not new_node_id:
            self._show_error("ID узла не может быть пустым.")
            return

        if new_node_id != old_node_id and new_node_id in self._node_ids:
            self._show_error(f"Узел {new_node_id!r} уже существует.")
            return

        self._node_ids = [
            new_node_id if node_id == old_node_id else node_id
            for node_id in self._node_ids
        ]
        self._links = [
            (
                new_node_id if source_id == old_node_id else source_id,
                new_node_id if target_id == old_node_id else target_id,
            )
            for source_id, target_id in self._links
        ]
        self._topology_kind = TopologyKind.MANUAL
        self._refresh_topology_editor()
        self._mark_dirty()

    def _remove_selected_node(self) -> None:
        current_item = self.node_list.currentItem()

        if current_item is None:
            self._show_error("Сначала выберите узел.")
            return

        node_id = current_item.text()
        self._node_ids = [item for item in self._node_ids if item != node_id]
        self._links = [
            (source_id, target_id)
            for source_id, target_id in self._links
            if source_id != node_id and target_id != node_id
        ]
        self._topology_kind = TopologyKind.MANUAL
        self._refresh_topology_editor()
        self._mark_dirty()

    def _selected_link(self) -> tuple[int, tuple[str, str]] | None:
        selection = self.link_table.selectionModel().selectedRows()

        if not selection:
            return None

        row_index = selection[0].row()
        return row_index, self._links[row_index]

    def _add_link(self) -> None:
        if len(self._node_ids) < 2:
            self._show_error("Для связи нужно как минимум два узла.")
            return

        dialog = LinkDialog(self._node_ids, parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        source_id, target_id, bidirectional = dialog.values()

        try:
            self._insert_link(source_id, target_id)

            if bidirectional:
                self._insert_link(target_id, source_id)
        except ValueError as error:
            self._show_error(str(error))
            return

        self._topology_kind = TopologyKind.MANUAL
        self._refresh_topology_editor()
        self._mark_dirty()

    def _edit_selected_link(self) -> None:
        selected = self._selected_link()

        if selected is None:
            self._show_error("Сначала выберите связь.")
            return

        row_index, (source_id, target_id) = selected
        dialog = LinkDialog(
            self._node_ids,
            initial_source=source_id,
            initial_target=target_id,
            parent=self,
        )
        dialog.bidirectional_box.hide()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_source_id, new_target_id, _ = dialog.values()

        if new_source_id == new_target_id:
            self._show_error("Связь узла с самим собой запрещена.")
            return

        if (
            (new_source_id, new_target_id) in self._links
            and (new_source_id, new_target_id) != (source_id, target_id)
        ):
            self._show_error("Такая связь уже существует.")
            return

        self._links[row_index] = (new_source_id, new_target_id)
        self._topology_kind = TopologyKind.MANUAL
        self._refresh_topology_editor()
        self._mark_dirty()

    def _remove_selected_link(self) -> None:
        selected = self._selected_link()

        if selected is None:
            self._show_error("Сначала выберите связь.")
            return

        row_index, _ = selected
        del self._links[row_index]
        self._topology_kind = TopologyKind.MANUAL
        self._refresh_topology_editor()
        self._mark_dirty()

    def _insert_link(self, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            raise ValueError("Связь узла с самим собой запрещена.")

        if (source_id, target_id) in self._links:
            raise ValueError(f"Связь {source_id} -> {target_id} уже существует.")

        self._links.append((source_id, target_id))

    def _build_config(self) -> DisseminationStudyConfig:
        topology = self._current_topology()
        source_id = self.source_combo.currentText().strip()

        if not source_id:
            raise ValueError("Нужно выбрать source_id.")

        return DisseminationStudyConfig(
            algorithm=DisseminationAlgorithm(
                str(self.algorithm_combo.currentData())
            ),
            topology=topology,
            runs=self.runs_spin.value(),
            seed=self.seed_spin.value(),
            source_id=source_id,
            latency_ms=self.latency_spin.value(),
            jitter_ms=self.jitter_spin.value(),
            loss_probability=self.loss_spin.value(),
            duplicate_probability=self.duplicate_spin.value(),
            reorder_probability=self.reorder_spin.value(),
            message_ttl_hops=(
                None if self.auto_ttl_box.isChecked() else self.ttl_spin.value()
            ),
            clock_offset_min_ms=self.clock_offset_min_spin.value(),
            clock_offset_max_ms=self.clock_offset_max_spin.value(),
            node_failure_model=NodeFailureModel(
                str(self.failure_model_combo.currentData())
            ),
            failed_node_count=self.failed_node_spin.value(),
            failed_channel_count=self.failed_channel_spin.value(),
            multicast_branching_factor=self.multicast_branch_spin.value(),
            gossip_fanout=self.gossip_fanout_spin.value(),
            gossip_rounds=self.gossip_rounds_spin.value(),
            gossip_interval_ms=self.gossip_interval_spin.value(),
            max_simulation_time=(
                None if self.unlimited_time_box.isChecked() else self.max_time_spin.value()
            ),
        )

    def _run_simulation(self) -> None:
        if self._simulation_thread is not None:
            return

        self._stop_playback()

        try:
            config = self._build_config()
        except ValueError as error:
            self._show_error(str(error))
            return

        self.run_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage(
            "Вычисляется полный trace и подготавливаются кадры..."
        )

        thread = QThread(self)
        worker = SimulationWorker(config)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_simulation_ready)
        worker.failed.connect(self._on_simulation_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_simulation_finished)

        self._simulation_thread = thread
        self._simulation_worker = worker
        thread.start()

    @Slot(object)
    def _on_simulation_ready(self, session_object: object) -> None:
        if not isinstance(session_object, DisseminationPlaybackSession):
            self._show_error("Получен некорректный результат симуляции")
            return

        session = session_object
        trace_result = session.trace_result
        study_result = session.study_result
        self._trace_result = trace_result
        self._study_result = study_result
        self._playback_trace = session.playback_trace
        self.results_action.setEnabled(True)
        self.open_results_button.setEnabled(True)

        self.graph_view.load_playback(session.playback_trace)
        self._populate_frames(session.playback_trace)
        self._update_run_summary(
            trace_result.config,
            trace_result,
            study_result,
        )
        self._set_trace_controls_enabled(True)
        self._set_frame_index(0)
        self.statusBar().showMessage(
            f"Готово: {len(trace_result.frames)} кадров, "
            f"{len(trace_result.events)} событий."
        )
        self._show_results_window()

    @Slot(str)
    def _on_simulation_failed(self, message: str) -> None:
        self._show_error(message)
        self.statusBar().showMessage("Не удалось рассчитать trace.")

    @Slot()
    def _on_simulation_finished(self) -> None:
        QApplication.restoreOverrideCursor()
        self.run_button.setEnabled(True)
        self._simulation_worker = None
        self._simulation_thread = None

    def _populate_frames(self, playback_trace: PlaybackTrace) -> None:
        self.timeline_slider.blockSignals(True)
        self.timeline_slider.setRange(0, len(playback_trace.frames) - 1)
        self.timeline_slider.setValue(0)
        self.timeline_slider.blockSignals(False)

        self.frame_table.blockSignals(True)
        self.frame_table.setRowCount(len(playback_trace.frames))

        for row_index, frame in enumerate(playback_trace.frames):
            category = frame.category
            event_type = frame.event_type
            summary = frame.summary
            values = (
                str(frame.index),
                str(frame.time),
                category,
                event_type,
                summary,
            )

            for column_index, value in enumerate(values):
                self.frame_table.setItem(row_index, column_index, QTableWidgetItem(value))

        self.frame_table.blockSignals(False)

    def _update_run_summary(
        self,
        config: DisseminationStudyConfig,
        trace_result: DisseminationTraceResult,
        study_result: DisseminationStudyResult,
    ) -> None:
        run = trace_result.run_result
        metrics = study_result.metrics
        self.run_summary.setPlainText(
            "\n".join(
                [
                    "Текущий сценарий",
                    f"algorithm: {config.algorithm.value}",
                    f"topology: {config.topology.kind}",
                    f"source_id: {config.source_id}",
                    f"nodes: {len(config.topology.node_ids)}",
                    f"links: {len(topology_links(config.topology))}",
                    f"seed: {config.seed}",
                    "",
                    "Первый прогон / trace",
                    f"informed: {run.informed_count}/{run.target_count}",
                    f"coverage: {run.coverage:.3f}",
                    f"completion_time: {format_optional(run.completion_time)}",
                    f"time_to_50_percent: {format_optional(run.time_to_50_percent)}",
                    f"time_to_90_percent: {format_optional(run.time_to_90_percent)}",
                    f"messages_sent: {run.messages_sent}",
                    f"messages_delivered: {run.messages_delivered}",
                    f"messages_lost: {run.messages_lost}",
                    f"messages_duplicated: {run.messages_duplicated}",
                    "",
                    "Агрегированные результаты",
                    f"runs: {config.runs}",
                    f"success_rate: {metrics.success_rate:.2%}",
                    f"mean_coverage: {metrics.mean_coverage:.3f}",
                    f"mean_completion_time: {format_optional(metrics.mean_completion_time)}",
                    f"mean_messages_sent: {metrics.mean_messages_sent:.2f}",
                    f"mean_messages_delivered: {metrics.mean_messages_delivered:.2f}",
                    f"mean_messages_lost: {metrics.mean_messages_lost:.2f}",
                    f"mean_message_overhead: {metrics.mean_message_overhead:.3f}",
                ]
            )
        )

    def _set_trace_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.first_button,
            self.prev_button,
            self.play_button,
            self.next_button,
            self.last_button,
            self.speed_combo,
            self.timeline_slider,
            self.frame_table,
        ):
            widget.setEnabled(enabled)

    def _set_frame_index(self, index: int) -> None:
        if self._playback_trace is None:
            return

        bounded_index = max(
            0,
            min(index, len(self._playback_trace.frames) - 1),
        )
        self._frame_index = bounded_index
        frame = self._playback_trace.frames[bounded_index]

        if self.timeline_slider.value() != bounded_index:
            self.timeline_slider.blockSignals(True)
            self.timeline_slider.setValue(bounded_index)
            self.timeline_slider.blockSignals(False)

        self.graph_view.apply_frame(frame)
        self.trace_header_label.setText(frame.header_text)
        self.frame_stats_label.setText(
            f"{frame.stats_text} | total_frames={len(self._playback_trace.frames)}"
        )
        self.event_details.setPlainText(frame.details_text)
        self._select_frame_row(bounded_index)

    def _select_frame_row(self, row_index: int) -> None:
        self.frame_table.blockSignals(True)
        self.frame_table.clearSelection()
        self.frame_table.selectRow(row_index)
        self.frame_table.scrollToItem(
            self.frame_table.item(row_index, 0),
            QAbstractItemView.ScrollHint.PositionAtCenter,
        )
        self.frame_table.blockSignals(False)

    def _on_frame_selected_from_table(self) -> None:
        selection = self.frame_table.selectionModel().selectedRows()

        if not selection:
            return

        self._set_frame_index(selection[0].row())

    def _toggle_playback(self) -> None:
        if self._playback_trace is None:
            return

        if self._play_timer.isActive():
            self._stop_playback()
            return

        if self._frame_index >= len(self._playback_trace.frames) - 1:
            self._set_frame_index(0)

        self.play_button.setText("Pause")
        self._play_timer.start(int(self.speed_combo.currentData()))

    def _stop_playback(self) -> None:
        self._play_timer.stop()
        self.play_button.setText("Play")

    def _advance_frame(self) -> None:
        if self._playback_trace is None:
            self._stop_playback()
            return

        if self._frame_index >= len(self._playback_trace.frames) - 1:
            self._stop_playback()
            return

        self._set_frame_index(self._frame_index + 1)

    def _jump_to_last_frame(self) -> None:
        if self._playback_trace is None:
            return

        self._set_frame_index(len(self._playback_trace.frames) - 1)

    def _show_results_window(self) -> None:
        if self._study_result is None or self._trace_result is None:
            return

        if self._results_window is None:
            self._results_window = ResultsWindow(self)

        self._results_window.set_results(self._trace_result.config, self._study_result)
        self._results_window.show()
        self._results_window.raise_()
        self._results_window.activateWindow()

    def _mark_dirty(self) -> None:
        self.statusBar().showMessage(
            "Конфигурация изменена. Перезапустите симуляцию, чтобы обновить trace и результаты."
        )
        self._render_editor_graph()

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Ошибка", message)


def launch_qt() -> None:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("DSSim Qt")
    app.setStyleSheet(
        """
        QMainWindow, QDialog { background: #f8fafc; color: #0f172a; }
        QWidget { color: #0f172a; }
        QGroupBox {
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            font-weight: 600;
            color: #0f172a;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QWidget#settingsTab,
        QScrollArea#settingsScrollArea,
        QWidget#settingsScrollContent,
        QScrollArea#settingsScrollArea > QWidget > QWidget {
            background: white;
            color: #0f172a;
        }
        QTabWidget::pane {
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            background: white;
        }
        QTabBar::tab {
            background: #e2e8f0;
            color: #0f172a;
            padding: 8px 12px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 2px;
        }
        QTabBar::tab:selected { background: #cbd5e1; }
        QTableWidget, QListWidget, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background: white;
            color: #0f172a;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 4px;
            selection-background-color: #cbd5e1;
            selection-color: #0f172a;
        }
        QTableWidget {
            alternate-background-color: #f1f5f9;
            gridline-color: #cbd5e1;
        }
        QTableWidget::item {
            background: #ffffff;
            color: #0f172a;
        }
        QTableWidget::item:alternate {
            background: #f1f5f9;
            color: #0f172a;
        }
        QTableWidget::item:selected {
            background: #cbd5e1;
            color: #0f172a;
        }
        QHeaderView::section {
            background: #e2e8f0;
            color: #0f172a;
            border: 1px solid #cbd5e1;
            padding: 6px;
        }
        QComboBox QAbstractItemView {
            background: white;
            color: #0f172a;
            selection-background-color: #cbd5e1;
            selection-color: #0f172a;
        }
        QLabel, QCheckBox {
            color: #0f172a;
        }
        QPushButton {
            background: #e2e8f0;
            color: #0f172a;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 6px 10px;
        }
        QPushButton:hover { background: #cbd5e1; }
        QToolBar { spacing: 8px; padding: 6px; border-bottom: 1px solid #cbd5e1; }
        """
    )
    pg.setConfigOptions(antialias=True, foreground="#cbd5e1")

    window = MainWindow()
    window.show()
    app.exec()
