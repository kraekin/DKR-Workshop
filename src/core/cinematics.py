"""Existing Animation tracks, from objects.c:8001E93C/8001F460/8002125C.

NTSC, one logic tick per 1/60 second. This is a geometric preview, not the
cutscene interpreter: external waits and scene switches stop the local track.
No serialized entries are modified by grouping or sampling.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

import numpy as np
from numpy.typing import NDArray

from src.core.objects import LevelObject, ObjectDatabase, ObjectDefinition, BEHAVIOR_NAMES


@dataclass(frozen=True)
class CinematicTrack:
    actor: int
    channel: int
    nodes: tuple[LevelObject, ...]
    indices: tuple[int, ...]
    target: ObjectDefinition | None
    warnings: tuple[str, ...] = ()

    @property
    def owner(self) -> int:
        return self.indices[0]

    @property
    def camera(self) -> bool:
        return self.target is not None and self.target.behavior_id == 51

    @property
    def label(self) -> str:
        name = self.target.name if self.target else 'No spawn target'
        return f"{'Camera' if self.camera else 'Actor'} {self.actor} · {name} · {len(self.nodes)} nodes"

    @property
    def loop(self) -> int:
        value = int(self.nodes[-1].value('goToNode', -1))
        return value if len(self.nodes) > 2 and 0 <= value < len(self.nodes)-1 else -1


def build_tracks(objects: tuple[LevelObject, ...], database: ObjectDatabase,
                 channel: int = 0) -> tuple[CinematicTrack, ...]:
    """Resolve initial-load actor IDs; stable sort and runtime ordinal numbering.

    Ambient actors have their signed high bit set by obj_init_animation. Scene
    channels are grouped separately from ambient, which occupies a distinct ID
    range. Equal orders and runtime append sentinels receive diagnostics.
    """
    groups: dict[tuple[int, int], list[tuple[int, LevelObject, str]]] = {}
    last_actor = 0
    for index, obj in enumerate(objects):
        if obj.definition.behavior_id != 49:
            continue
        actor = int(obj.value('actorIndex', 0))
        if actor == -2:
            actor = last_actor
        elif actor == -1:
            actor = 0
            last_actor = 0
        else:
            last_actor = actor
        scene = int(obj.value('channel', -1))
        if scene == -1:
            scene = channel
        if scene != 20 and (channel == -2 or scene != channel):
            continue
        if scene == 20:
            actor = ((actor | 128)+128) % 256-128
        warning = 'Runtime append order: initial-load order assumed.' if obj.value('order', 0) == -2 else ''
        groups.setdefault((scene, actor), []).append((index, obj, warning))
    result: list[CinematicTrack] = []
    for (scene, actor), entries in sorted(groups.items(), key=lambda pair: (pair[0][0] != 20, pair[0])):
        entries.sort(key=lambda item: max(0, int(item[1].value('order', 0))))
        nodes = tuple(item[1] for item in entries)
        warnings = [item[2] for item in entries if item[2]]
        orders = [int(node.value('order', 0)) for node in nodes]
        if len(set(orders)) != len(orders):
            warnings.append('Equal stored orders: runtime action flags can change tie order; map order shown.')
        ident = int(nodes[0].value('objectIdToSpawn', -1))
        try:
            target = database.resolve(ident) if ident >= 0 else None
        except ValueError:
            target = None
            warnings.append(f'Unresolved spawn object ID {ident}.')
        if any(node.value('unk22', 0) in (1, 18) or 10 <= node.value('unk22', 0) < 18 for node in nodes):
            warnings.append('Live camera/racer position substitution is unavailable; stored path shown.')
        if nodes[0].value('rotateType', 0) == 3:
            warnings.append('Look-at actor uses simultaneous preview poses; game actor update order can differ.')
        if target is not None and target.behavior_id in tuple(BEHAVIOR_NAMES.index(name) for name in ('BHV_CAR_ANIMATION', 'BHV_VEHICLE_ANIMATION')):
            warnings.append('Racer/vehicle controller: path is shown; the live vehicle assembly and steering are not simulated.')
        if any(obj.definition.behavior_id == BEHAVIOR_NAMES.index('BHV_OVERRIDE_POS') for obj in objects):
            warnings.append('Override-position helpers can alter the game actor pose; stored Animation nodes are previewed.')
        if any(node.value('unk2A', -1) >= 0 for node in nodes):
            warnings.append('Scene switch event stops this local track; select the destination scene separately.')
        loop = int(nodes[-1].value('goToNode', -1))
        if loop >= 0 and not (len(nodes) > 2 and loop < len(nodes)-1):
            warnings.append('Invalid / ineligible loop target; source treats this as an open path.')
        elif loop >= 0 and len(nodes)-loop < 4:
            warnings.append('Short loop control window is extended cyclically in this preview.')
        result.append(CinematicTrack(actor, scene, nodes, tuple(item[0] for item in entries), target,
                                     tuple(dict.fromkeys(warnings))))
    return tuple(result)


def interpolate(data: NDArray[np.float64], t: float, *, linear: bool = False,
                derivative: bool = False) -> NDArray[np.float64]:
    """Source Catmull–Rom polynomial (or source lerp), four control points."""
    if linear:
        return data[2]-data[1] if derivative else data[1]+t*(data[2]-data[1])
    a = -.5*data[0]+1.5*data[1]-1.5*data[2]+.5*data[3]
    b = data[0]-2.5*data[1]+2*data[2]-.5*data[3]
    c = .5*(data[2]-data[0])
    return (3*a*t+2*b)*t+c if derivative else ((a*t+b)*t+c)*t+data[1]


def controls(track: CinematicTrack, segment: int) -> NDArray[np.float64]:
    """Five XYZ / yaw,pitch,roll / scale controls including source end extensions."""
    nodes = track.nodes
    rows = np.array([(*node.position, *(int(node.value(key, 0))*math.tau/256
        for key in ('y_rotation', 'x_rotation', 'z_rotation')), max(int(node.value('scale', 64)), 1)/64)
        for node in nodes], np.float64)
    out: list[NDArray[np.float64]] = []
    for index in range(segment-1, segment+4):
        if index < 0:
            row = rows[-1].copy() if track.loop == 0 else rows[0].copy()
            if track.loop != 0 and len(rows) > 1:
                row[:3] = 2*rows[0, :3]-rows[1, :3]
        elif index >= len(rows):
            if track.loop >= 0:
                row = rows[track.loop+(index-len(rows)) % (len(rows)-track.loop)].copy()
            else:
                row = rows[-1].copy()
                if len(rows) > 1:
                    row[:3] = 2*rows[-1, :3]-rows[-2, :3]
        else:
            row = rows[index].copy()
        out.append(row)
    array = np.array(out)
    for i in range(1, 5):
        for axis in range(3, 6):
            delta = array[i, axis]-array[i-1, axis]
            if delta > math.pi:
                array[i:, axis] -= math.tau
            elif delta < -math.pi:
                array[i:, axis] += math.tau
    return array


def path_points(track: CinematicTrack, subdivisions: int = 16) -> NDArray[np.float32]:
    points: list[NDArray[np.float64]] = []
    count = len(track.nodes) if track.loop >= 0 else len(track.nodes)-1
    linear = int(track.nodes[0].value('unk2D', 0)) != 0
    for segment in range(max(count, 0)):
        linear = int(track.nodes[segment].value('unk2D', 0)) != 0
        data = controls(track, segment)
        points.extend(interpolate(data[:4, :3], t, linear=linear) for t in np.linspace(0, 1, subdivisions, endpoint=False))
    if points:
        points.append(np.asarray(track.nodes[track.loop if track.loop >= 0 else -1].position, np.float64))
    return np.asarray(points, np.float32).reshape(-1, 3)


def node_events(node: LevelObject) -> tuple[str, ...]:
    """Understood requests, not claims that an event has been simulated."""
    events: list[str] = []
    for field, default, title in (('messageId', 255, 'Message'), ('unk1F', -1, 'Music'),
                                ('unk1E', 0, 'Sound'), ('unk30', 0, 'Music fade'),
                                ('unk15', -1, 'Release actor'), ('unk2A', -1, 'Switch scene')):
        value = int(node.value(field, default))
        if value != default and (value >= 0 or field == 'unk30') and not (field == 'unk1F' and value <= 0):
            events.append(f'{title} {value}')
    pause = int(node.value('pauseFrameCount', -1))
    if pause >= 0:
        events.append(f'Pause {pause+1} ticks')
    if int(node.value('unk13', -1)) >= 0:
        events.append(f"Particle mask {node.value('unk13')}")
    if (int(node.value('unk29', 127)) & 127) != 127:
        events.append('Screen fade / fog request')
    if node.value('fadeOptions', 0):
        events.append(f"Actor fade flags {node.value('fadeOptions')}")
    return tuple(events)


@dataclass(frozen=True)
class CinematicPose:
    position: tuple[float, float, float]
    angles: tuple[float, float, float]
    scale: float
    node: int
    clip: int
    frame: float
    status: str
    visible: bool = True


@dataclass
class _State:
    tick: int
    segment: int
    progress: float
    step: float
    speed: float
    previous_speed: float
    delay: int
    pause: int
    position: NDArray[np.float64]
    angles: NDArray[np.float64]
    scale: float
    clip: int
    frame: float
    clip_speed: float
    clip_mode: int
    reverse: bool = False
    started: bool = False
    stopped: bool = False
    opacity: int = 255
    fade: int = 0
    status: str = 'Initial pose'

    def clone(self) -> _State:
        return replace(self, position=self.position.copy(), angles=self.angles.copy())


class CinematicTimeline:
    """Deterministic NTSC unit-tick playback with checkpoints for backward scrub.

    Source update rate varies in-game. These are 60 Hz reference timings, not
    frame-perfect claims for collision-driven actors or external cutscene state.
    """
    def __init__(self, track: CinematicTrack, clip_lengths: dict[int, int] | None = None) -> None:
        self.track = track
        self.clip_lengths = clip_lengths or {}
        n = track.nodes[0]
        self.initial = _State(0, 0, 0., .0, float(n.value('nodeSpeed', 0))*.1, 0.,
            int(n.value('animationStartDelay', 0)), int(n.value('pauseFrameCount', -1)),
            np.asarray(n.position, np.float64), np.array([int(n.value(k, 0))*math.tau/256
                for k in ('y_rotation', 'x_rotation', 'z_rotation')]),
            max(int(n.value('scale', 64)), 1)/64, int(n.value('objAnimIndex', 0)),
            float(n.value('unk16', 0)), float(n.value('objAnimSpeed', 0)), int(n.value('objAnimLoopType', 0)))
        self.state = self.initial.clone()
        self.checkpoints = {0: self.initial.clone()}
        self.arrivals: dict[int, int] = {}
        self._controls = tuple(controls(track, i) for i in range(len(track.nodes)+1))

    def sample(self, seconds: float) -> CinematicPose:
        tick = max(0, min(18000, int(math.floor(seconds*60+1e-7))))
        if tick < self.state.tick:
            nearest = max(i for i in self.checkpoints if i <= tick)
            self.state = self.checkpoints[nearest].clone()
        while self.state.tick < tick:
            self._advance()
            self.state.tick += 1
            if self.state.tick % 60 == 0:
                self.checkpoints[self.state.tick] = self.state.clone()
        s = self.state
        node = self._ordinal(s.segment)
        hidden = s.opacity == 0 or ((s.delay != 0 or s.status == 'Finished') and self.track.nodes[node].value('specialHide', 0) != 0)
        return CinematicPose(tuple(float(v) for v in s.position), tuple(float(v) for v in s.angles),
                              s.scale, node, s.clip, s.frame, s.status, not hidden)

    def _ordinal(self, index: int) -> int:
        n = len(self.track.nodes)
        return (self.track.loop+(index-n)) if index >= n and self.track.loop >= 0 else min(index, n-1)

    def _arrive(self, ordinal: int) -> None:
        s = self.state
        n = self.track.nodes[ordinal]
        self.arrivals.setdefault(ordinal, s.tick+1)
        clip = int(n.value('objAnimIndex', -1))
        if clip >= 0:
            if clip != s.clip:
                s.frame = float(n.value('unk16', 0))
            s.clip = clip
            s.clip_speed = float(n.value('objAnimSpeed', 0))
            s.clip_mode = int(n.value('objAnimLoopType', 0))
        s.pause = int(n.value('pauseFrameCount', -1))
        s.fade = int(n.value('fadeOptions', 0))
        if int(n.value('unk2A', -1)) >= 0:
            s.stopped = True
            s.status = f"Scene switch {n.value('unk2A')} (not simulated)"

    def _advance(self) -> None:
        s = self.state
        first = self.track.nodes[0]
        if s.stopped:
            return
        if s.delay < 0:
            s.status = 'Waiting for input / actor release (not simulated)'
            return
        s.delay = max(0, s.delay-1)
        if s.delay:
            s.status = 'Start delay'
            return
        if not s.started:
            s.started = True
            self._arrive(0)
            if s.stopped:
                return
        if s.fade & 1:
            s.opacity = max(0, (0 if s.fade & 2 else s.opacity)-8)
        else:
            s.opacity = min(255, (255 if s.fade & 2 else s.opacity)+8)
        mode = int(first.value('rotateType', 0))
        if mode == 1:
            # Runtime names swap the source roll/pitch spin fields.
            s.angles += np.array([first.value(k, 0) for k in ('yawSpinSpeed', 'rollSpinSpeed', 'pitchSpinSpeed')])*8*math.tau/65536
        length = self.clip_lengths.get(s.clip, 0)
        if length > 1:
            end = (length-1)*16
            s.frame += (-1 if s.reverse else 1)*s.clip_speed
            if s.clip_mode == 0 and s.frame >= end:
                s.frame -= end
            elif s.clip_mode == 2 and s.frame >= end:
                s.frame = end-1.
            elif s.clip_mode in (1, 3):
                if s.frame >= end:
                    s.reverse = True
                    s.frame = end-1.
                elif s.reverse and s.frame <= 0:
                    s.frame = 0.
                    if s.clip_mode == 1:
                        s.reverse = False
        if s.speed <= 0 or len(self.track.nodes) < 2 or (self.track.loop < 0 and s.segment >= len(self.track.nodes)-1):
            s.status = 'Finished'
            # Source fallback restarts nonnegative pause counters; -1 holds.
            if s.pause != -1:
                if s.pause >= 0:
                    s.pause -= 1
                if s.pause <= 0:
                    tick, old_position, old_angles = s.tick, s.position.copy(), s.angles.copy()
                    self.state = self.initial.clone()
                    self.state.tick = tick
                    self.state.position, self.state.angles = old_position, old_angles
            return
        if s.pause >= 0:
            s.pause -= 1
            s.status = 'Node pause'
            return
        data = self._controls[min(s.segment, len(self._controls)-1)]
        node = self.track.nodes[self._ordinal(s.segment)]
        linear = int(node.value('unk2D', 0)) != 0
        if s.step == 0:
            s.step = .01
        crossed = 0
        t = 0.
        for iteration in range(2):
            t = s.progress+s.step
            crossed = int(t >= 1.)
            if crossed:
                t -= 1.
            if t < 0 or t >= 1. or not math.isfinite(t):
                s.stopped = True
                s.status = 'Degenerate / overshooting path: preview stopped'
                return
            candidate = interpolate(data[crossed:crossed+4, :3], t, linear=linear)
            if iteration == 0:
                distance = float(np.linalg.norm(candidate-s.position))
                if distance:
                    s.step *= s.speed/distance
        values = interpolate(data[crossed:crossed+4], t, linear=linear)
        if crossed and self.track.loop < 0 and s.segment == len(self.track.nodes)-2:
            candidate = interpolate(data[:4, :3], 1.)
        s.position = candidate
        # Scale is always Catmull–Rom, including linear position paths.
        s.scale = float(interpolate(data[crossed:crossed+4, 6:7], t)[0])
        if mode not in (1, 2, 3):
            s.angles = values[3:6]
        elif mode == 2:
            direction = interpolate(data[crossed:crossed+4, :3], t, linear=linear, derivative=True)
            norm = float(np.linalg.norm(direction))
            if norm:
                # arctan2_f uses the inverse atan2 orientation, then source subtracts pi.
                s.angles[0] = math.atan2(-direction[0], -direction[2])
                s.angles[1] = math.atan2(direction[1], norm)
        s.progress = t
        speed = float(node.value('nodeSpeed', -1))*.1
        if speed < 0:
            speed = s.previous_speed
        else:
            s.previous_speed = speed
        if not crossed:
            following = self.track.nodes[self._ordinal(s.segment+1)]
            end_speed = float(following.value('nodeSpeed', -1))*.1
            s.speed = speed+(end_speed-speed)*t if end_speed >= 0 else speed
        s.status = 'Moving'
        if crossed:
            s.segment += 1
            if self.track.loop >= 0 and s.segment > len(self.track.nodes):
                s.segment = self.track.loop+1
            self._arrive(self._ordinal(s.segment))


def look_at(pose: CinematicPose, target: CinematicPose) -> CinematicPose:
    delta = np.asarray(target.position)-pose.position
    length = float(np.linalg.norm(delta))
    if not length:
        return pose
    return replace(pose, angles=(math.atan2(-delta[0], -delta[2]), math.atan2(delta[1], length), pose.angles[2]))


def camera_view(pose: CinematicPose) -> NDArray[np.float32]:
    """animcamera -> camera.c -> mtxf_from_inverse_transform, column GL view."""
    y, x, z = -pose.angles[0], -pose.angles[1], pose.angles[2]
    sy, sx, sz = math.sin(y), math.sin(x), math.sin(z)
    cy, cx, cz = math.cos(y), math.cos(x), math.cos(z)
    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, :3] = ((cy*cz-sx*sz*sy, -cx*sz, sx*sz*cy+sy*cz),
        (sx*cz*sy+cy*sz, cx*cz, sy*sz-sx*cz*cy), (-sy*cx, sx, cy*cx))
    matrix[:3, 3] = -matrix[:3, :3] @ np.asarray(pose.position)
    return matrix
