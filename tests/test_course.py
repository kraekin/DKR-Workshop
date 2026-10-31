"""Course authoring: explicit plans, source limits, identities and ROM isolation."""
from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.course import (CoursePoint,CourseOptions,GridOptions,build_course_plan,
    preview_course_plan,plan_objects,level_objects,route_points,yaw_byte,forward,
    route_heading,start_grid,course_diagnostics)
from src.core.rom import RomImage,AssetType,LUT_START,LUT_END,parse_asset_lut
from src.core.placement import TerrainSurface


@pytest.fixture(scope='module')
def rom():return RomImage.from_file(next(Path.cwd().glob('*.z64')))


def options(s):return CourseOptions(0,5)


def points(s):return route_points(level_objects(s,5),0)


@pytest.mark.parametrize('angle,expected',[(0,(0,0,-1)),(90,(-1,0,0)),(180,(0,0,1)),(270,(1,0,0)),(360,(0,0,-1)),(-90,(1,0,0))])
def test_racer_forward_and_quantized_yaw(angle,expected):
    assert np.allclose(forward(yaw_byte(angle)),expected)
    assert yaw_byte(angle+5.625)==(yaw_byte(angle)+1)%64


def test_grid_is_indexed_front_to_back_and_quantized():
    g=GridOptions((0,100,0),drop=False,column_spacing=120,row_spacing=140)
    p=start_grid(g)
    assert p[:4]==((-60,100,0),(60,100,0),(-60,100,140),(60,100,140))
    assert p[-1]==(60,100,420)
    turned=start_grid(replace(g,yaw=90))
    assert turned[2]==(140,100,60)
    stagger=start_grid(replace(g,stagger=.5))
    assert stagger[1]==(60,100,70)


@pytest.mark.parametrize('g',[GridOptions((32767,0,0),drop=False),GridOptions((0,0,0),columns=0),
    GridOptions((0,0,0),row_spacing=0),GridOptions((0,0,0),stagger=2),GridOptions((0,0,0),yaw=float('nan')),
    GridOptions((0,0,0),vehicle=10),GridOptions((0,0,0),entrance=256)])
def test_invalid_grids_refused(g):
    with pytest.raises(ValueError):start_grid(g)


def test_grid_requires_ground_below_and_preserves_offset(rom):
    s=EditSession(rom);terrain=TerrainSurface.from_model(s.track_model(5))
    p=start_grid(GridOptions((-1670,300,-6480)),terrain)
    assert all(-32768<=c<=32767 for v in p for c in v)
    with pytest.raises(ValueError,match='surface'):start_grid(GridOptions((30000,1000,30000)),terrain)


def test_route_plan_reorder_preserves_unknowns_other_sets_and_notes(rom):
    s=EditSession(rom);p=points(s);old={o.key:o for o in level_objects(s,5)}
    s.set_note(p[0].key,'index','finish marker')
    signature=s._signature();cursor=s._cursor
    ordered=(p[0],*reversed(p[1:]))
    plan=build_course_plan(s,5,ordered,options(s))
    report=preview_course_plan(s,plan)
    assert report.can_export and s._signature()==signature and s._cursor==cursor
    assert s.apply_course_plan(plan)
    for i,row in enumerate(ordered):
        a,b=old[row.key],s.object(row.key)
        assert b.value('index')==i
        assert all(x==y for j,(x,y) in enumerate(zip(a.raw_data,b.raw_data)) if j!=9)
    for key,obj in old.items():
        if key not in {p.key for p in ordered}:assert s.object(key).raw_data==obj.raw_data
    assert s.note(p[0].key,'index').text=='finish marker'
    s.undo();assert s._signature()==signature
    s.redo();assert s.object(ordered[-1].key).value('index')==len(ordered)-1


