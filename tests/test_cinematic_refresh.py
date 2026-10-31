"""UI cinematic cache integration without a QApplication or OpenGL context."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.cinematics import CinematicTimeline, build_tracks
from src.core.editing import EditSession
from src.core.rom import RomImage
from src.ui.main_window import MainWindow
from src.renderer.viewport import Viewport
from src.core.textures import SpriteInstance,SpriteTile,Texture
from src.core.track_artwork import build_texture,TextureOptions
import numpy as np
from dataclasses import replace


@pytest.fixture(scope='module')
def rom() -> RomImage:
    for path in Path(__file__).resolve().parents[1].glob('*.z64'):
        try:
            return RomImage.from_file(path)
        except ValueError:
            pass
    pytest.skip('Original local Rev1 ROM unavailable')


class CinematicRefresh:
    """Exercise the actual window cache with its two UI sinks replaced."""

    def __init__(self, session: EditSession) -> None:
        self.session = session
        self.timelines: tuple[CinematicTimeline, ...] = ()
        self.window = SimpleNamespace(
            current_objects=(), object_database=session.database, object_library=None,
            animation_toolbar=SimpleNamespace(channel=SimpleNamespace(currentData=lambda: 0)),
            viewport=SimpleNamespace(cinematic_camera=-1, set_cinematics=self.set_timelines),
            object_inspector=SimpleNamespace(cinematics=SimpleNamespace(set_tracks=lambda *_: None)),
            edit_session=session, _cinematic_key=None,
        )

    def set_timelines(self, timelines: tuple[CinematicTimeline, ...]) -> None:
        self.timelines = timelines

    def refresh(self) -> None:
        # Ancient Lake's collectable map precedes its secondary map in the viewport.
        self.window.current_objects = tuple(o for m in (73, 5) for o in self.session.current_map(m).objects)
        MainWindow._update_cinematics(self.window)

    def assert_owners(self) -> None:
        objects = self.window.current_objects
        expected = build_tracks(objects, self.session.database)
        assert tuple(t.track.indices for t in self.timelines) == tuple(t.indices for t in expected)
        for timeline in self.timelines:
            for index, node in zip(timeline.track.indices, timeline.track.nodes):
                assert objects[index].key == node.key
                assert objects[index].definition.behavior_id == 49


@pytest.mark.parametrize('object_id', [78, 28])  # RubberTree and WeaponBalloon
def test_cinematic_owners_follow_add_duplicate_delete_and_history(rom: RomImage, object_id: int) -> None:
    session = EditSession(rom)
    cache = CinematicRefresh(session)
    cache.refresh()
    cache.assert_owners()
    template = next(t for t in session.object_catalog if t.object_id == object_id)
    key = session.add_object(73, template, (-1074, 60, -7601))
    cache.refresh()
    cache.assert_owners()
    clone, = session.duplicate_objects((key,))
    cache.refresh()
    cache.assert_owners()
    session.delete_objects((key,))
    cache.refresh()
    cache.assert_owners()
    # Deleting an earlier entry in the secondary map shifts the same owners too.
    session.delete_objects(((5, 0),))
    cache.refresh()
    cache.assert_owners()
    for _ in range(4):
        session.undo()
        cache.refresh()
        cache.assert_owners()
    for _ in range(4):
        session.redo()
        cache.refresh()
        cache.assert_owners()
    assert session.object(clone).object_id == object_id


def test_unrelated_position_edits_reuse_cinematic_timelines(rom: RomImage) -> None:
    session = EditSession(rom)
    cache = CinematicRefresh(session)
    cache.refresh()
    timelines = cache.timelines
    session.set_position((73, 0), (123, 45, -678))
    cache.refresh()
    assert cache.timelines is timelines
    cache.assert_owners()
    node = timelines[0].track.nodes[0]
    session.set_position(node.key, (123, 45, -678))
    cache.refresh()
    assert cache.timelines is not timelines
    cache.assert_owners()


@pytest.mark.parametrize('refresh_pixels',[False,True])
def test_artwork_refresh_sprite_comparison_avoids_array_equality(refresh_pixels: bool) -> None:
    raw=build_texture(np.full((8,8,4),255,np.uint8),TextureOptions(8,8))
    def instance() -> SpriteInstance:
        frame=Texture.from_bytes(raw).frames[0]
        return SpriteInstance(0,0,(1.,2.,3.),1.,(SpriteTile(0,frame,0.,7.,0.,-7.),))
    before=instance();after=instance() if refresh_pixels else replace(before)
    view=SimpleNamespace(preview_time=0.,cinematic_motion=False,model_instances=(),sprites=(after,),
        cinematic_camera=-1,_cinematic_sample_key=None,cinematics=(),display_sprites=(before,),_sprites_dirty=False)
    Viewport._sample_cinematics(view)
    assert view._sprites_dirty==refresh_pixels
