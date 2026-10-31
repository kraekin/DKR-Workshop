"""Fresh-course transactions, nearby surface layers and start readiness, no Qt/GL."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.core.course import (CourseOptions, CoursePoint, GridOptions, build_course_plan,
    course_diagnostics, forward, grid_before_checkpoint, grid_placement, level_objects,
    plan_objects, preview_course_plan, route_heading, route_points, start_grid, surface_snap)
from src.core.editing import EditSession
from src.core.placement import TerrainSurface
from src.core.rom import AssetType, RomImage, LUT_START, LUT_END, parse_asset_lut


@pytest.fixture(scope='module')
def rom():
    return RomImage.from_file(next(Path.cwd().glob('*.z64')))


def floor(height=0., slope=0., extent=5000.):
    a=(-extent,height-slope*extent,-extent)
    b=(extent,height+slope*extent,-extent)
    c=(extent,height+slope*extent,extent)
    d=(-extent,height-slope*extent,extent)
    return TerrainSurface(np.array([[a,b,c],[a,c,d]],np.float64))


def square():
    return tuple(CoursePoint(p) for p in ((0,32,0),(2000,32,0),(2000,32,2000),(0,32,2000)))


def test_grid_snaps_both_sides_of_a_slope_and_preserves_offset():
    terrain=floor(slope=.2)
    positions=start_grid(GridOptions((0,0,0)),terrain)
    assert len(positions)==8
    assert all(y==round(x*.2)+8 for x,y,z in positions)
    assert positions[0][1]<0<positions[1][1]


@pytest.mark.parametrize('layer',[0,250])
def test_grid_stays_on_clicked_bridge_layer(layer):
    terrain=TerrainSurface(np.concatenate((floor().triangles,floor(250).triangles)))
    positions=start_grid(GridOptions((0,layer,0)),terrain)
    assert {p[1] for p in positions}=={layer+8}


def test_snap_uses_anchor_slope_instead_of_switching_to_nearer_parallel_deck():
    terrain=TerrainSurface(np.concatenate((floor(slope=.5).triangles,floor(100,slope=.5).triangles)))
    assert surface_snap(terrain,(300,0,0),reference=(0,0,0),offset=8)==158


def test_ambiguous_bridge_and_remote_height_are_refused():
    terrain=TerrainSurface(np.concatenate((floor().triangles,floor(100).triangles)))
    with pytest.raises(ValueError,match='ambiguous'):
        surface_snap(terrain,(0,50,0))
    with pytest.raises(ValueError,match='no rendered surface'):
        surface_snap(floor(),(0,2000,0))
    with pytest.raises(ValueError,match='positive'):
        surface_snap(floor(),(0,0,0),search=float('nan'))


def test_partial_grid_errors_retain_all_eight_numbered_preview_positions():
    placement=grid_placement(GridOptions((4950,0,0)),floor())
    assert len(placement.positions)==8
    assert {i for i,_ in placement.errors}=={1,3,5,7}
    assert all('surface' in message for _,message in placement.errors)
    with pytest.raises(ValueError,match='Racer 2'):
        start_grid(GridOptions((4950,0,0)),floor())


def test_fit_grid_walks_actual_approach_and_checks_all_starts_before_cp0():
    points=square()
    result=grid_before_checkpoint(points,GridOptions((0,0,0)),floor(),300)
    assert result.anchor[0]==0 and result.anchor[2]>=300
    assert result.yaw==0
    travel=forward(route_heading(points,0))
    assert all((np.array(p)-points[0].position)@travel<0 for p in start_grid(result,floor()))


def test_fit_refuses_when_entire_grid_has_no_road():
    with pytest.raises(ValueError,match='whole grid'):
        grid_before_checkpoint(square(),GridOptions((0,0,0)),floor(extent=10))


@pytest.mark.parametrize('clearance',[0,4001,1.5])
def test_fit_clearance_bounds(clearance):
    with pytest.raises(ValueError,match='clearance'):
        grid_before_checkpoint(square(),GridOptions((0,0,0)),floor(),clearance)


def test_fresh_course_removes_both_maps_and_rebuilds_every_mapped_set_atomically(rom,tmp_path):
    session=EditSession(rom)
    original_objects=level_objects(session,5)
    header=session.level_header(5)
    maps=tuple(dict.fromkeys(o.map_id for o in original_objects))
    assert len(maps)==2
    first=original_objects[0]
    session.set_note(first.key,'position:X','cleanup must undo this note too')
    signature=session._signature()
    cursor=session._cursor
    options=CourseOptions(header.checkpoint_sets[0],maps[0],remove_keys=tuple(o.key for o in original_objects),copy_sets=tuple(set(header.checkpoint_sets)))
    plan=build_course_plan(session,5,square(),options,GridOptions((0,50,200),drop=False))
    assert session._signature()==signature and session._cursor==cursor
    preview=preview_course_plan(session,plan)
    assert preview.can_export
    output=plan_objects(session,plan)
    assert len(output)==8+4*len(set(header.checkpoint_sets))
    assert all(o.definition.behavior_id in (11,13) for o in output)
    assert all(len(route_points(output,g))==4 for g in header.checkpoint_sets)
    assert not {o.key for o in output}&{o.key for o in original_objects}
    assert session.apply_course_plan(plan)
    assert session.undo_label=='Build course' and session._cursor==cursor+1
    after=session._signature()
    assert not session.note(first.key,'position:X').text
    path=session.save_project(tmp_path/'fresh.dkrproj',5)
    reopened=EditSession.load_project(path)
    assert reopened._signature()==after
    session.undo()
    assert session._signature()==signature and session.note(first.key,'position:X').text
    session.redo()
    assert session._signature()==after
    data=session.build_rom()
    out=RomImage(data,'z64',parse_asset_lut(data,LUT_START,LUT_END))
    for section in range(len(rom.sections)):
        if section not in (20,21):
            assert out.section(section)==rom.section(section)
    for m in range(rom.count(AssetType.LEVEL_OBJECT_MAPS)):
        if m not in maps:
            assert out.read_asset(AssetType.LEVEL_OBJECT_MAPS,m)==rom.read_asset(AssetType.LEVEL_OBJECT_MAPS,m)


def test_selective_cleanup_retains_unselected_objects_and_parameters(rom):
    session=EditSession(rom)
    objects=level_objects(session,5)
    keys=tuple(o.key for o in objects if o.category=='Scenery')
    plan=build_course_plan(session,5,(),CourseOptions(0,5,remove_keys=keys),edit_route=False)
    output={o.key:o.raw_data for o in plan_objects(session,plan)}
    assert not set(keys)&output.keys()
    assert all(output[o.key]==o.raw_data for o in objects if o.key not in keys)


def test_fresh_copies_keep_edited_header_references_valid_without_intermediate_deletion(rom):
    session=EditSession(rom)
    template=next(t for t in session.object_catalog if session.database.resolve(t.object_id).behavior_id==13)
    key=session.add_object(5,template,(0,32,0))
    session.set_parameter(key,'vehicleType',7)
    session.set_parameter(key,'isAltCheckpoint',0)
    session.set_level_field(5,'checkpoint_sets',(7,7,7))
    before=session._signature()
    before_maps=tuple(session._map_state(m) for m in (5,73))
    options=CourseOptions(0,5,remove_keys=tuple(o.key for o in level_objects(session,5)),copy_sets=(7,))
    plan=build_course_plan(session,5,square(),options,GridOptions((0,50,200),drop=False))
    assert preview_course_plan(session,plan).can_export
    session.apply_course_plan(plan)
    assert session.level_header(5).checkpoint_sets==(7,7,7)
    assert len(route_points(level_objects(session,5),7))==4
    session.undo()
    # Monotonic identity seeds are intentionally consumed even after undo.
    assert tuple(session._map_state(m) for m in (5,73))==before_maps
    assert session.level_header(5).checkpoint_sets==(7,7,7)


@pytest.mark.parametrize('kind',['duplicate','foreign','retained-row','copy-range'])
def test_invalid_cleanup_or_copy_plan_leaves_session_and_identity_counters_intact(rom,kind):
    session=EditSession(rom)
    points=route_points(level_objects(session,5),0)
    options=CourseOptions(0,5)
    if kind=='duplicate':options=replace(options,remove_keys=(points[0].key,points[0].key))
    if kind=='foreign':options=replace(options,remove_keys=((999,0),))
    if kind=='retained-row':options=replace(options,remove_keys=(points[0].key,))
    if kind=='copy-range':options=replace(options,copy_sets=(128,))
    before=session._signature(),dict(session._next_identity)
    with pytest.raises(ValueError):
        build_course_plan(session,5,points,options)
    assert (session._signature(),session._next_identity)==before and not session.can_undo


def test_lightweight_live_plan_defers_compression_capacity_validation(rom,monkeypatch):
    from src.core import course
    session=EditSession(rom)
    monkeypatch.setattr(course,'validate_capacity',lambda *args:pytest.fail('Expensive capacity check in live preview'))
    plan=build_course_plan(session,5,square(),CourseOptions(0,5),validate=False)
    assert len(route_points(plan_objects(session,plan),0))==4 and not session.can_undo


def test_readiness_warns_for_grid_past_cp0_and_wrong_direction(rom):
    session=EditSession(rom)
    all_keys=tuple(o.key for o in level_objects(session,5))
    plan=build_course_plan(session,5,square(),CourseOptions(0,5,remove_keys=all_keys),GridOptions((0,32,-200),yaw=180,drop=False))
    issues=course_diagnostics(plan_objects(session,plan),(0,0,0))
    assert any(i.code=='start-after-cp0' for i in issues)
    assert any(i.code=='start-direction' for i in issues)


def test_empty_course_cannot_be_reported_as_ready():
    codes=[issue.code for issue in course_diagnostics((),(0,1,0))]
    assert codes.count('short-course')==2 and codes.count('start-index')==8


def test_start_side_uses_stored_cp0_plane_rather_than_inferred_tangent(rom):
    session=EditSession(rom)
    keys=tuple(o.key for o in level_objects(session,5))
    plan=build_course_plan(session,5,square(),CourseOptions(0,5,remove_keys=keys),GridOptions((200,32,100),drop=False))
    objects=[]
    for obj in plan_objects(session,plan):
        if obj.definition.behavior_id==13 and obj.value('index')==0:
            obj=replace(obj,parameters=tuple(replace(p,value=0) if p.name=='angleY' else p for p in obj.parameters))
        objects.append(obj)
    issues=course_diagnostics(tuple(objects),(0,0,0))
    assert not any(i.code=='start-after-cp0' for i in issues)