def test_new_points_existing_starts_atomic_history_project_and_rom(rom,tmp_path):
    s=EditSession(rom);old={o.key:o.raw_data for o in level_objects(s,5)}
    p=points(s);p=(*p[:3],CoursePoint(tuple((np.array(p[2].position)+p[3].position)//2)),*p[3:])
    plan=build_course_plan(s,5,p,options(s),GridOptions((-1670,300,-6480)))
    pre=preview_course_plan(s,plan);signature=s._signature()
    s.apply_course_plan(plan)
    assert s.export_report().projected_end==pre.projected_end
    assert len(level_objects(s,5))==len(old)+1 and s.undo_label=='Build course'
    current=s._signature();keys={o.key for o in level_objects(s,5)}
    s.undo();assert s._signature()==signature
    s.redo();assert s._signature()==current and {o.key for o in level_objects(s,5)}==keys
    path=s.save_project(tmp_path/'course.dkrproj',5);loaded=EditSession.load_project(path)
    assert loaded._signature()==s._signature()
    data=s.build_rom();out=RomImage(data,'z64',parse_asset_lut(data,LUT_START,LUT_END))
    for i in range(len(rom.sections)):
        if i not in (20,21):assert out.section(i)==rom.section(i)
    changed={a.map_id for a,b in zip(plan.before,plan.after) if a.raw!=b.raw}
    for m in range(rom.count(AssetType.LEVEL_OBJECT_MAPS)):
        if m not in changed:assert out.read_asset(AssetType.LEVEL_OBJECT_MAPS,m)==rom.read_asset(AssetType.LEVEL_OBJECT_MAPS,m)


def test_alt_pair_renumbered_and_deletion_requires_explicit_option(rom):
    s=EditSession(rom);p=points(s)
    template=next(t for t in s.object_catalog if s.database.resolve(t.object_id).behavior_id==13)
    alt=s.add_object(73,template,(-1800,100,-7500))
    s.set_parameter(alt,'vehicleType',0);s.set_parameter(alt,'index',s.object(p[1].key).value('index'));s.set_parameter(alt,'isAltCheckpoint',1)
    ordered=(p[0],*reversed(p[1:]))
    plan=build_course_plan(s,5,ordered,options(s))
    changed=next(o for o in plan_objects(s,plan) if o.key==alt)
    assert changed.value('index')==len(p)-1
    with pytest.raises(ValueError,match='paired'):
        build_course_plan(s,5,tuple(v for v in p if v.key!=p[1].key),options(s))
    plan=build_course_plan(s,5,tuple(v for v in p if v.key!=p[1].key),replace(options(s),remove_alternates=True))
    assert alt not in {o.key for o in plan_objects(s,plan)}


@pytest.mark.parametrize('kind',['point-count','duplicate-key','wrong-type','coordinates','lanes','set','map','capacity'])
def test_refused_plans_preserve_session(rom,kind):
    s=EditSession(rom);p=points(s);o=options(s);signature=s._signature()
    if kind=='point-count':p=p[:3]
    if kind=='duplicate-key':p=(p[0],p[0],*p[2:])
    if kind=='wrong-type':p=(CoursePoint(p[0].position,(73,0)),*p[1:])
    if kind=='coordinates':p=(CoursePoint((40000,0,0)),*p[1:])
    if kind=='lanes':o=replace(o,reset_lanes=True,lane_half_width=100000)
    if kind=='set':o=replace(o,set_id=128)
    if kind=='map':o=replace(o,map_id=99)
    if kind=='capacity':p=tuple(CoursePoint((i,0,i*10)) for i in range(61))
    with pytest.raises(ValueError):build_course_plan(s,5,p,o)
    assert s._signature()==signature and not s.can_undo


def test_stale_plan_rejected_and_new_grid_entrance_preserves_old(rom):
    s=EditSession(rom);p=points(s)
    plan=build_course_plan(s,5,p,options(s),GridOptions((-1670,300,-6480),entrance=7))
    old=tuple(o.raw_data for o in level_objects(s,5) if o.definition.behavior_id==11)
    s.set_position(p[0].key,(-1500,100,-7600))
    with pytest.raises(ValueError,match='stale'):s.apply_course_plan(plan)
    s.undo()
    s.apply_course_plan(plan)
    starts=[o for o in level_objects(s,5) if o.definition.behavior_id==11]
    assert tuple(o.raw_data for o in starts if o.value('entranceID')==0)==old
    assert sorted(o.value('racerIndex') for o in starts if o.value('entranceID')==7)==list(range(8))


def test_grid_only_plan_and_no_op(rom):
    s=EditSession(rom)
    plan=build_course_plan(s,5,(),options(s),None,edit_route=False)
    assert not s.apply_course_plan(plan) and not s.dirty
    plan=build_course_plan(s,5,(),options(s),GridOptions((-1670,300,-6480)),edit_route=False)
    cps=tuple(o.raw_data for o in level_objects(s,5) if o.definition.behavior_id==13)
    s.apply_course_plan(plan)
    assert tuple(o.raw_data for o in level_objects(s,5) if o.definition.behavior_id==13)==cps


def test_headings_and_lanes_only_change_requested_fields(rom):
    s=EditSession(rom);p=points(s)
    plan=build_course_plan(s,5,p,replace(options(s),align_headings=True,reset_lanes=True))
    objs={o.key:o for o in plan_objects(s,plan)}
    for i,row in enumerate(p):
        assert objs[row.key].value('angleY')==route_heading(p,i)
        assert [objs[row.key].value(v) for v in ('unk13','unk14','unk15','unk16')]==[0]*4
        assert objs[row.key].value('unk18')==s.object(row.key).value('unk18')


def test_diagnostics_report_real_duplicate_and_floor_problems(rom):
    s=EditSession(rom);o=level_objects(s,5)
    first=next(v for v in o if v.definition.behavior_id==11)
    issues=course_diagnostics((*o,replace(first,index=99999)),s.level_header(5).checkpoint_sets)
    assert any(i.code=='start-index' and first.key in i.keys for i in issues)
    empty=course_diagnostics((),(0,0,0))
    assert any(i.code=='short-course' for i in empty)
    assert any(i.code=='start-index' for i in empty)


def test_sixty_entry_limit_counts_retained_alternates(rom):
    s=EditSession(rom);p=points(s)
    template=next(t for t in s.object_catalog if s.database.resolve(t.object_id).behavior_id==13)
    alt=s.add_object(73,template,(-1800,100,-7500))
    for name,value in {'vehicleType':0,'index':s.object(p[0].key).value('index'),'isAltCheckpoint':1}.items():s.set_parameter(alt,name,value)
    draft=(*p,*(CoursePoint((i*100,100,i*50)) for i in range(60-len(p))))
    signature=s._signature(),s._cursor
    with pytest.raises(ValueError,match='including retained alternates'):build_course_plan(s,5,draft,options(s))
    assert (s._signature(),s._cursor)==signature


def test_duplicate_start_index_refused_without_modifying_either_map(rom):
    s=EditSession(rom);start=next(o for o in level_objects(s,5) if o.definition.behavior_id==11)
    s.duplicate_objects((start.key,))
    signature=s._signature(),s._cursor
    with pytest.raises(ValueError,match='duplicate/invalid racer'):build_course_plan(s,5,(),options(s),GridOptions((-1670,300,-6480)),edit_route=False)
    assert (s._signature(),s._cursor)==signature


def test_consumed_identity_invalidates_plan_even_after_undo(rom):
    s=EditSession(rom);p=points(s)
    plan=build_course_plan(s,5,(*p,CoursePoint((-1700,100,-7000))),options(s))
    signature=s._signature()
    s.duplicate_objects((p[0].key,));s.undo()
    assert s._signature()==signature
    with pytest.raises(ValueError,match='stale'):s.apply_course_plan(plan)
    assert s._signature()==signature and not s.can_undo


def test_entire_new_course_has_neutral_lanes_and_retains_other_objects(rom):
    s=EditSession(rom);p=points(s)
    draft=tuple(CoursePoint(p[i].position) for i in (0,4,8,12))
    old={o.key:o.raw_data for o in level_objects(s,5) if o.definition.behavior_id!=13 or o.value('vehicleType')!=0}
    plan=build_course_plan(s,5,draft,options(s))
    report=preview_course_plan(s,plan)
    affected={l.index for l in s._catalog.levels if 5 in (s.level_header(l.index).object_map_id,s.level_header(l.index).secondary_object_map_id)}
    assert {int(label.split(':')[0]) for a in report.assets if a.index==5 for label in a.levels}==affected
    s.apply_course_plan(plan)
    route=route_points(level_objects(s,5),0)
    assert len(route)==4 and all(row.key not in {v.key for v in p} for row in route)
    for row in route:
        obj=s.object(row.key)
        assert obj.value('unk19')==0 and all(obj.value(f'unk{i:X}')==0 for i in range(0xF,0x17))
    assert all(s.object(k).raw_data==raw for k,raw in old.items())


def test_grid_vehicle_override_is_explicit(rom):
    s=EditSession(rom);start=next(o for o in level_objects(s,5) if o.definition.behavior_id==11)
    s.set_parameter(start.key,'vehicle',1)
    grid=GridOptions((-1670,300,-6480))
    plan=build_course_plan(s,5,(),options(s),grid,edit_route=False)
    assert next(o for o in plan_objects(s,plan) if o.key==start.key).value('vehicle')==1
    plan=build_course_plan(s,5,(),options(s),replace(grid,vehicle=-1),edit_route=False)
    assert all(o.value('vehicle')==-1 for o in plan_objects(s,plan) if o.definition.behavior_id==11 and o.value('entranceID')==0)


def test_budget_refusal_leaves_history_and_identity_seeds_untouched(rom,monkeypatch):
    from src.core import course
    original=course.make_export_report
    s=EditSession(rom);p=points(s)
    plan=build_course_plan(s,5,(*p,CoursePoint((-1700,100,-7000))),options(s))
    signature=s._signature(),dict(s._next_identity)
    def refuse(*args,**kwargs):return replace(original(*args,**kwargs),errors=('Capacity test refusal',))
    monkeypatch.setattr(course,'make_export_report',refuse)
    with pytest.raises(ValueError,match='refusal'):s.apply_course_plan(plan)
    assert (s._signature(),s._next_identity)==signature and not s.can_undo


def test_every_loaded_stock_level_accepts_read_only_diagnostics_and_noop(rom):
    s=EditSession(rom);checked=0
    for level in s._catalog.levels:
        h=s.level_header(level.index)
        maps=[i for i in (h.object_map_id,h.secondary_object_map_id) if i>=0]
        if not maps or h.geometry_id<0:continue
        plan=build_course_plan(s,level.index,(),CourseOptions(h.checkpoint_sets[0],maps[0]),edit_route=False)
        assert plan.before==plan.after and not s.dirty and not s.can_undo
        checked+=1
    assert checked>=50


def test_preview_keeps_prior_other_map_diff_and_removes_restored_stock_map(rom):
    s=EditSession(rom);p=points(s)
    secondary=next(o for o in level_objects(s,5) if o.map_id==73)
    s.set_position(secondary.key,(secondary.position[0]+1,*secondary.position[1:]))
    initial=s.export_report()
    noop=build_course_plan(s,5,(),options(s),edit_route=False)
    report=preview_course_plan(s,noop)
    assert report.projected_end==initial.projected_end
    assert {a.index for a in report.assets if a.section==21}=={73}
    assert next(a for a in report.assets if a.section==21).changes==next(a for a in initial.assets if a.section==21).changes
    # Exercise an exact stock candidate at the structural preflight boundary.
    # Ancient Lake's sparse stock indexes would otherwise also be renumbered.
    from src.core.structure import raw_map
    o=s.object(p[0].key);s.set_position(o.key,(o.position[0],o.position[1]+5,o.position[2]))
    plan=build_course_plan(s,5,(),options(s),edit_route=False)
    plan=replace(plan,after=tuple(replace(state,raw=raw_map(s.original_map(5))) if state.map_id==5 else state for state in plan.after))
    report=preview_course_plan(s,plan)
    assert {a.index for a in report.assets if a.section==21}=={73}
    s.apply_course_plan(plan)
    assert report.projected_end==s.export_report().projected_end
