"""Viewport, camera and artwork controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QLabel, QSlider, QToolBar, QWidget, QSizePolicy, QMenu, QToolButton
from src.core.special_art import PORTRAIT_NAMES


class EnvironmentToolbar(QToolBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__('Environment preview', parent)
        self.setObjectName('environmentToolbar')
        self.setMovable(False)
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)
        for name, label, checked, hint in (
            ('sky', 'Sky / background', True, 'Saved skybox and background; special sky uses its texture plane without color scripts'),
            ('fog', 'Saved fog', False, 'Saved N64 fog defaults in perspective view. Disable for unobscured editing; triggers are not simulated'),
            ('motion', 'Texture motion', True, 'Track flipbooks and placed texture-scroll controllers, driven by Play/scrub'),
            ('water', 'Water preview ≈', True, 'Saved wave settings on the stored shoreline. Camera/racer edge dampening and swells are omitted; disabled while editing materials'),
            ('gradient', 'Multiplayer gradient', False, 'Preview the saved multiplayer gradient instead of the single-player sky')):
            action = self.addAction(label); action.setCheckable(True); action.setChecked(checked); action.setToolTip(hint)
            setattr(self, name, action)
        self.summary = QLabel('ⓘ', self)
        self.summary.setAccessibleName('Environment preview information')
        self.set_summary('Preview only · Play/scrub controls motion')
        self.addWidget(self.summary)

    def set_summary(self, text: str) -> None:
        self.summary.setToolTip(text)
        self.summary.setAccessibleDescription(text)
        self.setToolTip(text)


class SpecialArtworkToolbar(QToolBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__('Special artwork', parent)
        self.setObjectName('specialArtworkToolbar')
        self.setMovable(False)
        self.visible = self.addAction('Special art')
        self.visible.setCheckable(True)
        self.visible.setChecked(True)
        self.visible.setToolTip('Ground zipper decals, fish, butterflies and portrait samples; independent of gizmo filters')
        self.addWidget(QLabel(' Portrait sample ', self))
        self.portrait = QComboBox(self)
        self.portrait.setObjectName('portraitSample')
        self.portrait.setAccessibleName('Portrait sample character')
        self.portrait.addItem('Off — needs racers', -1)
        for index, name in enumerate(PORTRAIT_NAMES):
            self.portrait.addItem(name, index)
        self.portrait.setCurrentIndex(PORTRAIT_NAMES.index('Diddy') + 1)
        self.portrait.setToolTip('Preview the chosen character on all portrait slots.')
        self.addWidget(self.portrait)
        self.summary = QLabel('', self)
        self.addWidget(self.summary)
        self.summary.setToolTip('Play/scrub above previews animation')
        self.summary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.summary.setMaximumWidth(260)


class CameraToolbar(QToolBar):
    """Camera preferences stay available when objects or render layers change."""

    speed_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Camera controls", parent)
        self.setObjectName("cameraToolbar")
        self.setMovable(False)
        self.addWidget(QLabel("Camera speed  ", self))
        self.speed = QSlider(Qt.Orientation.Horizontal, self)
        self.speed.setObjectName("cameraSpeedSlider")
        self.speed.setAccessibleName("Camera movement speed")
        self.speed.setRange(1, 400)
        self.speed.setValue(100)
        self.speed.setPageStep(25)
        self.speed.setFixedWidth(180)
        self.speed.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.speed.setToolTip(
            "1–400% of normal whole-level movement speed. Shift gives a further 4× boost. "
            "Object selection, focus and Fit/Reset preserve this speed."
        )
        self.addWidget(self.speed)
        self.speed_value = QLabel(" 100%", self)
        self.speed_value.setMinimumWidth(60)
        self.addWidget(self.speed_value)
        self.speed.valueChanged.connect(self._speed_changed)
        self.addSeparator()
        self.addWidget(QLabel(" View ", self))
        self.view = QComboBox(self)
        self.view.setAccessibleName("Camera projection view")
        self.view.addItems(["Perspective", "Top", "Front", "Right"])
        self.addWidget(self.view)
        self.addWidget(QLabel(" Transform ", self))
        self.transform = QComboBox(self)
        self.transform.setAccessibleName("Object transform tool")
        self.transform.addItems(["Move", "Rotate", "Scale"])
        self.addWidget(self.transform)

    @Slot(int)
    def _speed_changed(self, percent: int) -> None:
        self.speed_value.setText(f" {percent}%")
        self.speed_changed.emit(percent)


class RenderToolbar(QToolBar):
    segment_selected = Signal(int)
    routes_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Render controls", parent)
        self.setObjectName("renderToolbar")
        self.setMovable(False)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.grid = self._toggle("Grid")
        self.grid.setToolTip('World-aligned working plane. Use the arrow for placement and automatic visibility.')
        self.grid_menu = QMenu('Working grid', self)
        self.grid_auto = self.grid_menu.addAction('Automatic visibility')
        self.grid_auto.setCheckable(True); self.grid_auto.setChecked(True)
        self.grid_auto.setToolTip('Show the grid in top/front/side views; hide it in perspective.')
        self.grid_follow = self.grid_menu.addAction('Follow selection height / depth')
        self.grid_follow.setCheckable(True); self.grid_follow.setChecked(True)
        self.grid_pick = self.grid_menu.addAction('Set plane from a track surface…')
        self.grid_reset = self.grid_menu.addAction('Reset working plane')
        self.grid.setMenu(self.grid_menu)
        grid_button = self.widgetForAction(self.grid)
        grid_button.setObjectName('workGridButton')
        grid_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        grid_button.setStyleSheet(
            'QToolButton#workGridButton { padding-right: 13px; }'
        )
        self.axes = self._toggle("Axes", checked=True)
        self.axes.setToolTip('Show the corner XYZ orientation indicator.')
        self.addSeparator()
        self.fit = self.addAction("Fit / Reset (F)")
        self.addSeparator()
        self.wireframe = self._toggle("Wireframe", requires_model=True)
        self.vertex_colors = self._toggle("Vertex Colors", checked=True, requires_model=True)
        self.bounds = self._toggle("Segment Bounds", requires_model=True)
        self.culling = self._toggle("Cull Backfaces", checked=True, requires_model=True)
        self.segments = QComboBox(self)
        self.segments.setObjectName("segmentSelector")
        self.segments.setAccessibleName("Select segment")
        self.segments.addItem("All segments", -1)
        self.segments.setMinimumContentsLength(12)
        self.segments.setEnabled(False)
        self.addWidget(self.segments)
        self.isolate = self._toggle("Isolate Segment", requires_model=True)
        self.segments.currentIndexChanged.connect(self._segment_changed)
        self.addSeparator()
        self.textures = self._toggle("Textures", checked=True, requires_model=True)
        self.sprites = self._toggle("Sprites", checked=True)
        self.set_sprite_count(0)
        self.objects = self._toggle("Objects", checked=True, requires_model=True)
        self.racelines = self._toggle("Racelines", requires_model=True)
        self.vehicle = QComboBox(self)
        self.vehicle.setAccessibleName("Raceline vehicle")
        for label,data in (("All vehicles",-1),("Car",0),("Hovercraft",1),("Plane",2)):
            self.vehicle.addItem(label,data)
        self.addWidget(self.vehicle)
        self.lane = QComboBox(self)
        self.lane.setAccessibleName("Raceline lane")
        for label,data in (("Centerline",-1),("AI lane 0",0),("AI lane 1",1),("AI lane 2",2),("AI lane 3",3),("All AI lanes",4)):
            self.lane.addItem(label,data)
        self.addWidget(self.lane)
        self.vehicle.currentIndexChanged.connect(self.routes_changed)
        self.lane.currentIndexChanged.connect(self.routes_changed)
        self.set_object_count(0)

    def set_object_count(self, count: int) -> None:
        for action in (self.objects,self.racelines):
            action.setEnabled(count>0)
        self.objects.setToolTip("Gameplay gizmos; filter categories in the Objects inspector tab")
        self.racelines.setToolTip("Checkpoint splines and explicit AI adjacency; overlays remain visible through track surfaces")
        self.vehicle.setEnabled(count>0)
        self.lane.setEnabled(count>0)

    def set_sprite_count(self, count: int) -> None:
        self.sprites.setEnabled(count > 0)
        self.sprites.setToolTip(f"{count} ROM sprite instances. Independent of gizmo filters; Play previews supported frame sequences.")

    def set_segment_count(self, count: int) -> None:
        self.segments.blockSignals(True)
        self.segments.clear()
        self.segments.addItem("All segments", -1)
        for index in range(count):
            self.segments.addItem(f"Segment {index}", index)
        self.segments.blockSignals(False)
        self.segments.setEnabled(count > 0)
        self.isolate.setChecked(False)
        self.isolate.setEnabled(False)
        for action in (self.wireframe, self.vertex_colors, self.bounds, self.culling, self.textures):
            action.setEnabled(count > 0)
            action.setToolTip("")
        self.textures.setToolTip("Show texture snapshots using each batch's stored frame. Off shows solid geometry.")

    @Slot(int)
    def _segment_changed(self, row: int) -> None:
        index = int(self.segments.currentData()) if row >= 0 else -1
        if index < 0:
            self.isolate.setChecked(False)
        self.isolate.setEnabled(index >= 0)
        self.segment_selected.emit(index)

    def _toggle(self, title: str, *, checked: bool = False, requires_model: bool = False) -> QAction:
        action = QAction(title, self)
        action.setCheckable(True)
        action.setChecked(checked)
        if requires_model:
            action.setEnabled(False)
            action.setToolTip("Load a level to use this control.")
        self.addAction(action)
        return action


class AnimationToolbar(QToolBar):
    """Artwork preview only; controls do not modify object records."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__('Animation preview',parent)
        self.setObjectName('animationToolbar')
        self.setMovable(False)
        self.models = self.addAction('Models')
        self.models.setCheckable(True)
        self.models.setChecked(True)
        self.models.setToolTip('ROM 3D object artwork, independent of helper gizmos')
        self.play = self.addAction('Play')
        self.play.setCheckable(True)
        self.play.toggled.connect(lambda playing:self.play.setText('Pause' if playing else 'Play'))
        self.reset = self.addAction('Rewind')
        self.time = QSlider(Qt.Orientation.Horizontal,self)
        self.time.setAccessibleName('Animation preview time')
        self.time.setObjectName('animationTimeSlider')
        self.time.setRange(0,1800)
        self.time.setFixedWidth(170)
        self.time.setToolTip('Scrub artwork and cinematic paths. Set the range in Tools → Cinematics; preview does not save edits.')
        self.addWidget(self.time)
        self.time_label = QLabel(' 0.00 s ',self)
        self.time_label.setMinimumWidth(75)
        self.addWidget(self.time_label)
        self.rate = QComboBox(self)
        self.rate.setAccessibleName('Animation preview speed')
        for value in (.25,.5,1.,2.):
            self.rate.addItem(f'{value:g}×',value)
        self.rate.setCurrentIndex(2)
        self.addWidget(self.rate)
        self.addWidget(QLabel(' Scene ',self))
        self.channel = QComboBox(self)
        self.channel.setMinimumContentsLength(18)
        self.channel.setAccessibleName('Animation scene channel')
        self.addWidget(self.channel)
        self.addWidget(QLabel(' Selected clip ',self))
        self.clip = QComboBox(self)
        self.clip.setAccessibleName('Selected object animation clip')
        self.clip.addItem('From object',-1)
        self.clip.setMinimumContentsLength(10)
        self.addWidget(self.clip)
        self.summary = QLabel('',self)
        self.addWidget(self.summary)
        limitation = 'Play/scrub clips and verified cinematic paths.'
        self.setToolTip(limitation)
        self.summary.setToolTip(limitation)

    def set_time(self, seconds: float) -> None:
        self.time.blockSignals(True)
        self.time.setValue(round(seconds*60))
        self.time.blockSignals(False)
        self.time_label.setText(f' {seconds:.2f} s ')

    def set_channels(self, channels: set[int]) -> None:
        self.channel.blockSignals(True)
        self.channel.clear()
        self.channel.addItem('Ambient + scene 0',0)
        for channel in sorted(channels-{0,20,-1}):
            self.channel.addItem(f'Ambient + scene {channel}',channel)
        self.channel.addItem('Ambient only',-2)
        self.channel.blockSignals(False)

    def set_clips(self, count: int) -> None:
        self.clip.blockSignals(True)
        self.clip.clear()
        self.clip.addItem('From object',-1)
        for index in range(count):
            self.clip.addItem(f'Clip {index}',index)
        self.clip.setEnabled(count > 0)
        self.clip.blockSignals(False)
