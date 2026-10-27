"""Existing-node edits and explicit cinematic preview controls, inside Tools."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QTreeWidget, QTreeWidgetItem, QSpinBox, QDoubleSpinBox, QPushButton)

from src.core.cinematics import CinematicTimeline, node_events
from src.core.objects import LevelObject
from src.core.parameter_labels import ANIMATION_PARAMETERS

# Friendly labels backed by the runtime consumers; storage keys stay unchanged.
_FIELD_ORDER = ('animationStartDelay', 'nodeSpeed', 'pauseFrameCount', 'unk2D', 'rotateType', 'goToNode', 'y_rotation', 'x_rotation', 'z_rotation', 'scale', 'objAnimIndex', 'objAnimSpeed', 'objAnimLoopType', 'unk16', 'actorIndex', 'order', 'channel', 'nextAnim', 'unk15', 'unk2A', 'messageId', 'unk1F', 'unk1E', 'specialHide')
FIELDS: tuple[tuple[str, str, str], ...] = tuple(
    (key, ANIMATION_PARAMETERS[key].label, ANIMATION_PARAMETERS[key].description)
    for key in (*_FIELD_ORDER, *(key for key in ANIMATION_PARAMETERS if key not in _FIELD_ORDER))
)


class CinematicPanel(QWidget):
    node_selected = Signal(object, bool)
    parameter_changed = Signal(object, str, object)
    time_requested = Signal(float)
    duration_changed = Signal(float)
    camera_requested = Signal(int)
    paths_changed = Signal(bool)
    motion_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.timelines: tuple[CinematicTimeline, ...] = ()
        self.node: LevelObject | None = None
        self.editing = False
        self.seconds = 0.
        self._refreshing = False
        self._syncing_value = False
        self._drafts: dict[tuple[tuple[int, int], str], int] = {}
        layout = QVBoxLayout(self)
        self.track = QComboBox(self)
        self.track.setAccessibleName('Cinematic track')
        self.track.currentIndexChanged.connect(self._track_changed)
        layout.addWidget(self.track)
        options = QHBoxLayout()
        self.paths = QCheckBox('Draw paths', self)
        self.paths.setToolTip('Pink: cameras. Green: actors. Node markers remain selectable through terrain.')
        self.paths.toggled.connect(self.paths_changed)
        self.motion = QCheckBox('Move actors', self)
        self.motion.setChecked(True)
        self.motion.toggled.connect(self.motion_changed)
        options.addWidget(self.paths); options.addWidget(self.motion)
        layout.addLayout(options)
        self.camera = QCheckBox('View through selected camera (Esc exits)', self)
        self.camera.toggled.connect(self._camera_changed)
        layout.addWidget(self.camera)
        row = QHBoxLayout()
        self.time = QDoubleSpinBox(self)
        self.time.setDecimals(3); self.time.setRange(0, 30); self.time.setSuffix(' s')
        self.time.setSingleStep(1/60)
        self.time.setAccessibleName('Cinematic preview seconds')
        self.time.valueChanged.connect(self.time_requested)
        row.addWidget(QLabel('Time', self)); row.addWidget(self.time)
        self.duration = QSpinBox(self)
        self.duration.setRange(10, 300); self.duration.setValue(30); self.duration.setSuffix(' s')
        self.duration.setAccessibleName('Cinematic preview duration')
        self.duration.valueChanged.connect(self._duration_changed)
        row.addWidget(QLabel('Range', self)); row.addWidget(self.duration)
        layout.addLayout(row)
        self.nodes = QTreeWidget(self)
        self.nodes.setHeaderLabels(['Node / map:entry', 'First arrival', 'Events (requests only)'])
        self.nodes.setColumnWidth(0, 120); self.nodes.setColumnWidth(1, 85)
        self.nodes.setAccessibleName('Cinematic nodes and event markers')
        self.nodes.currentItemChanged.connect(self._node_changed)
        self.nodes.itemDoubleClicked.connect(lambda item, _: self.node_selected.emit(item.data(0, Qt.ItemDataRole.UserRole), True))
        layout.addWidget(self.nodes, 2)
        row = QHBoxLayout()
        jump = QPushButton('Find node time', self)
        jump.setToolTip('Calculate first arrivals within Range and scrub to the selected node. Unreachable waits stay marked.')
        jump.clicked.connect(self._jump)
        row.addWidget(jump)
        focus = QPushButton('Focus stored node', self)
        focus.clicked.connect(lambda: self.node_selected.emit(self.node.key, True) if self.node else None)
        row.addWidget(focus)
        layout.addLayout(row)
        self.field = QComboBox(self)
        for key, label, hint in FIELDS:
            self.field.addItem(label, key)
            self.field.setItemData(self.field.count()-1, hint, Qt.ItemDataRole.ToolTipRole)
        self.field.setAccessibleName('Cinematic node field')
        self.field.currentIndexChanged.connect(self._field_changed)
        layout.addWidget(self.field)
        row = QHBoxLayout()
        self.value = QSpinBox(self)
        self.value.setAccessibleName('Cinematic node field value')
        self.apply = QPushButton('Apply to node', self)
        self.apply.clicked.connect(self._apply)
        row.addWidget(self.value); row.addWidget(self.apply)
        self.value.valueChanged.connect(self._value_changed)
        layout.addLayout(row)
        self.hint = QLabel(self); self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.feedback = QLabel(self); self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.notes = QLabel('Choose a scene above. Play/scrub is preview-only. Node edits use existing undo, project save and ROM export.', self)
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.notes)
        self.set_tracks((), False)

    def set_tracks(self, timelines: tuple[CinematicTimeline, ...], editing: bool) -> None:
        self._refreshing = True
        owner = self.timeline.track.owner if self.timeline else -1
        node_key = self.node.key if self.node else None
        self.timelines, self.editing = timelines, editing
        active = {node.key for timeline in timelines for node in timeline.track.nodes}
        self._drafts = {key: value for key, value in self._drafts.items() if key[0] in active}
        self.track.blockSignals(True)
        self.track.clear()
        for timeline in timelines:
            self.track.addItem(f'{timeline.track.label} · scene {timeline.track.channel}', timeline.track.owner)
        selected = self.track.findData(owner)
        self.track.setCurrentIndex(max(0, selected) if timelines else -1)
        self.track.blockSignals(False)
        self._track_changed()
        if node_key:
            self.select_node(node_key)
        self._refreshing = False

    @property
    def timeline(self) -> CinematicTimeline | None:
        index = self.track.currentIndex()
        return self.timelines[index] if 0 <= index < len(self.timelines) else None

    def _track_changed(self) -> None:
        self.camera.setChecked(False)
        timeline = self.timeline
        self.nodes.blockSignals(True); self.nodes.clear()
        if timeline:
            for ordinal, node in enumerate(timeline.track.nodes):
                events = '; '.join(node_events(node)) or '—'
                item = QTreeWidgetItem([f'{ordinal} · {node.map_id}:{node.index}', '—', events])
                item.setData(0, Qt.ItemDataRole.UserRole, node.key)
                item.setToolTip(2, events)
                self.nodes.addTopLevelItem(item)
            self.nodes.setCurrentItem(self.nodes.topLevelItem(0))
        self.nodes.blockSignals(False)
        self._node_changed(self.nodes.currentItem(), None)
        self.camera.setEnabled(timeline is not None and timeline.track.camera)
        warnings = '\n'.join(timeline.track.warnings) if timeline else 'No tracks in this scene. Try another scene channel above.'
        loop = f'Loop → ordinal {timeline.track.loop}' if timeline and timeline.track.loop >= 0 else 'Open path'
        self.notes.setText(f'{loop}. NTSC 60 Hz reference preview.\n{warnings}\n'
            'Not simulated: live racer/camera substitutions, input and actor-release logic, scene chaining, audio/messages/particles, collision, game lighting and screen fades. Actor fades use visibility endpoints.')
        self.set_time(self.seconds)

    def _node_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        key = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self.node = next((n for n in self.timeline.track.nodes if n.key == key), None) if self.timeline else None
        self._field_changed()
        if self.node and not self._refreshing:
            self.node_selected.emit(self.node.key, False)

    def select_node(self, key: tuple[int, int]) -> None:
        timeline_index = next((i for i, t in enumerate(self.timelines) if any(n.key == key for n in t.track.nodes)), -1)
        if timeline_index < 0:
            return
        if timeline_index != self.track.currentIndex():
            self.track.setCurrentIndex(timeline_index)
        for row in range(self.nodes.topLevelItemCount()):
            item = self.nodes.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                self.nodes.blockSignals(True); self.nodes.setCurrentItem(item); self.nodes.blockSignals(False)
                self.node = self.timeline.track.nodes[row]
                self._field_changed()
                break

    def _field_changed(self) -> None:
        key = self.field.currentData()
        parameter = next((p for p in self.node.parameters if p.name == key), None) if self.node else None
        self.value.setEnabled(parameter is not None and self.editing)
        self.apply.setEnabled(parameter is not None and self.editing)
        if parameter:
            draft_key = self.node.key, str(key)
            if self._drafts.get(draft_key) == int(parameter.value):
                self._drafts.pop(draft_key, None)
            self._syncing_value = True
            self.value.setRange(*{'b': (-128, 127), 'B': (0, 255), 'h': (-32768, 32767), 'H': (0, 65535)}[parameter.format])
            self.value.setValue(self._drafts.get(draft_key, int(parameter.value)))
            self._syncing_value = False
        self.hint.setText(next((hint for field, _, hint in FIELDS if field == key), ''))

    def _value_changed(self, value: int) -> None:
        if self._syncing_value or self.node is None:
            return
        key = str(self.field.currentData())
        draft_key = self.node.key, key
        if self.node.value(key) == value:
            self._drafts.pop(draft_key, None)
        else:
            self._drafts[draft_key] = value

    def clear_drafts(self) -> None:
        self._drafts.clear()

    def _apply(self) -> None:
        if self.node and self.editing and self.node.value(self.field.currentData()) != self.value.value():
            self.parameter_changed.emit(self.node.key, self.field.currentData(), self.value.value())

    def _camera_changed(self, checked: bool) -> None:
        self.camera_requested.emit(self.timeline.track.owner if checked and self.timeline else -1)

    def _duration_changed(self, value: int) -> None:
        self.time.setMaximum(value)
        self.duration_changed.emit(float(value))

    def set_time(self, seconds: float) -> None:
        self.seconds = seconds
        self.time.blockSignals(True); self.time.setValue(seconds); self.time.blockSignals(False)
        timeline = self.timeline
        if timeline is None:
            self.feedback.setText('No cinematic selected.')
            return
        pose = timeline.sample(seconds if self.motion.isChecked() else 0.)
        for row in range(self.nodes.topLevelItemCount()):
            tick = timeline.arrivals.get(row)
            self.nodes.topLevelItem(row).setText(1, f'{tick/60:.3f} s' if tick is not None else '—')
        self.feedback.setText(f'Node {pose.node} · {pose.status}\nXYZ ' + ', '.join(f'{v:.1f}' for v in pose.position))

    def _jump(self) -> None:
        if self.timeline is None or self.node is None:
            return
        ordinal = next(i for i, node in enumerate(self.timeline.track.nodes) if node.key == self.node.key)
        self.timeline.sample(float(self.duration.value()))
        tick = self.timeline.arrivals.get(ordinal)
        if tick is not None:
            self.time_requested.emit(tick/60)
        else:
            self.set_time(self.seconds)
            self.feedback.setText('This node is not reached within Range; inspect waits, speed, loop and scene events.')
