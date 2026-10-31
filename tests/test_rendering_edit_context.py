"""Queued edit ownership and scene transparency regressions; no Qt/GL context."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MethodType, SimpleNamespace

import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.object_models import ModelInstance
from src.core.objects import ObjectDefinition
from src.core.rom import RomImage
from src.renderer.object_mesh import ObjectMesh
from src.renderer.track_mesh import DrawRange, TrackMesh, SpriteMesh, SpriteDrawRange
from src.renderer.transparency import TransparentDraw, draw_back_to_front
from src.renderer.viewport import Viewport
from src.ui.geometry_panel import GeometryPanel
from src.ui.main_window import MainWindow
from src.ui.material_panel import MaterialPanel


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob('*.z64')))


@pytest.mark.parametrize('kind', ['geometry', 'uv', 'color'])
def test_queued_cells_keep_the_original_track_after_level_switch(
        rom: RomImage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str) -> None:
    session = EditSession(rom)
    old, other = session.track_model(5), session.track_model(6)
    messages: list[str] = []
    refreshes: list[tuple[int, bool]] = []
    label = SimpleNamespace(setText=messages.append)
    window = SimpleNamespace(edit_session=session, current_model=old, _commit_editor=lambda: None,
        _refresh_track_model=lambda index, *, reveal: refreshes.append((index, reveal)),
        _update_material_panel=lambda: None,
        object_inspector=SimpleNamespace(geometry_panel=SimpleNamespace(message=label), materials=SimpleNamespace(message=label)))
    queued: list = []
    monkeypatch.setattr('src.ui.geometry_panel.defer_edit', lambda owner, callback: queued.append(callback))
    monkeypatch.setattr('src.ui.material_panel.defer_edit', lambda owner, callback: queued.append(callback))
    panel = SimpleNamespace(_loading=False, enabled=True, model=old)
    item = SimpleNamespace(data=lambda *_: (0, 0))
    if kind == 'geometry':
        point = old.segments[0].vertices[0].astype(int)
        item.text = lambda _: ', '.join(map(str, point+(0, 1, 0)))
        panel.mode = SimpleNamespace(currentIndex=lambda: 0)
        panel.move_requested = SimpleNamespace(emit=lambda *args: MainWindow._edit_geometry(window, *args))
        GeometryPanel._coordinate_changed(panel, item, 1)
    else:
        panel.edit_requested = SimpleNamespace(emit=lambda *args: MainWindow._edit_materials(window, *args))
        panel._emit = MethodType(MaterialPanel._emit, panel)
        if kind == 'uv':
            uv = old.segments[0].uvs[0].reshape(-1).astype(int).copy()
            uv[0] += 1
            item.text = lambda _: ', '.join(map(str, uv))
            MaterialPanel._face_changed(panel, item, 1)
        else:
            color = old.segments[0].colors[0].astype(int).copy()
            color[2] = (color[2]+1) % 256
            item.text = lambda _: ', '.join(map(str, color))
            MaterialPanel._color_changed(panel, item, 1)
    assert len(queued) == 1 and not session.dirty
    window.current_model = panel.model = other
    queued.pop()()
    assert session.track_model(5).raw_data != old.raw_data
    assert session.track_model(6).raw_data == other.raw_data
    assert refreshes == [(5, False)] and 'applied' in messages[-1].lower()
    edited = session.track_model(5).raw_data
    session.undo()
    assert session.track_model(5).raw_data == old.raw_data
    session.redo()
    assert session.track_model(5).raw_data == edited
    reopened = EditSession.load_project(session.save_project(tmp_path/f'{kind}.dkrproj', 6))
    assert reopened.track_model(5).raw_data == edited
    assert reopened.track_model(6).raw_data == other.raw_data


def test_offscreen_edit_refresh_keeps_the_users_selected_level() -> None:
    events: list[str] = []
    window = SimpleNamespace(edit_session=object(), catalog=object(), current_model=SimpleNamespace(model_id=6),
        _update_edit_actions=lambda: events.append('history updated'),
        level_panel=SimpleNamespace(select_level=lambda _: events.append('level changed')))
    MainWindow._refresh_track_model(window, 5, reveal=False)
    assert events == ['history updated']


@pytest.mark.parametrize('reverse', [False, True])
def test_blending_uses_view_depth_instead_of_object_order_or_radial_distance(reverse: bool) -> None:
    calls: list[str] = []
    # The near range is far off axis: radial-distance sorting would draw it first.
    draws = [TransparentDraw(np.array((100., 0., -3.), np.float32), lambda: calls.append('near')),
             TransparentDraw(np.array((0., 0., -10.), np.float32), lambda: calls.append('far'))]
    view = np.eye(4, dtype=np.float32)
    view[2, 3] = 30.
    draw_back_to_front(reversed(draws) if reverse else draws, view)
    assert calls == ['far', 'near']


def _group(center: tuple[float, float, float], first: int = 0, *, transparent: bool = True) -> DrawRange:
    return DrawRange(0, first, 3, False, None, transparent, False, False, np.array(center, np.float32))


def test_transparent_models_use_animated_world_centers_for_each_range() -> None:
    vertices = np.array(((0., 0., 0.), (3., 0., 0.), (0., 3., 0.),
                         (0., 0., -4.), (3., 0., -4.), (0., 3., -4.)), np.float32)
    faces = np.array(((0, 1, 2), (3, 4, 5)), np.uint32)
    model = SimpleNamespace(mesh=SimpleNamespace(segments=(SimpleNamespace(vertices=vertices),), indices=faces))
    groups = [_group((0., 0., 0.)), _group((0., 0., -4.), 3)]
    mesh = ObjectMesh.__new__(ObjectMesh)
    mesh.library = SimpleNamespace(model=lambda _: model, clip=lambda *_: SimpleNamespace(
        frame_count=2, pose=lambda *_: vertices+(0, 0, -2)))
    mesh.meshes = {0: SimpleNamespace(ranges=groups, _elements=np.arange(6))}
    calls: list[tuple] = []
    mesh._draw_instance = lambda instance, *args, **kwargs: calls.append((instance.object_index, kwargs['ranges'][0].first_index, kwargs['pose']))
    definition = ObjectDefinition(0, 'Test', 2, 1.)
    near = ModelInstance(0, definition, 0, (0., 0., 0.), 2., (0., 0., 0.))
    far = replace(near, object_index=1, position=(0., 0., -10.))
    matrix = np.eye(4, dtype=np.float32)
    draws = mesh.transparent_draws((near, far, replace(near, visible=False)), matrix, np.zeros(3),
        0., -1, -1, textured=True, wireframe=False, culling=True)
    assert sorted(round(float(d.center[2])) for d in draws) == [-22, -14, -12, -4]
    draw_back_to_front(draws, matrix)
    assert [(owner, first) for owner, first, _ in calls] == [(1, 3), (1, 0), (0, 3), (0, 0)]
    assert all(np.array_equal(pose, vertices+(0, 0, -2)) for _, _, pose in calls)


def test_track_and_sprite_queues_keep_isolation_hidden_and_animation_filters() -> None:
    matrix = np.eye(4, dtype=np.float32)
    mesh = TrackMesh.__new__(TrackMesh)
    mesh.ranges = [_group((0., 0., -3.)), replace(_group((0., 0., -8.), 3), segment_index=1),
                   _group((0., 0., -5.), 6, transparent=False)]
    mesh.omitted_batches = {(1, 0)}
    calls: list[dict] = []
    mesh.draw = lambda *args, **kwargs: calls.append(kwargs)
    draws = mesh.transparent_draws(matrix, vertex_colors=True, wireframe=False, cull_backfaces=True,
        isolated_segment=-1, textured=True, camera_position=np.zeros(3))
    assert len(draws) == 1
    draws[0].draw()
    assert calls[0]['ranges'] == (mesh.ranges[0],)
    assert not mesh.transparent_draws(matrix, vertex_colors=True, wireframe=False, cull_backfaces=True,
        isolated_segment=1, textured=True, camera_position=np.zeros(3))
    sprites = SpriteMesh.__new__(SpriteMesh)
    sprites.instances = (SimpleNamespace(object_index=2, frames=(1, 2), frame_at=lambda _: 1),)
    sprites.ranges = [SpriteDrawRange(0, 0, 6, True, np.zeros(3), 2, 0),
                      SpriteDrawRange(1, 6, 6, True, np.zeros(3), 2, 1)]
    sprites.draw = lambda *args, **kwargs: calls.append(kwargs)
    draws = sprites.transparent_draws(matrix, matrix, np.zeros(3), seconds=1., hidden=frozenset())
    assert len(draws) == 1
    draws[0].draw()
    assert calls[-1]['ranges'][0].texture_id == 1
    assert not sprites.transparent_draws(matrix, matrix, np.zeros(3), seconds=1., hidden=frozenset({2}))


def test_viewport_merges_transparency_across_all_artwork_categories() -> None:
    calls: list[str] = []
    def renderer(name: str, z: float) -> SimpleNamespace:
        return SimpleNamespace(transparent_draws=lambda *args, **kwargs: [
            TransparentDraw(np.array((0., 0., z), np.float32), lambda: calls.append(name))])
    viewport = SimpleNamespace(_mesh=renderer('track', -2), _sprite_mesh=renderer('sprite', -10),
        _object_mesh=renderer('model', -4), _special_mesh=renderer('special', -8), _environment=renderer('water', -6),
        vertex_colors=True, wireframe=False, cull_backfaces=True, textured=True,
        camera=SimpleNamespace(position=np.zeros(3),view='Perspective'), show_sprites=True, show_models=True, show_special_art=True,
        cinematic_poses={}, preview_time=0., display_models=(), selected_object=-1, preview_clip=-1,
        material_active=False, material_isolation=None)
    matrix = np.eye(4, dtype=np.float32)
    Viewport._draw_transparency(viewport, matrix, matrix, -1, True)
    assert calls == ['sprite', 'special', 'water', 'model', 'track']
    calls.clear()
    viewport.show_sprites = viewport.show_models = viewport.show_special_art = False
    Viewport._draw_transparency(viewport, matrix, matrix, -1, False)
    assert calls == ['track']
    calls.clear()
    viewport.show_sprites = viewport.show_models = viewport.show_special_art = True
    viewport.material_active, viewport.material_isolation = True, (0, 0)
    Viewport._draw_transparency(viewport, matrix, matrix, -1, False)
    assert calls == ['track']
