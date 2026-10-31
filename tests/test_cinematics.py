"""Source-derived cinematic math/timing plus existing-entry project/export gates."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import math
import struct

import numpy as np
import pytest

from src.core.cinematics import (CinematicTrack, CinematicTimeline, CinematicPose,
    build_tracks, controls, interpolate, path_points, node_events, camera_view, look_at)
from src.core.objects import (LevelObject, ObjectDefinition, ObjectParameter,
    ObjectDatabase, load_object_database, load_object_map)
from src.core.rom import RomImage, AssetType, LUT_START, LUT_END, parse_asset_lut
from src.core.editing import EditSession
from src.core.level_header import load_level_catalog


HELPER = ObjectDefinition(0, 'Animation', 49, 1.)
TARGET = ObjectDefinition(1, 'Actor', 50, 2.)
CAMERA = ObjectDefinition(2, 'Camera', 51, 1.)
DATABASE = ObjectDatabase((1, 2), (HELPER, TARGET, CAMERA))


def node(index: int, position: tuple[int, int, int] | None = None, **values: int) -> LevelObject:
    fields = dict(actorIndex=0, channel=0, order=index, objectIdToSpawn=0, nodeSpeed=10,
        goToNode=-1, pauseFrameCount=-1, animationStartDelay=0, rotateType=0, unk2D=1,
        unk2A=-1, unk15=-1, unk13=-1, unk1F=-1, messageId=255, unk29=127, scale=64)
    fields.update(values)
    return LevelObject(0, index, None, 0, HELPER, position or (index*100, 0, 0), 50, False,
        tuple(ObjectParameter(k, 8+i, 'b', v) for i, (k, v) in enumerate(fields.items())), None)


def track(*nodes: LevelObject) -> CinematicTrack:
    return build_tracks(tuple(nodes), DATABASE)[0]


def test_group_sort_scene_ambient_and_camera() -> None:
    nodes = (node(0, order=2), node(1, order=0), node(2, channel=1),
             node(3, actorIndex=1, objectIdToSpawn=1), node(4, channel=20, actorIndex=2))
    tracks = build_tracks(nodes, DATABASE)
    assert len(tracks) == 3
    assert tracks[0].channel == 20 and tracks[0].actor == -126
    assert tracks[1].indices == (1, 0)
    assert tracks[2].camera and tracks[2].target == CAMERA
    assert len(build_tracks(nodes, DATABASE, -2)) == 1
    assert build_tracks(nodes, DATABASE, 1)[1].indices == (2,)
    assert [n.value('order') for n in nodes] == [2, 0, 2, 3, 4]  # no runtime renumbering leaks to ROM


def test_duplicate_orders_and_auto_actor_are_diagnosed() -> None:
    t = build_tracks((node(0, actorIndex=5), node(1, actorIndex=-2, order=0)), DATABASE)[0]
    assert t.actor == 5 and t.indices == (0, 1)
    assert any('Equal stored orders' in text for text in t.warnings)
    reset = build_tracks((node(0, actorIndex=5), node(1, actorIndex=-1), node(2, actorIndex=-2)), DATABASE)
    assert reset[0].actor == 0 and reset[0].indices == (1, 2)


def test_catmull_polynomial_derivative_and_linear() -> None:
    data = np.array(((0., 0.), (2., 5.), (5., 2.), (9., 1.)))
    np.testing.assert_array_equal(interpolate(data, 0), data[1])
    np.testing.assert_array_equal(interpolate(data, 1), data[2])
    np.testing.assert_allclose(interpolate(data, .5, linear=True), (3.5, 3.5))
    dt = 1e-5
    numeric = (interpolate(data, .3+dt)-interpolate(data, .3-dt))/(2*dt)
    np.testing.assert_allclose(interpolate(data, .3, derivative=True), numeric, atol=1e-8)


def test_rotation_shortest_wrap_and_open_endpoints() -> None:
    t = track(node(0, y_rotation=250), node(1, y_rotation=6), node(2))
    data = controls(t, 0)
    np.testing.assert_allclose(data[0, :3], (-100, 0, 0))
    midpoint = interpolate(data[:4], .5)[3]
    assert midpoint == pytest.approx(math.tau, abs=.02)
    assert interpolate(data[:4], .5, linear=True)[3] == pytest.approx(math.tau)
    points = path_points(t)
    np.testing.assert_allclose(points[0], t.nodes[0].position)
    np.testing.assert_allclose(points[-1], t.nodes[-1].position)


def test_ntsc_speed_delay_pause_and_deterministic_rewind() -> None:
    t = track(node(0, animationStartDelay=60, pauseFrameCount=2), node(1), node(2))
    timeline = CinematicTimeline(t)
    assert timeline.sample(59/60).position == (0., 0., 0.)
    assert timeline.sample(62/60).position == (0., 0., 0.)
    assert timeline.sample(63/60).position[0] == pytest.approx(1.)
    assert timeline.arrivals[0] == 60
    forward = timeline.sample(2.)
    assert forward.position[0] == pytest.approx(58.)
    timeline.sample(.1)
    assert timeline.sample(2.) == forward
    assert CinematicTimeline(t).sample(2.) == forward


def test_inherited_speed_and_variable_speed() -> None:
    inherited = CinematicTimeline(track(node(0), node(1, nodeSpeed=-1), node(2, nodeSpeed=-1)))
    assert inherited.sample(1.).position[0] == pytest.approx(60.)
    fast = CinematicTimeline(track(node(0), node(1, nodeSpeed=20), node(2, nodeSpeed=20)))
    assert fast.sample(1.).position[0] > 60


def test_open_path_finishes_and_loop_reenters_ordinal() -> None:
    t = track(*(node(i) for i in range(5)))
    timeline = CinematicTimeline(t)
    assert timeline.sample(10.).status == 'Finished'
    np.testing.assert_allclose(timeline.sample(10.).position, (400, 0, 0))
    looped = replace(t, nodes=(*t.nodes[:-1], node(4, goToNode=1)))
    run = CinematicTimeline(looped)
    assert looped.loop == 1
    assert run.sample(12.).status != 'Finished'
    assert len(run.arrivals) == 5
    pose = run.sample(12.); run.sample(0)
    assert run.sample(12.) == pose


def test_external_wait_and_scene_change_are_explicit() -> None:
    waiting = CinematicTimeline(track(node(0, animationStartDelay=-1), node(1)))
    assert 'Waiting' in waiting.sample(20).status
    assert not waiting.arrivals
    switched = CinematicTimeline(track(node(0), node(1, unk2A=2), node(2)))
    pose = switched.sample(10.)
    assert 'Scene switch 2' in pose.status
    assert switched.sample(20.) == pose
    assert 'Switch scene 2' in node_events(node(0, unk2A=2))


@pytest.mark.parametrize('mode,frame', ((0, 0.), (1, 14.), (2, 31.), (3, 14.)))
def test_clip_modes_use_sixteenths(mode: int, frame: float) -> None:
    t = track(node(0, objAnimIndex=0, objAnimSpeed=1, objAnimLoopType=mode, nodeSpeed=0))
    timeline = CinematicTimeline(t, {0: 3})
    # 32 ticks reaches 31 in ping-pong; next 17 ticks descends to 14.
    ticks = 64 if mode == 0 else 49
    assert timeline.sample(ticks/60).frame == pytest.approx(frame)


def test_camera_view_and_look_at_orientation() -> None:
    pose = CinematicPose((3., 4., 5.), (0., 0., 0.), 1., 0, 0, 0., 'Initial')
    view = camera_view(pose)
    np.testing.assert_allclose(view @ np.array([3, 4, 5, 1]), [0, 0, 0, 1])
    np.testing.assert_allclose(view[:3, :3], np.eye(3))
    toward = look_at(pose, replace(pose, position=(3., 4., 100.)))
    np.testing.assert_allclose(-camera_view(toward)[2, :3], [0, 0, 1], atol=1e-6)
    rolled = camera_view(replace(pose, angles=(.4, .2, .3)))[:3, :3]
    np.testing.assert_allclose(rolled @ rolled.T, np.eye(3), atol=1e-6)


def test_tangent_spin_pause_clip_change_and_hide_endpoints() -> None:
    tangent = CinematicTimeline(track(node(0, rotateType=2), node(1), node(2)))
    pose = tangent.sample(.5)
    np.testing.assert_allclose(-camera_view(pose)[2, :3], [1, 0, 0], atol=1e-6)
    spin = CinematicTimeline(track(node(0, rotateType=1, nodeSpeed=0, yawSpinSpeed=1, rollSpinSpeed=2, pitchSpinSpeed=3)))
    np.testing.assert_allclose(spin.sample(1).angles, np.array((1, 2, 3))*480*math.tau/65536)
    delayed = CinematicTimeline(track(node(0, animationStartDelay=120, specialHide=1), node(1)))
    assert not delayed.sample(1).visible
    assert delayed.sample(2).visible
    switch = CinematicTimeline(track(node(0, objAnimIndex=0, objAnimSpeed=1),
        node(1, objAnimIndex=1, unk16=17, objAnimSpeed=0, pauseFrameCount=5), node(2)), {0: 100, 1: 10})
    switch.sample(2)
    assert switch.state.clip == 1 and switch.state.frame == 17


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(Path(__file__).resolve().parents[1].glob('*.z64'))
    if not paths:
        pytest.skip('Local Rev1 ROM absent')
    return RomImage.from_file(paths[0])


def test_all_stock_tracks_have_finite_paths_and_deterministic_samples(rom: RomImage) -> None:
    db = load_object_database(rom)
    count = 0
    for map_id in range(rom.count(AssetType.LEVEL_OBJECT_MAPS)):
        objects = load_object_map(rom, map_id, db).objects
        for channel in {int(o.value('channel', 0)) for o in objects if o.definition.behavior_id == 49}:
            for t in build_tracks(objects, db, channel):
                assert np.isfinite(path_points(t)).all()
                run = CinematicTimeline(t)
                initial = run.sample(0)
                later = run.sample(.5)
                assert np.isfinite((*later.position, *later.angles, later.scale)).all()
                assert run.sample(0) == initial
                assert run.sample(.5) == later
                count += 1
    assert count > 100


def test_existing_node_edit_undo_project_and_in_memory_rom(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    obj = next(o for o in session.current_map(5).objects if o.definition.behavior_id == 49)
    original = obj.raw_data
    assert original is not None and len(original) == 50
    assert session.set_parameter(obj.key, 'nodeSpeed', 37)
    changed = session.object(obj.key).raw_data
    assert changed[:0x14] == original[:0x14] and changed[0x15:] == original[0x15:]
    assert changed[0x14] == 37
    assert session.set_parameter(obj.key, 'animationStartDelay', 600)
    assert struct.unpack_from('>h', session.object(obj.key).raw_data, 0xE)[0] == 600
    session.save_project(tmp_path/'cinematic.dkrproj', 5)
    reopened = EditSession.load_project(tmp_path/'cinematic.dkrproj')
    assert reopened.object(obj.key) == session.object(obj.key)
    output = session.build_rom()
    exported = RomImage(output, 'z64', parse_asset_lut(output, LUT_START, LUT_END))
    db = load_object_database(exported)
    reloaded = load_object_map(exported, 5, db).objects[obj.index]
    assert reloaded.raw_data == session.object(obj.key).raw_data
    assert len(exported.data) == len(rom.data)
    session.undo(); session.undo()
    assert session.object(obj.key).raw_data == original
    assert session.build_rom() == rom.data
