"""Staged checkpoint/start-grid authoring using existing structural writers.

Local sources: level_object_entries.h:119–157, object_functions.c:2484/3194,
objects.c:1059–1145/5530–5800, racer.c:2977–2979/3158, object_functions.h:12.
No Qt/OpenGL, heuristic graph repair, geometry changes or new project writers.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import struct
from typing import TYPE_CHECKING

import numpy as np

from src.core.objects import LevelObject, ObjectMap
from src.core.object_structure import (EntryIdentity, MapState, MAX_IDENTITY,
    identify, rebuild, validate_capacity)
from src.core.placement import TerrainSurface, patch_entry
from src.core.routes import RouteIssue, route_diagnostics, lane_point, LATERAL, HEIGHT, BEHAVIOR
from src.core.rom import AssetType, AssetTable
from src.core.export_report import AssetDiff, ExportReport, make_export_report
from src.core.structure import raw_map

if TYPE_CHECKING:
    from src.core.editing import EditSession

Position = tuple[int,int,int]
ObjectKey = tuple[int,int]


@dataclass(frozen=True)
class CoursePoint:
    position: Position
    key: ObjectKey | None = None


@dataclass(frozen=True)
class CourseOptions:
    set_id: int
    map_id: int
    align_headings: bool = False
    reset_lanes: bool = False
    scale: int = 64
    lane_half_width: float = 160.
    remove_alternates: bool = False
    drop: bool = False
    height_offset: int = 32
    remove_keys: tuple[ObjectKey, ...] = ()
    copy_sets: tuple[int, ...] = ()


@dataclass(frozen=True)
class GridOptions:
    anchor: Position
    yaw: float = 0.
    entrance: int = 0
    columns: int = 2
    column_spacing: float = 120.
    row_spacing: float = 140.
    stagger: float = 0.
    drop: bool = True
    height_offset: int = 8
    vehicle: int | None = None
    snap_range: float = 512.


@dataclass(frozen=True)
class GridPlacement:
    positions: tuple[Position, ...]
    errors: tuple[tuple[int, str], ...] = ()


def surface_snap(terrain: TerrainSurface, point: Position, *, reference: Position | None = None,
                 offset: int = 0, search: float = 512.) -> int:
    """Snap near the clicked layer, including uphill, without selecting a remote roof.

    Use the local plane at the anchor to predict the road height at each grid
    position. Intersect vertically at the target, then choose the nearest layer
    to that prediction. Equidistant distinct layers are deliberately ambiguous.
    This is editor placement math, not a new game collision interpretation.
    """
    if not math.isfinite(search) or search <= 0:
        raise ValueError('Surface search distance must be positive and finite')
    triangles = terrain.triangles
    if not len(triangles):
        raise ValueError('no rendered surface near the position')
    a = triangles[:, 0]
    normals = np.cross(triangles[:, 1]-a, triangles[:, 2]-a)
    valid = np.abs(normals[:, 1]) > 1e-9

    def hits(x: float, z: float) -> tuple[np.ndarray, np.ndarray]:
        e1, e2 = triangles[:, 1]-a, triangles[:, 2]-a
        determinant = e1[:, 0]*e2[:, 2]-e1[:, 2]*e2[:, 0]
        inv = np.divide(1., determinant, out=np.zeros_like(determinant), where=valid)
        dx, dz = x-a[:, 0], z-a[:, 2]
        u = (dx*e2[:, 2]-dz*e2[:, 0])*inv
        v = (e1[:, 0]*dz-e1[:, 2]*dx)*inv
        rows = np.flatnonzero(valid & (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7))
        heights = a[rows, 1]-(normals[rows, 0]*(x-a[rows, 0])+normals[rows, 2]*(z-a[rows, 2]))/normals[rows, 1]
        return rows, heights

    def nearest(heights: np.ndarray, expected: float) -> int:
        order = np.argsort(np.abs(heights-expected), kind='stable')
        if not len(order) or abs(heights[order[0]]-expected) > search:
            raise ValueError('no rendered surface near the position')
        first = int(order[0])
        for other in order[1:]:
            if abs(heights[other]-heights[first]) > 1 and abs(abs(heights[other]-expected)-abs(heights[first]-expected)) < 1:
                raise ValueError('ambiguous surface layers; move the anchor closer to the intended road')
        return first

    expected = float(point[1])
    if reference is not None:
        rows, heights = hits(reference[0], reference[2])
        row = int(rows[nearest(heights, reference[1])])
        expected = float(a[row, 1]-(normals[row, 0]*(point[0]-a[row, 0])+normals[row, 2]*(point[2]-a[row, 2]))/normals[row, 1])
    _, heights = hits(point[0], point[2])
    height = int(round(float(heights[nearest(heights, expected)])))+offset
    if not -32768 <= height <= 32767:
        raise ValueError('Surface placement exceeds signed16 height')
    return height


@dataclass(frozen=True)
class CoursePlan:
    level: int
    signature: str
    before: tuple[MapState,...]
    after: tuple[MapState,...]
    seeds: tuple[tuple[int,int],...]
    counters: tuple[tuple[int,int],...]
    selection: tuple[ObjectKey,...]
    issues: tuple[RouteIssue,...]
    changes: tuple[str,...]


def _point(point: tuple[float,...]) -> Position:
    if len(point)!=3 or not np.isfinite(point).all():
        raise ValueError('Position needs three finite coordinates')
    p=tuple(int(round(v)) for v in point)
    if any(v < -32768 or v > 32767 for v in p):
        raise ValueError('Course placement exceeds signed16 coordinates')
    return p


def yaw_byte(degrees: float) -> int:
    if not math.isfinite(degrees):raise ValueError('Heading must be finite')
    return int(round((degrees%360)/5.625))%64


def forward(yaw: int) -> np.ndarray:
    theta=(yaw%64)*math.tau/64
    # Local +Z is the checkpoint plane normal. Racers accelerate along -Z.
    return np.array([-math.sin(theta),0.,-math.cos(theta)],np.float64)


def route_heading(points: tuple[CoursePoint,...], index: int) -> int:
    p=np.asarray([v.position for v in points],np.float64)
    incoming=p[index]-p[(index-1)%len(p)]
    outgoing=p[(index+1)%len(p)]-p[index]
    incoming[1]=outgoing[1]=0
    a,b=np.linalg.norm(incoming),np.linalg.norm(outgoing)
    if a<1 or b<1:raise ValueError('Neighboring checkpoints need distinct X/Z positions')
    tangent=incoming/a+outgoing/b
    if np.linalg.norm(tangent)<1e-6:
        raise ValueError('A route doubles back by 180°; add a turning point before aligning headings')
    return yaw_byte(math.degrees(math.atan2(-tangent[0],-tangent[2])))


def grid_placement(options: GridOptions, terrain: TerrainSurface | None = None) -> GridPlacement:
    if (type(options.entrance) is not int or not 0<=options.entrance<=255
            or type(options.columns) is not int or not 1<=options.columns<=8
            or any(not math.isfinite(v) or v<=0 for v in (options.column_spacing,options.row_spacing))
            or not math.isfinite(options.stagger) or not 0<=options.stagger<=1
            or (options.vehicle is not None and (type(options.vehicle) is not int or options.vehicle not in (-1,0,1,2)))):
        raise ValueError('Choose a valid entrance, 1..8 columns, positive spacing, 0..1 stagger and vehicle')
    anchor=np.asarray(_point(options.anchor),np.float64)
    yaw=yaw_byte(options.yaw);heading=forward(yaw)
    theta=yaw*math.tau/64;right=np.array([math.cos(theta),0.,-math.sin(theta)])
    result=[];errors=[]
    for index in range(8):
        row,column=divmod(index,options.columns)
        lateral=(column-(options.columns-1)/2)*options.column_spacing
        behind=(row+(options.stagger if column%2 else 0))*options.row_spacing
        point=_point(tuple(anchor+right*lateral-heading*behind))
        if options.drop:
            try:
                if terrain is None:raise ValueError('no rendered surface near the position')
                height=surface_snap(terrain,point,reference=options.anchor,offset=options.height_offset,search=options.snap_range)
                point=point[0],height,point[2]
            except ValueError as error:
                errors.append((index,f'Racer {index+1}: {error}'))
        result.append(point)
    if len(set(result))!=8:raise ValueError('Grid spacing collapses racers onto the same position')
    return GridPlacement(tuple(result),tuple(errors))


def start_grid(options: GridOptions, terrain: TerrainSurface | None = None) -> tuple[Position,...]:
    placement=grid_placement(options,terrain)
    if placement.errors:raise ValueError(placement.errors[0][1])
    return placement.positions


def grid_before_checkpoint(points: tuple[CoursePoint,...], options: GridOptions,
                           terrain: TerrainSurface, clearance: int = 200) -> GridOptions:
    """Walk back along the approach, then check the entire straight grid footprint."""
    if len(points)<4:raise ValueError('Place at least four route points first')
    if type(clearance) is not int or not 1<=clearance<=4000:
        raise ValueError('Grid clearance must be 1..4000 units')
    route=np.asarray([v.position for v in (points[0],*reversed(points[1:]))],np.float64)
    lengths=np.linalg.norm(np.diff(route,axis=0)[:,[0,2]],axis=1)
    if np.any(lengths<1):raise ValueError('Neighboring checkpoints need distinct X/Z positions')
    cumulative=np.r_[0.,np.cumsum(lengths)]
    cp0=np.asarray(points[0].position);normal=forward(route_heading(points,0))
    for distance in range(clearance,min(clearance+2001,int(cumulative[-1])),100):
        leg=min(int(np.searchsorted(cumulative,distance,side='right'))-1,len(lengths)-1)
        fraction=(distance-cumulative[leg])/lengths[leg]
        anchor=_point(tuple(route[leg]+fraction*(route[leg+1]-route[leg])))
        toward=route[leg]-route[leg+1]
        yaw=yaw_byte(math.degrees(math.atan2(-toward[0],-toward[2])))
        candidate=replace(options,anchor=anchor,yaw=yaw*5.625)
        placement=grid_placement(replace(candidate,drop=True),terrain)
        if not placement.errors and all(float((np.asarray(p)-cp0)@normal)<-1 for p in placement.positions):
            return candidate
    raise ValueError('The whole grid does not fit on the approach before CP0. Reduce spacing or place and aim it manually.')


def level_objects(session: EditSession, level: int) -> tuple[LevelObject,...]:
    h=session.level_header(level)
    maps=tuple(dict.fromkeys(i for i in (h.object_map_id,h.secondary_object_map_id) if i>=0))
    return tuple(o for m in maps for o in session.current_map(m).objects)


def route_points(objects: tuple[LevelObject,...], group: int) -> tuple[CoursePoint,...]:
    return tuple(CoursePoint(o.position,o.key) for o in sorted(
        (o for o in objects if o.definition.behavior_id==13 and o.value('vehicleType')==group and not o.value('isAltCheckpoint')),
        key=lambda o:(o.value('index'),o.key)))


def course_diagnostics(objects: tuple[LevelObject,...], sets: tuple[int,int,int],
                       terrain: TerrainSurface | None = None, *, active_set: int | None = None,
                       entrance: int | None = None) -> tuple[RouteIssue,...]:
    issues=list(route_diagnostics(objects,sets))
    groups=sorted(set(sets)|{int(o.value('vehicleType')) for o in objects if o.definition.behavior_id==13})
    for group in groups:
        main=sorted((o for o in objects if o.definition.behavior_id==13 and o.value('vehicleType')==group and not o.value('isAltCheckpoint')),key=lambda o:o.value('index'))
        if len(main)<4:
            issues.append(RouteIssue('short-course',f'Set {group}: fewer than four main checkpoints; review the closed spline.',tuple(o.key for o in main)))
        for i,o in enumerate(main):
            next_o=main[(i+1)%len(main)]
            delta=np.asarray(next_o.position,np.float64)-o.position
            horizontal=np.linalg.norm(delta[[0,2]])
            if horizontal<1:
                issues.append(RouteIssue('coincident-checkpoints',f'Set {group}, CP {o.value("index")}: next checkpoint shares its X/Z.',(o.key,next_o.key)))
            else:
                for node in (o,next_o):
                    dot=abs(float(forward(int(node.value('angleY')))@delta))/horizontal
                    if dot<.05:
                        issues.append(RouteIssue('parallel-plane',f'Set {group}, CP {node.value("index")}: crossing plane is nearly parallel to this route leg; review heading.',(node.key,)))
            if terrain is not None:
                for lane in range(4):
                    point=tuple(int(round(v)) for v in lane_point(o,lane))
                    if terrain.surface_y(point,drop=True) is None:
                        issues.append(RouteIssue('lane-no-floor',f'Set {group}, CP {o.value("index")}, lane {lane}: no rendered floor below target; check height/width or intended flight.',(o.key,)))
    entrances=sorted({int(o.value('entranceID')) for o in objects if o.definition.behavior_id==11}|({entrance} if entrance is not None else {0}))
    main_route=route_points(objects,sets[0] if active_set is None else active_set)
    travel=None;crossing_normal=None
    if len(main_route)>=4:
        try:
            travel=forward(route_heading(main_route,0))
            cp0=next(o for o in objects if o.key==main_route[0].key)
            crossing_normal=forward(int(cp0.value('angleY')))
            if float(crossing_normal@travel)<0:crossing_normal=-crossing_normal
        except ValueError:pass
    for entrance in entrances:
        grid=[o for o in objects if o.definition.behavior_id==11 and o.value('entranceID')==entrance]
        for index in range(8):
            matches=[o for o in grid if o.value('racerIndex')==index]
            if len(matches)!=1:
                issues.append(RouteIssue('start-index',f'Entrance {entrance}, racer {index}: {len(matches)} setup points; expected one.',tuple(o.key for o in matches)))
        for o in grid:
            if o.value('racerIndex')>=8:issues.append(RouteIssue('start-index',f'Entrance {entrance}: racer index {o.value("racerIndex")} is outside 0..7.',(o.key,)))
            if terrain is not None and terrain.surface_y(o.position,drop=True) is None:
                issues.append(RouteIssue('start-no-floor',f'Entrance {entrance}, racer {o.value("racerIndex")}: no rendered floor below start.',(o.key,)))
        overrides={o.value('vehicle') for o in grid if o.value('vehicle')!=-1}
        if len(overrides)>1:issues.append(RouteIssue('start-vehicles',f'Entrance {entrance}: conflicting vehicle overrides; the last loaded matching point wins.',tuple(o.key for o in grid)))
        if travel is not None:
            for o in grid:
                if float((np.asarray(o.position)-main_route[0].position)@crossing_normal)>=-1:
                    issues.append(RouteIssue('start-after-cp0',f'Entrance {entrance}, racer {o.value("racerIndex")+1}: on or beyond CP0. Move the grid farther back.',(o.key,)))
                if float(forward(int(o.value('angleY')))@travel)<=0:
                    issues.append(RouteIssue('start-direction',f'Entrance {entrance}, racer {o.value("racerIndex")+1}: faces away from the approach to CP0. Rotate the grid 180° or aim it toward CP0.',(o.key,)))
    return tuple(dict.fromkeys(issues))


def plan_objects(session: EditSession, plan: CoursePlan) -> tuple[LevelObject,...]:
    states={s.map_id:s for s in plan.after}
    h=session.level_header(plan.level)
    result=[]
    for m in dict.fromkeys(i for i in (h.object_map_id,h.secondary_object_map_id) if i>=0):
        state=states.get(m)
        model=identify(ObjectMap.from_bytes(state.raw,session.database,map_id=m),state.identities) if state else session.current_map(m)
        result.extend(model.objects)
    return tuple(result)


def build_course_plan(session: EditSession, level: int, points: tuple[CoursePoint,...],
                      options: CourseOptions, grid: GridOptions | None = None, *, edit_route: bool = True,
                      validate: bool = True) -> CoursePlan:
    session._require_idle()
    h=session.level_header(level)
    maps=tuple(dict.fromkeys(i for i in (h.object_map_id,h.secondary_object_map_id) if i>=0))
    if options.map_id not in maps:raise ValueError('Choose a map loaded by the selected level')
    if (type(options.set_id) is not int or not -128<=options.set_id<=127 or type(options.scale) is not int or not 5<=options.scale<=255
            or not math.isfinite(options.lane_half_width) or options.lane_half_width<0):
        raise ValueError('Invalid checkpoint set, scale or lane half-width')
    if edit_route and not 4<=len(points)<=60:raise ValueError('Author a closed course with 4..60 main checkpoints')
    all_objects=level_objects(session,level);all_lookup={o.key:o for o in all_objects}
    if len(set(options.remove_keys))!=len(options.remove_keys) or any(k not in all_lookup for k in options.remove_keys):
        raise ValueError('Cleanup must select distinct objects from the two loaded level maps')
    copies=tuple(dict.fromkeys(options.copy_sets))
    if any(type(g) is not int or not -128<=g<=127 for g in copies):raise ValueError('Invalid copied checkpoint set')
    removed_keys=set(options.remove_keys)
    objects=tuple(o for o in all_objects if o.key not in removed_keys);lookup={o.key:o for o in objects}
    before=tuple(session._map_state(m) for m in maps)
    entries={m:[(o.index,o.raw_data) for o in session.current_map(m).objects if o.key not in removed_keys] for m in maps}
    identities={s.map_id:[i for i in s.identities if (s.map_id,i.value) not in removed_keys] for s in before}
    seeds={m:session._next_identity.get(m,len(session.original_map(m).objects)) for m in maps}
    counters=dict(seeds);selected=[];changes=[]
    if removed_keys:changes.append(f'Cleanup: remove {len(removed_keys)} placed objects across {len({k[0] for k in removed_keys})} map(s).')
    terrain=TerrainSurface.from_model(session.track_model(h.geometry_id))
    def update(obj: LevelObject,raw: bytes) -> None:
        entries[obj.map_id]=[(i,raw if i==obj.index else r) for i,r in entries[obj.map_id]]
        selected.append(obj.key)
    def append(behavior: int,position: Position,parameters: dict[str,int]) -> None:
        template=next((t for t in session.object_catalog if session.database.resolve(t.object_id).behavior_id==behavior and t.map_id is not None),None)
        if template is None:raise ValueError('No verified stock entry template for this course object')
        raw=template.raw(session)
        model=ObjectMap.from_bytes(struct.pack('>I',len(raw))+bytes(12)+raw+bytes(-len(raw)%8),session.database,map_id=options.map_id)
        raw=patch_entry(model.objects[0],position=position,parameters=parameters)
        serial=counters[options.map_id]
        if serial>=MAX_IDENTITY:raise ValueError('Stable object identity counter exhausted')
        counters[options.map_id]+=1
        entries[options.map_id].append((serial,raw))
        identities[options.map_id].append(EntryIdentity(serial,template,raw))
        selected.append((options.map_id,serial))
    if edit_route:
        keys=[p.key for p in points if p.key is not None]
        if len(set(keys))!=len(keys):raise ValueError('A checkpoint cannot occupy two sequence rows')
        for p in points:
            _point(p.position)
            if p.key is not None and (p.key not in lookup or lookup[p.key].definition.behavior_id!=13 or lookup[p.key].value('vehicleType')!=options.set_id or lookup[p.key].value('isAltCheckpoint')):
                raise ValueError('Course rows must use main checkpoints from the selected set')
        old_main=[o for o in objects if o.definition.behavior_id==13 and o.value('vehicleType')==options.set_id and not o.value('isAltCheckpoint')]
        remap={int(lookup[p.key].value('index')):i for i,p in enumerate(points) if p.key is not None}
        if len(remap)!=len(keys):raise ValueError('Main checkpoint indexes are duplicated; resolve them before paired renumbering')
        alternates=[o for o in objects if o.definition.behavior_id==13 and o.value('vehicleType')==options.set_id and o.value('isAltCheckpoint')]
        if not options.remove_alternates and len(points)+len(alternates)>60:
            raise ValueError('Selected set exceeds 60 checkpoints including retained alternates')
        removed={o.key for o in old_main if o.key not in keys}
        if options.remove_alternates:removed.update(o.key for o in alternates)
        else:
            for o in alternates:
                if o.value('index') not in remap:raise ValueError('A retained alternate loses its paired main checkpoint; retain that main or explicitly remove alternates')
                update(o,patch_entry(o,parameters={'index':remap[o.value('index')]}))
        for m in maps:
            entries[m]=[(i,r) for i,r in entries[m] if (m,i) not in removed]
            identities[m]=[v for v in identities[m] if (m,v.value) not in removed]
        for i,p in enumerate(points):
            position=_point(p.position)
            if options.drop:
                height=terrain.surface_y(position,drop=True,offset=options.height_offset)
                if height is None:raise ValueError(f'Checkpoint {i}: no rendered floor below origin')
                position=position[0],height,position[2]
            params={'index':i}
            if options.align_headings or p.key is None:params['angleY']=route_heading(points,i)
            if options.reset_lanes or p.key is None:
                lateral=tuple(round(v*options.lane_half_width/(options.scale/32)) for v in (-1,-1/3,1/3,1))
                if any(v < -128 or v > 127 for v in lateral):raise ValueError('Lane half-width exceeds the signed8 offset range at this scale')
                params.update(dict(zip(LATERAL,lateral))|{field:0 for field in HEIGHT+BEHAVIOR}|{'scale':options.scale})
            if p.key is None:
                params.update({'vehicleType':options.set_id,'isAltCheckpoint':0,'unk19':0})
                append(13,position,params)
            else:update(lookup[p.key],patch_entry(lookup[p.key],position=position,parameters=params))
        changes.append(f'Set {options.set_id}: {len(old_main)} → {len(points)} main checkpoints; indexes 0..{len(points)-1}; {len(alternates) if options.remove_alternates else 0} alternates removed.')
        if any(lookup[k].value('unk19') for k in keys):changes.append('Existing HUD turn cues and special bytes are retained; review cues after reordering.')
        for group in copies:
            if group==options.set_id:continue
            old={o.key for o in objects if o.definition.behavior_id==13 and o.value('vehicleType')==group}
            for m in maps:
                entries[m]=[(i,r) for i,r in entries[m] if (m,i) not in old]
                identities[m]=[v for v in identities[m] if (m,v.value) not in old]
            # Explicitly copied sets get the same geometry and neutral lane defaults.
            for i,p in enumerate(points):
                position=_point(p.position)
                if options.drop:
                    height=terrain.surface_y(position,drop=True,offset=options.height_offset)
                    if height is None:raise ValueError(f'Checkpoint {i}: no rendered floor below origin')
                    position=position[0],height,position[2]
                lateral=tuple(round(v*options.lane_half_width/(options.scale/32)) for v in (-1,-1/3,1/3,1))
                if any(not -128<=v<=127 for v in lateral):raise ValueError('Lane half-width exceeds the signed8 offset range at this scale')
                params={'index':i,'angleY':route_heading(points,i),'scale':options.scale,'vehicleType':group,'isAltCheckpoint':0,'unk19':0}
                params.update(dict(zip(LATERAL,lateral))|{f:0 for f in HEIGHT+BEHAVIOR})
                append(13,position,params)
            changes.append(f'Set {group}: replace with a copy of the new {len(points)}-checkpoint route for mapped vehicles.')
    if grid is not None:
        starts=[o for o in objects if o.definition.behavior_id==11 and o.value('entranceID')==grid.entrance]
        if any(sum(o.value('racerIndex')==index for o in starts)>1 for index in range(8)) or any(o.value('racerIndex')>=8 for o in starts):
            raise ValueError('Resolve duplicate/invalid racer indexes in the target entrance before laying out its grid')
        positions=start_grid(grid,terrain)
        for index,position in enumerate(positions):
            existing=next((o for o in starts if o.value('racerIndex')==index),None)
            params={'angleY':yaw_byte(grid.yaw)}
            if grid.vehicle is not None:params['vehicle']=grid.vehicle
            if existing:update(existing,patch_entry(existing,position=position,parameters=params))
            else:append(11,position,params|{'racerIndex':index,'entranceID':grid.entrance,'vehicle':grid.vehicle if grid.vehicle is not None else -1})
        changes.append(f'Entrance {grid.entrance}: 8 starts, {grid.columns} columns; stored heading {yaw_byte(grid.yaw)*5.625:g}°.')
    after=tuple(MapState(m,rebuild(session,m,tuple(r for _,r in entries[m])),tuple(identities[m])) for m in maps)
    if validate:validate_capacity(session,after)
    plan=CoursePlan(level,session._signature(),before,after,tuple(seeds.items()),tuple(counters.items()),tuple(dict.fromkeys(selected)),(),tuple(changes))
    issues=course_diagnostics(plan_objects(session,plan),h.checkpoint_sets,terrain,active_set=options.set_id,
                              entrance=grid.entrance if grid else None)
    return replace(plan,issues=issues)


def validate_plan_current(session: EditSession, plan: CoursePlan) -> None:
    if session._signature()!=plan.signature or any(session._map_state(s.map_id)!=s for s in plan.before) or any(session._next_identity.get(m,len(session.original_map(m).objects))!=i for m,i in plan.seeds):
        raise ValueError('Course preview is stale; build it again before applying')


def preview_course_plan(session: EditSession, plan: CoursePlan) -> ExportReport:
    from src.core.editing import compress_object_map
    validate_plan_current(session,plan);validate_capacity(session,plan.after)
    session._validate_map_references({s.map_id:identify(ObjectMap.from_bytes(s.raw,session.database,map_id=s.map_id),s.identities) for s in plan.after})
    sections,old_report=session._prepare_export()
    previous_layout_errors=make_export_report(session.rom,sections,old_report.assets).errors
    sections=list(sections);table=AssetTable.parse(sections[20],len(sections[21]))
    replacements={s.map_id:(session.rom.read_asset(AssetType.LEVEL_OBJECT_MAPS,s.map_id)
        if s.raw==raw_map(session.original_map(s.map_id)) else compress_object_map(s.raw)) for s in plan.after}
    chunks=[];offsets=[0]
    for index in range(len(table)):
        span=table.span(index);chunk=replacements.get(index,sections[21][span.start:span.end])
        chunks.append(chunk);offsets.append(offsets[-1]+len(chunk))
    chunks.append(sections[21][table.offsets[-1]:]);sections[21]=b''.join(chunks)
    lookup=bytearray(sections[20]);struct.pack_into('>'+str(len(offsets))+'I',lookup,0,*offsets);sections[20]=bytes(lookup)
    diffs=tuple(d for d in old_report.assets if not(d.section==21 and d.index in replacements))
    for state in plan.after:
        old=next(s for s in plan.before if s.map_id==state.map_id)
        # Include pre-existing edits in either loaded map even if the course
        # leaves that map alone. Conversely, a draft restoring stock bytes must
        # remove its former diff and reuse the original compressed span.
        original=raw_map(session.original_map(state.map_id))
        if original==state.raw:continue
        existing=next((d for d in old_report.assets if d.section==21 and d.index==state.map_id),None)
        changes=plan.changes if old.raw!=state.raw else existing.changes if existing else ()
        uses=tuple(f'{l.index}: {l.name}' for l in session._catalog.levels if state.map_id in (session.level_header(l.index).object_map_id,session.level_header(l.index).secondary_object_map_id))
        diffs+=(AssetDiff(21,state.map_id,f'Course object map {state.map_id}',len(original),len(state.raw),len(session.rom.read_asset(AssetType.LEVEL_OBJECT_MAPS,state.map_id)),len(replacements[state.map_id]),uses,changes),)
    report=make_export_report(session.rom,tuple(sections),diffs)
    # Preserve unrelated existing failures; a valid course draft cannot waive
    # another asset writer's protection or runtime-workspace refusal.
    report=report.retain_validation_errors(old_report,previous_layout_errors)
    if not report.can_export:raise ValueError('; '.join(report.errors))
    return report
