"""Lossless USA Rev1 course-name editing; no menu/dialogue text writers.

Sources: game.c:114–124/642–674, font.h:34–57, font.c:719–758,
menu.c:8715–8775/12602–12654, text/dkrText.cpp in the local decomp.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import TYPE_CHECKING

from src.core.level_header import LANGUAGES, LevelNames
from src.core.rom import AssetType, AssetTable, RomImage
from src.core.export_report import AssetDiff, ExportReport, make_export_report

if TYPE_CHECKING:
    from src.core.editing import EditSession

EDITABLE_LANGUAGES = ('english','german','french')
MAX_NAME_BYTES = 63  # menu.c's non-JP ghost-name buffer/copy, including separate NUL.
SCREEN_WIDTH = 320


@dataclass(frozen=True)
class NameRecord:
    values: LevelNames
    strings: tuple[bytes,...]  # Includes each terminator, preserving DKRJP encoding.
    tail: bytes

    @classmethod
    def parse(cls, raw: bytes) -> NameRecord:
        values=LevelNames.from_bytes(raw)
        strings=[];offset=0
        for _ in LANGUAGES:
            start=offset
            while offset<len(raw):
                value=raw[offset];offset+=1
                if value==0:break
                if value&0x80:offset+=1
            strings.append(raw[start:offset])
        return cls(values,tuple(strings),raw[offset:])


@dataclass(frozen=True)
class NameFont:
    name: str
    fixed: int
    space: int
    texture_ids: tuple[int,...]
    advances: tuple[int,...]

    def width(self, text: str) -> int:
        return sum(self.space if c==' ' else (self.fixed or self.advances[ord(c)-32])
            if 33<=ord(c)<128 and self.texture_ids[ord(c)-32]!=255 else 0 for c in text)


def load_name_fonts(raw: bytes) -> tuple[NameFont,...]:
    """Read only the verified 0x400-byte Latin font metadata, not its images."""
    if len(raw)<4:raise ValueError('Truncated font metadata')
    count=struct.unpack_from('>I',raw)[0]
    if count<3 or 4+count*0x400>len(raw):raise ValueError('Invalid font record count/size')
    result=[]
    for i in range(3):  # FunFont entry banners, SmallFont ghost list, BigFont titles.
        start=4+i*0x400
        fixed,_,space,_=struct.unpack_from('>4H',raw,start+0x20)
        result.append(NameFont(raw[start:start+32].split(b'\0',1)[0].decode('ascii'),fixed,space,
            tuple(raw[start+0x100+j*8] for j in range(96)),
            tuple(raw[start+0x101+j*8] for j in range(96))))
    return tuple(result)


def encode_name(text: str, fonts: tuple[NameFont,...]) -> bytes:
    if not isinstance(text,str):raise ValueError('Course names must be text')
    if any(not 32<=ord(c)<=126 for c in text):
        raise ValueError('Use printable ASCII characters; accents, control codes and newlines are unsupported in USA Rev1 names')
    if len(text)>MAX_NAME_BYTES:raise ValueError(f'Course names must be at most {MAX_NAME_BYTES} bytes')
    for font in fonts:
        missing=''.join(dict.fromkeys(c for c in text if c!=' ' and font.texture_ids[ord(c)-32]==255))
        if missing:raise ValueError(f'{font.name} has no glyph for {missing!r}; use letters, spaces or supported punctuation')
    return text.encode('ascii')+b'\0'


def validate_name_edit(base: bytes, raw: bytes, fonts: tuple[NameFont,...]) -> NameRecord:
    if not isinstance(raw,bytes) or len(raw)>len(base)+3*(MAX_NAME_BYTES+1):
        raise ValueError('Invalid course-name record size')
    old,new=NameRecord.parse(base),NameRecord.parse(raw)
    if old.strings[3]!=new.strings[3] or old.tail!=new.tail:
        raise ValueError('Japanese name bytes and opaque name-record tails must be retained')
    for i,key in enumerate(EDITABLE_LANGUAGES):
        if new.strings[i]!=old.strings[i] and encode_name(getattr(new.values,key),fonts)!=new.strings[i]:
            raise ValueError('Noncanonical Latin course-name encoding')
    return new


def edit_names(base: bytes, current: bytes, changes: dict[str,str], fonts: tuple[NameFont,...]) -> bytes:
    if not isinstance(changes,dict) or any(k not in EDITABLE_LANGUAGES for k in changes):
        raise ValueError('Only English, German and French course names are editable')
    old=NameRecord.parse(base);now=validate_name_edit(base,current,fonts)
    strings=list(now.strings)
    for key,value in changes.items():
        i=EDITABLE_LANGUAGES.index(key)
        # Exact reversion reuses original bytes, including legacy glyph choices.
        strings[i]=old.strings[i] if value==getattr(old.values,key) else encode_name(value,fonts)
    raw=b''.join(strings)+now.tail
    validate_name_edit(base,raw,fonts)
    return raw


def name_warnings(record: NameRecord, fonts: tuple[NameFont,...]) -> tuple[str,...]:
    warnings=[]
    for key in EDITABLE_LANGUAGES:
        value=getattr(record.values,key)
        if not value.strip():warnings.append(f'{key.title()}: blank course label')
        width=fonts[2].width(value)
        if width>SCREEN_WIDTH:warnings.append(f'{key.title()}: BigFont width {width} px exceeds the 320 px screen; centered titles may clip')
    return tuple(warnings)


def prepare_name_sections(rom: RomImage, updates: dict[int,bytes]) -> tuple[bytes,bytes,tuple[AssetDiff,...]]:
    """Rebuild only sections24/25; preserve entry bytes, table sentinel and tails."""
    table=rom.index_table(AssetType.LEVEL_NAMES)
    if any(type(i) is not int or not 0<=i<len(table) for i in updates):raise ValueError('Invalid course ID')
    data=rom.section(AssetType.LEVEL_NAMES);offsets=[table.offsets[0]]
    chunks=[data[:offsets[0]]];diffs=[]
    for i in range(len(table)):
        base=rom.read_asset(AssetType.LEVEL_NAMES,i);raw=updates.get(i,base)
        chunks.append(raw);offsets.append(offsets[-1]+len(raw))
        if raw!=base:
            old,new=NameRecord.parse(base),NameRecord.parse(raw)
            fields=tuple(f'{key.title()}: {getattr(old.values,key)!r} → {getattr(new.values,key)!r}'
                for key in EDITABLE_LANGUAGES if old.strings[EDITABLE_LANGUAGES.index(key)]!=new.strings[EDITABLE_LANGUAGES.index(key)])
            diffs.append(AssetDiff(25,i,f'Course name {i}',len(base),len(raw),len(base),len(raw),
                (f'{i}: {new.values.english or "(blank)"}',),fields))
    chunks.append(data[table.offsets[-1]:])
    packed=b''.join(chunks)
    # Never append alignment to a no-op: preserve exact original section bytes.
    if packed!=data:packed+=bytes(-len(packed)%16)
    lookup=bytearray(rom.section(AssetType.LEVEL_NAMES_TABLE))
    struct.pack_into('>'+str(len(offsets))+'I',lookup,0,*offsets)
    AssetTable.parse(bytes(lookup),len(packed))
    return bytes(lookup),packed,tuple(diffs)


@dataclass(frozen=True)
class NamePlan:
    signature: str
    before: tuple[tuple[int,bytes],...]
    after: tuple[tuple[int,bytes],...]
    report: ExportReport
    ram_before: int
    ram_after: int
    warnings: tuple[str,...]


def plan_names(session: EditSession, changes: dict[int,dict[str,str]]) -> NamePlan:
    session._require_idle()
    updates={};warnings=[]
    for index,fields in changes.items():
        if type(index) is not int or not 0<=index<session.rom.count(AssetType.LEVEL_NAMES):raise ValueError('Invalid course ID')
        raw=edit_names(session.original_asset(AssetType.LEVEL_NAMES,index),session.current_asset(AssetType.LEVEL_NAMES,index),fields,session.name_fonts)
        if raw!=session.current_asset(AssetType.LEVEL_NAMES,index):updates[index]=raw
        warnings.extend(f'Course {index}: {w}' for w in name_warnings(NameRecord.parse(raw),session.name_fonts))
    signature=session._signature()
    sections,old_report=session._prepare_export()
    previous_layout_errors=make_export_report(session.rom,sections,old_report.assets).errors
    sections=list(sections)
    all_updates={i:raw for (s,i),raw in session._assets.items() if s==AssetType.LEVEL_NAMES}|updates
    table,data,diffs=prepare_name_sections(session.rom,all_updates)
    original=session.rom.index_table(AssetType.LEVEL_NAMES)
    current=AssetTable.parse(sections[24],len(sections[25]))
    final=AssetTable.parse(table,len(data));sections[24],sections[25]=table,data
    report=make_export_report(session.rom,tuple(sections),tuple(d for d in old_report.assets if d.section!=25)+diffs)
    report=report.retain_validation_errors(old_report,previous_layout_errors)
    if not report.can_export:raise ValueError('; '.join(report.errors))
    if original.offsets[0]!=0:raise ValueError('Unexpected name-table base offset')
    before=tuple((i,session.current_asset(AssetType.LEVEL_NAMES,i)) for i in sorted(updates))
    return NamePlan(signature,before,tuple(sorted(updates.items())),report,
        current.offsets[-1]-current.offsets[0],final.offsets[-1]-final.offsets[0],tuple(warnings))
