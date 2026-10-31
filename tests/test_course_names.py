"""Name codec/table, staged edits, narrow writer permissions and ROM isolation."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import pytest

from src.core.course_names import (NameRecord,load_name_fonts,encode_name,edit_names,
    validate_name_edit,prepare_name_sections,plan_names,name_warnings)
from src.core.editing import EditSession
from src.core.rom import RomImage,AssetType,AssetTable,LUT_START,LUT_END,parse_asset_lut
from src.core.level_header import load_level_catalog


@pytest.fixture(scope='module')
def rom():return RomImage.from_file(next(Path.cwd().glob('*.z64')))


@pytest.mark.parametrize('index',range(65))
def test_every_stock_name_roundtrips_without_reencoding_other_languages(rom,index):
    raw=rom.read_asset(AssetType.LEVEL_NAMES,index);record=NameRecord.parse(raw)
    assert b''.join(record.strings)+record.tail==raw
    fonts=load_name_fonts(rom.section(AssetType.FONTS))
    assert edit_names(raw,raw,{},fonts)==raw
    assert edit_names(raw,raw,{k:getattr(record.values,k) for k in ('english','german','french')},fonts)==raw


def test_font_layout_and_width_from_rom(rom):
    fonts=load_name_fonts(rom.section(AssetType.FONTS))
    assert [f.name for f in fonts]==['FunFont','SmallFont','BigFont']
    assert fonts[0].space==6 and fonts[1].space==3 and fonts[2].space==8
    assert fonts[2].width(' ')==8
    assert encode_name('Sunset Circuit',fonts)==b'Sunset Circuit\0'


@pytest.mark.parametrize('raw',[b'',bytes(3),struct.pack('>I',2)+bytes(0x800),struct.pack('>I',999)+bytes(0x1000)])
def test_truncated_font_metadata_refused(raw):
    with pytest.raises(ValueError):load_name_fonts(raw)


@pytest.mark.parametrize('text',['A'*64,'bad\0name','bad\nname','bad\tname','Café','雪','A🙂','A\x7f','Track 2'])
def test_invalid_or_missing_glyph_names_refused_without_history(rom,text):
    s=EditSession(rom);before=s._signature()
    with pytest.raises(ValueError):s.set_course_names(5,{'english':text})
    assert s._signature()==before and not s.can_undo and s.build_rom()==rom.data


def test_changed_language_preserves_exact_other_strings_and_opaque_tail(rom):
    s=EditSession(rom);base=s.original_asset(AssetType.LEVEL_NAMES,5)+b'\x91opaque\x00'
    raw=edit_names(base,base,{'english':'Sunset Circuit'},s.name_fonts)
    before,after=NameRecord.parse(base),NameRecord.parse(raw)
    assert before.strings[1:]==after.strings[1:] and after.tail==before.tail
    assert after.values.english=='Sunset Circuit'
    with pytest.raises(ValueError):edit_names(base,raw,{'japanese':'A'},s.name_fonts)
    with pytest.raises(ValueError):validate_name_edit(base,b''.join(after.strings[:3])+b'other\0'+after.tail,s.name_fonts)
    with pytest.raises(ValueError):validate_name_edit(base,raw[:-1],s.name_fonts)


@pytest.mark.parametrize('raw',[b'only\0one',b'one\0two\0three\0\x80',b'one\0two\0three\0\x81\xff\0'])
def test_malformed_name_records_refused(raw):
    with pytest.raises(ValueError):NameRecord.parse(raw)


def test_table_rebuild_retains_count_sentinel_other_records_and_tails(rom):
    table,data,diffs=prepare_name_sections(rom,{})
    assert (table,data)==(rom.section(24),rom.section(25)) and not diffs
    s=EditSession(rom);old=rom.index_table(AssetType.LEVEL_NAMES)
    raw=edit_names(s.original_asset(AssetType.LEVEL_NAMES,5),s.original_asset(AssetType.LEVEL_NAMES,5),{'english':'Sunset Circuit'},s.name_fonts)
    table,data,diffs=prepare_name_sections(rom,{5:raw})
    new=AssetTable.parse(table,len(data))
    assert len(new)==len(old)==65 and len(data)%16==0
    assert table[len(old.offsets)*4:]==rom.section(24)[len(old.offsets)*4:]
    assert data[new.offsets[-1]:].startswith(rom.section(25)[old.offsets[-1]:])
    for i in range(65):
        span=new.span(i)
        assert data[span.start:span.end]==(raw if i==5 else rom.read_asset(AssetType.LEVEL_NAMES,i))
    assert [d.index for d in diffs]==[5]


def test_atomic_multicourse_plan_history_reopen_and_name_only_rom_changes(rom,tmp_path):
    s=EditSession(rom);before=s._signature()
    plan=plan_names(s,{5:{'english':'Sunset Circuit','french':'CIRCUIT SOLEIL'},0:{'english':'New Central Area'}})
    assert s._signature()==before and not s.can_undo
    assert plan.ram_after-plan.ram_before==sum(len(b)-len(a) for (_,a),(_,b) in zip(plan.before,plan.after))
    assert s.apply_course_names(plan) and s.undo_label=='Edit course names'
    assert s.course_names(5).english==s._catalog.levels[5].name=='Sunset Circuit'
    assert s.export_report().projected_end==plan.report.projected_end
    signature=s._signature();s.undo();assert s._signature()==before and s._catalog.levels[5].name=='Ancient Lake'
    s.redo();assert s._signature()==signature
    path=s.save_project(tmp_path/'names.dkrproj',5);document=json.loads(path.read_text())
    assert document['version']==12 and len(document['course_names'])==2
    assert all(a['section']!=25 for a in document['asset_edits'])
    loaded=EditSession.load_project(path)
    assert loaded._signature()==signature and loaded._catalog.levels[5].name=='Sunset Circuit'
    data=loaded.build_rom();out=RomImage(data,'z64',parse_asset_lut(data,LUT_START,LUT_END))
    assert load_level_catalog(out).levels[5].name=='Sunset Circuit'
    for i in range(len(rom.sections)):
        if i not in (24,25):assert out.section(i)==rom.section(i)
    for i in range(65):
        if i not in (0,5):assert out.read_asset(AssetType.LEVEL_NAMES,i)==rom.read_asset(AssetType.LEVEL_NAMES,i)


def test_revert_names_preserves_other_edits_and_returns_stock_bytes(rom):
    s=EditSession(rom);base=s.course_names(5)
    s.set_level_field(5,'laps',2);signature=s._signature()
    s.set_course_names(5,{'english':'Sunset Circuit'})
    assert s.set_course_names(5,{k:getattr(base,k) for k in ('english','german','french')})
    assert s._signature()==signature and s.project_document()['version']==6
    assert not s.set_course_names(5,{'english':base.english})
    assert s.level_header(5).laps==2


def test_long_and_blank_names_report_display_warnings(rom):
    s=EditSession(rom);plan=plan_names(s,{5:{'english':'W'*63,'french':''}})
    assert any('320' in w for w in plan.warnings) and any('blank' in w for w in plan.warnings)
    assert plan.report.can_export


def test_stale_and_capacity_refused_plan_cannot_change_data_or_history(rom,monkeypatch):
    from src.core import course_names
    s=EditSession(rom);plan=plan_names(s,{5:{'english':'Sunset Circuit'}})
    s.set_level_field(5,'laps',2);signature=s._signature(),s._cursor
    with pytest.raises(ValueError,match='stale'):s.apply_course_names(plan)
    assert (s._signature(),s._cursor)==signature
    original=course_names.make_export_report
    def refuse(*args,**kwargs):return replace(original(*args,**kwargs),errors=('Capacity test refusal',))
    monkeypatch.setattr(course_names,'make_export_report',refuse)
    with pytest.raises(ValueError,match='refusal'):s.set_course_names(5,{'english':'Sunset Circuit'})
    assert (s._signature(),s._cursor)==signature


@pytest.mark.parametrize('version',range(1,12))
def test_legacy_project_versions_cannot_gain_name_writer(rom,tmp_path,version):
    s=EditSession(rom);s.set_course_names(5,{'english':'Sunset Circuit'})
    doc=s.project_document();doc['version']=version
    path=tmp_path/'legacy.dkrproj';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):EditSession.load_project(path)


@pytest.mark.parametrize('bad',['duplicate','hash','encoding','hex','size','index','japanese','tail','asset-patch','text-asset'])
def test_malformed_name_projects_rejected(rom,tmp_path,bad):
    s=EditSession(rom);s.set_course_names(5,{'english':'Sunset Circuit'});doc=s.project_document();row=doc['course_names'][0]
    if bad=='duplicate':doc['course_names'].append(dict(row))
    if bad=='hash':row['base_asset_sha1']='0'*40
    if bad=='encoding':row['encoding']='menu-text'
    if bad=='hex':row['data']='zz'
    if bad=='size':row['data']='00'*10000
    if bad=='index':row['index']=65
    if bad=='japanese':
        rec=NameRecord.parse(bytes.fromhex(row['data']));row['data']=(b''.join(rec.strings[:3])+b'A\0'+rec.tail).hex()
    if bad=='tail':row['data']+='00'
    if bad in ('asset-patch','text-asset'):
        doc['asset_edits']=[{'section':25 if bad=='asset-patch' else 8,'index':5,'encoding':'raw','bytes':[]}]
    path=tmp_path/'bad.dkrproj';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):EditSession.load_project(path)
