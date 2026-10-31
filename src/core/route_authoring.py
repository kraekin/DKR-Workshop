"""Staged alternate checkpoints and lane generation using verified entry fields."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import TYPE_CHECKING
import numpy as np

from src.core.course import (CoursePlan, CoursePoint, level_objects, plan_objects,
    route_heading, surface_snap, course_diagnostics)
from src.core.object_structure import (EntryIdentity, MapState, MAX_IDENTITY, rebuild,
    validate_capacity, identify)
from src.core.objects import ObjectMap, LevelObject
from src.core.placement import TerrainSurface, patch_entry
from src.core.routes import LATERAL, HEIGHT, BEHAVIOR, RouteIssue, lane_point

if TYPE_CHECKING:
    from src.core.editing import EditSession


@dataclass(frozen=True)
class AlternatePoint:
    index: int
    position: tuple[int, int, int]
    key: tuple[int, int] | None = None


@dataclass(frozen=True)
class LaneOptions:
    half_width: float = 160.
    follow_road: bool = False
    road_height: int = 32
    reset_behaviors: bool = False


def continuity_issues(objects: tuple[LevelObject, ...], group: int) -> tuple[RouteIssue, ...]:
    main = sorted((o for o in objects if o.definition.behavior_id == 13 and o.value("vehicleType") == group
                   and not o.value("isAltCheckpoint")), key=lambda o: o.value("index"))
    alternate = {o.value("index"): o for o in objects if o.definition.behavior_id == 13
                 and o.value("vehicleType") == group and o.value("isAltCheckpoint")}
    issues: list[RouteIssue] = []
    for branch in (False, True) if alternate else (False,):
        route = [alternate.get(o.value("index"), o) if branch else o for o in main]
        for i, obj in enumerate(route):
            other = route[(i + 1) % len(route)]
            distance = float(np.linalg.norm(np.asarray(other.position, float) - obj.position))
            values = [obj.value(field) for field in LATERAL]
            if values != sorted(values):
                issues.append(RouteIssue("lane-order", f"CP {obj.value('index')}: lane offsets cross their numeric order; review intended AI lanes.", (obj.key,)))
            for lane in range(4):
                separation = float(np.linalg.norm(np.asarray(lane_point(other, lane)) - lane_point(obj, lane)))
                if separation > max(distance * 2, distance + 512):
                    issues.append(RouteIssue("lane-discontinuity", f"{'Alternate' if branch else 'Main'} CP {obj.value('index')} → {other.value('index')}, lane {lane}: large jump relative to the route centre.", (obj.key, other.key)))
            if branch and obj.value("isAltCheckpoint"):
                issues.append(RouteIssue("alternate-pair", f"Alternate CP {obj.value('index')} replaces its paired main index; review entry/rejoin and all four lanes.", (obj.key,)))
    return tuple(dict.fromkeys(issues))


def build_route_plan(session: EditSession, level: int, group: int, map_id: int,
                     alternates: tuple[AlternatePoint, ...], lanes: LaneOptions | None = None,
                     *, align_alternates: bool = True) -> CoursePlan:
    session._require_idle()
    header = session.level_header(level)
    maps = tuple(dict.fromkeys(m for m in (header.object_map_id, header.secondary_object_map_id) if m >= 0))
    if map_id not in maps:
        raise ValueError("Choose a map loaded by this course")
    objects = level_objects(session, level)
    main = [o for o in objects if o.definition.behavior_id == 13 and o.value("vehicleType") == group and not o.value("isAltCheckpoint")]
    lookup = {int(o.value("index")): o for o in main}
    if len(main) < 4 or len(lookup) != len(main):
        raise ValueError("Author at least four distinct main checkpoint indexes before finishing routes")
    if len(main) + len(alternates) > 60 or len({p.index for p in alternates}) != len(alternates):
        raise ValueError("Use one alternate per main index and at most 60 total checkpoints in the set")
    old = {o.key: o for o in objects if o.definition.behavior_id == 13 and o.value("vehicleType") == group and o.value("isAltCheckpoint")}
    retained = [p.key for p in alternates if p.key is not None]
    if len(set(retained)) != len(retained) or any(key not in old for key in retained):
        raise ValueError("Alternate rows must retain distinct entries from this checkpoint set")
    before = tuple(session._map_state(m) for m in maps)
    seeds = {m: session._next_identity.get(m, len(session.original_map(m).objects)) for m in maps}
    counters = dict(seeds)
    entries = {m: [(o.index, o.raw_data) for o in session.current_map(m).objects if o.key not in old or o.key in retained] for m in maps}
    identities = {s.map_id: [identity for identity in s.identities if (s.map_id, identity.value) not in old or (s.map_id, identity.value) in retained] for s in before}
    branch = {p.index: p for p in alternates}
    ordered = sorted(main, key=lambda o: o.value("index"))
    points = tuple(CoursePoint(branch[o.value("index")].position if o.value("index") in branch else o.position) for o in ordered)
    selected: list[tuple[int, int]] = []
    for point in alternates:
        if type(point.index) is not int or point.index not in lookup:
            raise ValueError("Each alternate must pair with an existing main checkpoint index")
        paired = lookup[point.index]
        template = old[point.key] if point.key is not None else paired
        parameters = {"index": point.index, "vehicleType": group}
        if point.key is None:
            parameters["isAltCheckpoint"] = 1
        if align_alternates:
            parameters["angleY"] = route_heading(points, ordered.index(paired))
        raw = patch_entry(template, position=point.position, parameters=parameters)
        if point.key is not None:
            entries[template.map_id] = [(i, raw if i == template.index else r) for i, r in entries[template.map_id]]
            selected.append(point.key)
        else:
            serial = counters[map_id]
            if serial >= MAX_IDENTITY:
                raise ValueError("Stable object identity counter exhausted")
            counters[map_id] += 1
            origin = next(i for s in before if s.map_id == paired.map_id for i in s.identities if i.value == paired.index)
            entries[map_id].append((serial, raw))
            identities[map_id].append(EntryIdentity(serial, origin.template, raw))
            selected.append((map_id, serial))
    terrain = TerrainSurface.from_model(session.track_model(header.geometry_id))
    if lanes is not None:
        if not math.isfinite(lanes.half_width) or lanes.half_width < 0 or type(lanes.road_height) is not int:
            raise ValueError("Lane width and road height must be finite valid values")
        for m in maps:
            parsed = identify(ObjectMap.from_bytes(rebuild(session, m, tuple(raw for _, raw in entries[m])), session.database, map_id=m), tuple(identities[m]))
            updated = {}
            for obj in parsed.objects:
                if obj.definition.behavior_id != 13 or obj.value("vehicleType") != group:
                    continue
                scale = max(float(obj.value("scale")), 5) / 32
                values = [round(factor * lanes.half_width / scale) for factor in (-1, -1/3, 1/3, 1)]
                if any(v < -128 or v > 127 for v in values):
                    raise ValueError(f"CP {obj.value('index')}: lane width exceeds signed8 range at its existing scale")
                parameters = dict(zip(LATERAL, values))
                for lane, lateral in enumerate(values):
                    if lanes.follow_road:
                        yaw = obj.yaw or 0
                        target = (round(obj.position[0] + scale * math.cos(yaw) * lateral), obj.position[1],
                                  round(obj.position[2] - scale * math.sin(yaw) * lateral))
                        y = surface_snap(terrain, target, reference=obj.position, offset=lanes.road_height)
                        height = round((y - obj.position[1]) / scale)
                        if not -128 <= height <= 127:
                            raise ValueError("Road-following lane exceeds the stored signed8 height range")
                        parameters[HEIGHT[lane]] = height
                    if lanes.reset_behaviors:
                        parameters[BEHAVIOR[lane]] = 0
                updated[obj.index] = patch_entry(obj, parameters=parameters)
            entries[m] = [(i, updated.get(i, raw)) for i, raw in entries[m]]
    after = tuple(MapState(m, rebuild(session, m, tuple(raw for _, raw in entries[m])), tuple(identities[m])) for m in maps)
    validate_capacity(session, after)
    notes = (f"Set {group}: {len(old)} → {len(alternates)} paired alternate checkpoints.",)
    if lanes is not None:
        notes += (f"Generate four lanes at half-width {lanes.half_width:g}; {'follow nearby road' if lanes.follow_road else 'retain existing heights'}; {'reset' if lanes.reset_behaviors else 'retain'} behavior selectors.",)
    plan = CoursePlan(level, session._signature(), before, after, tuple(seeds.items()), tuple(counters.items()), tuple(selected), (), notes)
    result = plan_objects(session, plan)
    return replace(plan, issues=course_diagnostics(result, header.checkpoint_sets, terrain, active_set=group) + continuity_issues(result, group))
