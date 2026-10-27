"""Lossless object/header/material edits, projects and ROM rebuilding, without Qt/GL.

Layouts: include/level_object_entries.h, buildObjectMap.cpp, asset_loading.c.
Compression: DKRCompression.cpp. Checksums: local tools/n64crc.c:92-163.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from typing import Any
import zlib

from src.core.objects import LevelObject, ObjectDatabase, ObjectMap, load_object_database, load_object_map
from src.core.object_models import ObjectModel
from src.core.object_dependencies import DefinitionUse, definition_dependencies
from src.core.rom import AssetTable, AssetType, LUT_END, LUT_START, REV1_SHA1, RomImage, parse_asset_lut
from src.core.export_report import AssetDiff, ExportReport, make_export_report
from src.core.level_header import LevelHeader, LevelNames, load_level_catalog
from src.core.level_settings import (LEVEL_FIELDS, FIELD_BY_KEY, LevelReferences,
                                     SettingValue, base_references, validate_header_edit, write_field)
from src.core.research import FieldNote, RESULTS, research_fields
from src.core.level_model import LevelModel
from src.core.geometry import (VertexKey, Position, move_vertices, copy_geometry,
    geometry_changed, geometry_changes, verify_geometry_stream)
from src.core.materials import (MaterialEdit, TextureReference, texture_references,
                                edit_materials, material_changes)
from src.core.minimap import (SpriteReference, sprite_references, edit_minimap,
                              validate_model_edit, copy_minimap, minimap_changes)
from src.core.image_assets import (TEXTURE_SECTIONS, IMAGE_SECTIONS, unpack_texture, pack_texture,
    texture_from_raw, replace_frame, validate_texture_edit, validate_sprite_edit, edit_anchor,
    edit_timing, sprite_canvas, split_sprite_png)
from src.core.image_usage import ImageUses, build_image_uses
from src.core.textures import Texture, Pixels
from src.core.object_structure import (ObjectTemplate, EntryIdentity, MapState, StructureChange,
    MAX_IDENTITY, base_identities, identify, rebuild, validate_state, validate_capacity,
    catalog as object_catalog, diagnostics as structural_diagnostics)
from src.core.track_import import validate_import_runtime
from src.core.track_segments import import_project_version, validate_segmented_runtime, compress_segmented_track
from src.core.track_artwork import texture_pool_refs, validate_custom_texture
from src.core.course import CoursePlan, preview_course_plan, validate_plan_current
from src.core.course_names import (NameFont, NamePlan, NameRecord, EDITABLE_LANGUAGES,
    load_name_fonts, validate_name_edit, plan_names, prepare_name_sections)
from src.core.global_objects import (ObjectResources, GlobalObjectPlan,
    validate_definition, definition_uses, global_diff)
from src.core.model_editing import (MODEL_ASSETS, ModelPlan, validate_asset as validate_object_art,
    prepare_sections as prepare_object_art, plan_models)

ObjectKey = tuple[int, int]
AssetKey = tuple[AssetType, int]
# Writable assets require format-specific validation before installation.
WRITABLE_FIXED_ASSETS: frozenset[AssetType] = frozenset({AssetType.LEVEL_HEADERS, AssetType.OBJECTS})
WRITABLE_ASSETS = WRITABLE_FIXED_ASSETS | {AssetType.LEVEL_MODELS, AssetType.LEVEL_NAMES} | IMAGE_SECTIONS | MODEL_ASSETS


class EditError(ValueError):
    """Invalid edit, project or export destination."""


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise EditError(f"Value must be an integer in {minimum}..{maximum}")
    return value


def compress_asset(raw: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = struct.pack("<IB", len(raw), 9) + compressor.compress(raw) + compressor.flush()
    return packed + bytes((-len(packed)) % 16)


def compress_object_map(raw: bytes) -> bytes:
    return compress_asset(raw)


def n64_checksums(data: bytes | bytearray) -> tuple[int, int]:
    """Unsigned32 port of local n64crc.c; detect CIC from the preserved bootcode."""
    if len(data) < 0x101000:
        raise EditError("ROM is too short for N64 checksum verification")
    cic = {0x6170A4A1: 6101, 0x90BB6CB5: 6102, 0x0B050EE0: 6103,
           0x98BC2C86: 6105, 0xACC8580A: 6106}.get(zlib.crc32(data[0x40:0x1000]))
    seeds = {6101: 0xF8CA4DDC, 6102: 0xF8CA4DDC, 6103: 0xA3886759,
             6105: 0xDF26F436, 6106: 0x1FEA617A}
    if cic not in seeds:
        raise EditError("Unrecognized N64 bootcode/CIC")
    mask = 0xFFFFFFFF
    t1 = t2 = t3 = t4 = t5 = t6 = seeds[cic]
    for index, (word,) in enumerate(struct.iter_unpack(">I", data[0x1000:0x101000])):
        total = t6 + word
        if total > mask:
            t4 = (t4 + 1) & mask
        t6 = total & mask
        t3 ^= word
        shift = word & 31
        rotated = ((word << shift) | (word >> ((32 - shift) & 31))) & mask
        t5 = (t5 + rotated) & mask
        t2 ^= rotated if t2 > word else t6 ^ word
        extra = struct.unpack_from(">I", data, 0x750 + ((0x1000 + index * 4) & 255))[0] if cic == 6105 else t5
        t1 = (t1 + (extra ^ word)) & mask
    if cic == 6103:
        return ((t6 ^ t4) + t3) & mask, ((t5 ^ t2) + t1) & mask
    if cic == 6106:
        return ((t6 * t4) + t3) & mask, ((t5 * t2) + t1) & mask
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def _raw_map(model: ObjectMap) -> bytes:
    return model.header + b"".join(obj.raw_data or b"" for obj in model.objects) + model.padding


def _assemble_rom(rom: RomImage, sections: tuple[bytes, ...], report: ExportReport) -> bytes:
    """Shared bounded byte assembly; callers separately authorize asset changes."""
    if not report.can_export:
        raise EditError('; '.join(report.errors))
    blob = b''.join(sections)
    end = LUT_END+len(blob)
    old_end = rom.sections[-1].end
    if end > len(rom.data) or any(value not in (0, 255) for value in rom.data[old_end:end]):
        raise EditError("Edited assets exceed the original ROM's available padding")
    result = bytearray(rom.data)
    result[LUT_END:end] = blob
    relative = [0]
    for section in sections:
        relative.append(relative[-1]+len(section))
    struct.pack_into('>'+str(len(relative))+'I', result, LUT_START+4, *relative)
    struct.pack_into('>2I', result, 0x10, *n64_checksums(result))
    spans = parse_asset_lut(result, LUT_START, LUT_END)
    for span, expected in zip(spans, sections):
        if result[span.start:span.end] != expected:
            raise EditError('ROM export section validation failed')
    return bytes(result)


def _atomic_write(path: Path, payload: bytes, base_path: Path | None) -> Path:
    destination = path.resolve()
    if base_path is not None and destination == base_path.resolve():
        raise EditError("Choose a new file; the original ROM is read-only")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".dkr-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        temporary.replace(destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


@dataclass(frozen=True)
class EditChange:
    key: ObjectKey
    before: bytes
    after: bytes
    label: str


@dataclass(frozen=True)
class MovePreview:
    key: ObjectKey
    before: bytes


@dataclass(frozen=True)
class AssetChange:
    key: AssetKey
    before: bytes
    after: bytes
    label: str


@dataclass(frozen=True)
class AssetGroupChange:
    keys: tuple[AssetKey, ...]
    before: tuple[bytes, ...]
    after: tuple[bytes, ...]
    label: str


@dataclass(frozen=True)
class TrackImportChange:
    index: int
    before: bytes
    before_base: bytes | None
    after: bytes
    after_base: bytes | None
    label: str
    before_textures: tuple[bytes, ...] | None = None
    after_textures: tuple[bytes, ...] | None = None
    removed_texture_edits: tuple[tuple[AssetKey, bytes], ...] = ()


@dataclass(frozen=True)
class GroupChange:
    keys: tuple[ObjectKey, ...]
    before: tuple[tuple[int, bytes], ...]
    after: tuple[tuple[int, bytes], ...]
    label: str


@dataclass(frozen=True)
class GroupPreview:
    keys: tuple[ObjectKey, ...]
    before: tuple[tuple[int, bytes], ...]
    label: str


@dataclass(frozen=True)
class ResearchChange:
    key: ObjectKey | None
    field: str
    before: FieldNote | str
    after: FieldNote | str
    label: str


class EditSession:
    """Verified base ROM, reversible existing-asset overlays and shared history."""

    def __init__(self, rom: RomImage, database: ObjectDatabase | None = None) -> None:
        if hashlib.sha1(rom.data).hexdigest() != REV1_SHA1:
            raise EditError("Editing requires the verified original USA Rev 1 base ROM")
        self.rom = rom
        self.database = database if database is not None else load_object_database(rom)
        self._originals: dict[int, ObjectMap] = {}
        self._modified: dict[int, bytes] = {}
        self._assets: dict[AssetKey, bytes] = {}
        self._track_imports: dict[int, bytes] = {}
        self._custom_textures: tuple[bytes, ...] = ()
        self._custom_refs: tuple[TextureReference, ...] = ()
        self._model_originals: dict[int, bytes] = {}
        self._model_parsed: dict[int, tuple[bytes, LevelModel]] = {}
        self._material_refs: tuple[TextureReference, ...] | None = None
        self._minimap_refs: tuple[SpriteReference, ...] | None = None
        self._asset_packed_cache: dict[AssetKey, tuple[bytes, bytes]] = {}
        self._image_originals: dict[AssetKey, bytes] = {}
        self._image_uses: ImageUses | None = None
        self._definition_uses: dict[int, DefinitionUse] | None = None
        self._original_object_models: dict[int, ObjectModel] = {}
        self._parsed: dict[int, ObjectMap] = {}
        self._notes: dict[tuple[int, int, str], FieldNote] = {}
        self._structures: dict[int, tuple[EntryIdentity, ...]] = {}
        self._next_identity: dict[int, int] = {}
        self._object_catalog: tuple[ObjectTemplate, ...] | None = None
        self._name_fonts: tuple[NameFont,...] | None = None
        self._object_resources: ObjectResources | None = None
        self.structure_warnings: tuple[str, ...] = ()
        self.experiment_name = ""
        self._history: list[EditChange | AssetChange | AssetGroupChange | TrackImportChange | GroupChange | ResearchChange | StructureChange] = []
        self._cursor = 0
        self._move: MovePreview | None = None
        self._group: GroupPreview | None = None
        self._saved_signature = self._signature()
        self.last_key: ObjectKey | None = None
        self.last_asset_key: AssetKey | None = None
        self.last_keys: tuple[ObjectKey, ...] = ()
        self.project_path: Path | None = None
        self.selected_level = 0
        self._report_cache: tuple[str, tuple[bytes, ...], ExportReport] | None = None
        self._packed_cache: dict[int, tuple[bytes, bytes]] = {}
        self._catalog = load_level_catalog(rom)
        self._level_references = base_references(rom, self._catalog, self.database)
        self.asset_source = EditedRom(self)

    def original_map(self, map_id: int) -> ObjectMap:
        _integer(map_id, 0, self.rom.count(AssetType.LEVEL_OBJECT_MAPS) - 1)
        if map_id not in self._originals:
            self._originals[map_id] = load_object_map(self.rom, map_id, self.database)
        return self._originals[map_id]

    def current_map(self, map_id: int) -> ObjectMap:
        if map_id not in self._modified:
            original = self.original_map(map_id)
            return identify(original, self._structures[map_id]) if map_id in self._structures else original
        if map_id not in self._parsed:
            parsed = ObjectMap.from_bytes(self._modified[map_id], self.database, map_id=map_id)
            self._parsed[map_id] = identify(parsed, self._structures[map_id]) if map_id in self._structures else parsed
        return self._parsed[map_id]

    def object(self, key: ObjectKey) -> LevelObject:
        model = self.current_map(key[0])
        _integer(key[1], 0, MAX_IDENTITY-1)
        obj = next((obj for obj in model.objects if obj.index == key[1]), None)
        if obj is None:
            raise EditError('Object identity is absent from this map')
        return obj

    @property
    def object_catalog(self) -> tuple[ObjectTemplate, ...]:
        if self._object_catalog is None:
            self._object_catalog = object_catalog(self)
        return self._object_catalog

    def _map_state(self, map_id: int) -> MapState:
        return MapState(map_id, _raw_map(self.current_map(map_id)),
            self._structures.get(map_id, base_identities(self, map_id)))

    def _install_states(self, states: tuple[MapState, ...]) -> None:
        models = tuple(validate_state(self, state) for state in states)
        self._validate_map_references({state.map_id: model for state, model in zip(states, models)})
        for state, parsed in zip(states, models):
            if state.identities == base_identities(self, state.map_id):
                self._structures.pop(state.map_id, None)
            else:
                self._structures[state.map_id] = state.identities
            if state.raw == _raw_map(self.original_map(state.map_id)):
                self._modified.pop(state.map_id, None)
            else:
                self._modified[state.map_id] = state.raw
            self._parsed[state.map_id] = parsed
        self._image_uses = None
        self._definition_uses = None

    def _commit_structure(self, before: tuple[MapState, ...], after: tuple[MapState, ...],
            selection_before: tuple[ObjectKey, ...], selection_after: tuple[ObjectKey, ...], label: str) -> None:
        validate_capacity(self, after)
        notes_before = tuple(sorted(self._notes.items()))
        self._install_states(after)
        active = {obj.key for state in after for obj in self.current_map(state.map_id).objects}
        changed_maps = {state.map_id for state in after}
        self._notes = {key: value for key, value in self._notes.items() if key[0] not in changed_maps or key[:2] in active}
        self._history[self._cursor:] = [StructureChange(before, after, notes_before,
            tuple(sorted(self._notes.items())), selection_before, selection_after, label)]
        self._cursor += 1
        self.last_keys, self.last_key, self.last_asset_key = selection_after, next(iter(selection_after), None), None

    def add_object(self, map_id: int, template: ObjectTemplate, position: tuple[int, int, int]) -> ObjectKey:
        self._require_idle()
        if not isinstance(position, tuple) or len(position) != 3:
            raise EditError('Position needs three signed16 integers')
        point = tuple(_integer(value, -32768, 32767) for value in position)
        state = self._map_state(map_id)
        serial = self._next_identity.get(map_id, len(self.original_map(map_id).objects))
        if serial >= MAX_IDENTITY:
            raise EditError('Stable identity counter exhausted')
        raw = bytearray(template.raw(self))
        struct.pack_into('>3h', raw, 2, *point)
        entry = EntryIdentity(serial, template, bytes(raw))
        entries = tuple(obj.raw_data for obj in self.current_map(map_id).objects) + (bytes(raw),)
        after = MapState(map_id, rebuild(self, map_id, entries), (*state.identities, entry))
        key = map_id, serial
        self._commit_structure((state,), (after,), (), (key,), 'Add object')
        self._next_identity[map_id] = serial + 1
        self.structure_warnings = structural_diagnostics(self, (self.object(key),))
        return key

    def apply_course_plan(self, plan: CoursePlan, selection: tuple[ObjectKey,...] = ()) -> bool:
        self._require_idle()
        validate_plan_current(self,plan)
        preview_course_plan(self,plan)
        if plan.before==plan.after:return False
        self._commit_structure(plan.before,plan.after,selection,plan.selection,'Build course')
        self._next_identity.update(plan.counters)
        self.structure_warnings=tuple(issue.message for issue in plan.issues)
        return True

    def duplicate_objects(self, keys: tuple[ObjectKey, ...], delta: tuple[int, int, int] = (16, 0, 0)) -> tuple[ObjectKey, ...]:
        self._require_idle()
        if not keys or len(set(keys)) != len(keys) or len(delta) != 3:
            raise EditError('Select distinct objects and an XYZ offset')
        originals = tuple(self.object(key) for key in keys)
        before = tuple(self._map_state(m) for m in sorted({key[0] for key in keys}))
        after, created, counters = [], [], dict(self._next_identity)
        for state in before:
            entries = [obj.raw_data for obj in self.current_map(state.map_id).objects]
            identities = list(state.identities)
            for obj in originals:
                if obj.map_id != state.map_id:
                    continue
                identity = next(i for i in state.identities if i.value == obj.index)
                serial = counters.get(state.map_id, len(self.original_map(state.map_id).objects))
                if serial >= MAX_IDENTITY:
                    raise EditError('Stable identity counter exhausted')
                point = tuple(_integer(a + _integer(b, -65535, 65535), -32768, 32767) for a, b in zip(obj.position, delta))
                raw = bytearray(obj.raw_data)
                struct.pack_into('>3h', raw, 2, *point)
                identities.append(EntryIdentity(serial, identity.template, bytes(raw)))
                entries.append(bytes(raw))
                created.append((state.map_id, serial))
                counters[state.map_id] = serial + 1
            after.append(MapState(state.map_id, rebuild(self, state.map_id, tuple(entries)), tuple(identities)))
        self._commit_structure(before, tuple(after), keys, tuple(created), f'Duplicate {len(keys)} object(s)')
        self._next_identity = counters
        self.structure_warnings = structural_diagnostics(self, originals)
        return tuple(created)

    def delete_objects(self, keys: tuple[ObjectKey, ...]) -> None:
        self._require_idle()
        if not keys or len(set(keys)) != len(keys):
            raise EditError('Select distinct objects')
        originals = tuple(self.object(key) for key in keys)
        warnings = structural_diagnostics(self, originals, deleting=True)
        before = tuple(self._map_state(m) for m in sorted({key[0] for key in keys}))
        after = tuple(MapState(state.map_id,
            rebuild(self, state.map_id, tuple(obj.raw_data for obj in self.current_map(state.map_id).objects if obj.key not in keys)),
            tuple(i for i in state.identities if (state.map_id, i.value) not in keys)) for state in before)
        self._commit_structure(before, after, keys, (), f'Delete {len(keys)} object(s)')
        self.structure_warnings = warnings

    @property
    def modified_maps(self) -> tuple[int, ...]:
        return tuple(sorted(self._modified))

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._history)

    @property
    def undo_label(self) -> str:
        return self._history[self._cursor - 1].label if self.can_undo else ""

    @property
    def redo_label(self) -> str:
        return self._history[self._cursor].label if self.can_redo else ""

    def _signature(self) -> str:
        digest = hashlib.sha256()
        for map_id, raw in sorted(self._modified.items()):
            digest.update(struct.pack(">I", map_id))
            digest.update(raw)
        for (section, index), raw in sorted(self._assets.items()):
            digest.update(struct.pack(">III", 0xFFFFFFFF, int(section), index))
            digest.update(raw)
        for index, baseline in sorted(self._track_imports.items()):
            digest.update(struct.pack('>II',0xFFFFFFFE,index))
            digest.update(baseline)
        for raw in self._custom_textures:
            digest.update(struct.pack('>II',0xFFFFFFFD,len(raw)))
            digest.update(raw)
        for map_id in sorted(self._structures):
            digest.update(struct.pack('>II', map_id, self._next_identity.get(map_id, len(self.original_map(map_id).objects))))
            for identity in self._structures[map_id]:
                template = identity.template
                digest.update(struct.pack('>4i', identity.value, template.object_id,
                    template.map_id if template.map_id is not None else -1,
                    template.entry_index if template.entry_index is not None else -1))
                digest.update(identity.initial)
        digest.update(json.dumps([self.experiment_name, [(key, note.text, note.result) for key, note in sorted(self._notes.items())]], ensure_ascii=True).encode())
        return digest.hexdigest()

    def note(self, key: ObjectKey, field: str) -> FieldNote:
        return self._notes.get((*key, field), FieldNote())

    def _install_research(self, key: ObjectKey | None, field: str, value: FieldNote | str) -> None:
        if key is None:
            self.experiment_name = str(value)
        elif isinstance(value, FieldNote):
            if value == FieldNote():
                self._notes.pop((*key, field), None)
            else:
                self._notes[(*key, field)] = value

    def set_note(self, key: ObjectKey, field: str, text: str, result: str = "Untested") -> bool:
        self._require_idle()
        if field not in {item.key for item in research_fields(self.object(key))}:
            raise EditError("Parameter does not exist on this object")
        if not isinstance(text, str) or len(text) > 20000 or result not in RESULTS:
            raise EditError("Notes require at most 20000 characters and a supported observation result")
        return self._change_research(key, field, FieldNote(text, result), "Edit parameter note")

    def set_experiment_name(self, name: str) -> bool:
        self._require_idle()
        if not isinstance(name, str) or len(name) > 200:
            raise EditError("Project label must be at most 200 characters")
        return self._change_research(None, "experiment", name, "Rename project label")

    def _change_research(self, key: ObjectKey | None, field: str, value: FieldNote | str, label: str) -> bool:
        before = self.note(key, field) if key is not None else self.experiment_name
        if before == value:
            return False
        self._install_research(key, field, value)
        self._history[self._cursor:] = [ResearchChange(key, field, before, value, label)]
        self._cursor += 1
        self.last_key, self.last_asset_key, self.last_keys = key, None, (key,) if key is not None else ()
        return True

    def current_asset(self, section: AssetType, index: int) -> bytes:
        original = self.original_asset(section, index)
        return self._assets.get((section, index), original)

    def original_asset(self, section: AssetType, index: int) -> bytes:
        if section in MODEL_ASSETS:
            key = section, index
            if key not in self._image_originals:
                self._image_originals[key] = self.rom.read_asset(section, index, decompress=True)
            return self._image_originals[key]
        if section == AssetType.TEXTURES_3D and index >= self.rom.count(section):
            offset = _integer(index-self.rom.count(section),0,len(self._custom_textures)-1)
            return self._custom_textures[offset]
        if section in TEXTURE_SECTIONS:
            key = section, index
            if key not in self._image_originals:
                self._image_originals[key] = unpack_texture(self.rom.read_asset(section, index))
            return self._image_originals[key]
        if section == AssetType.LEVEL_MODELS:
            if index not in self._model_originals:
                self._model_originals[index] = self.rom.read_asset(section, index, decompress=True)
            return self._model_originals[index]
        return self.rom.read_asset(section, index)

    @property
    def material_references(self) -> tuple[TextureReference, ...]:
        if self._material_refs is None:
            self._material_refs = texture_references(self.rom)
        return self._material_refs + self._custom_refs

    @property
    def custom_textures(self) -> tuple[bytes, ...]:
        return self._custom_textures

    def _set_texture_pool(self, textures: tuple[bytes, ...]) -> None:
        refs = texture_pool_refs(self.rom.count(AssetType.TEXTURES_3D),textures)
        self._custom_textures,self._custom_refs = textures,refs
        self._image_uses = None
        self._definition_uses = None

    def track_model(self, index: int) -> LevelModel:
        raw = self.current_asset(AssetType.LEVEL_MODELS, index)
        cached = self._model_parsed.get(index)
        if cached is None or cached[0] != raw:
            cached = raw, LevelModel.from_bytes(raw, model_id=index)
            self._model_parsed[index] = cached
        return cached[1]

    def track_base(self, index: int) -> bytes:
        return self._track_imports.get(index, self.original_asset(AssetType.LEVEL_MODELS,index))

    def imported_track(self, index: int) -> bool:
        return index in self._track_imports

    def track_import_version(self, index: int) -> int:
        baseline = self._track_imports.get(index)
        return import_project_version(self.original_asset(AssetType.LEVEL_MODELS,index),baseline,
            self.material_references,self.minimap_references) if baseline is not None else 0

    def preview_track_import(self, index: int, raw: bytes, *, textures: tuple[bytes, ...] = ()) -> ExportReport:
        self._require_idle()
        if textures:
            previous = self._custom_textures
            try:
                self._set_texture_pool(previous+textures)
                report = self.preview_track_import(index,raw)
                uses = tuple(f'{l.index}: {l.name}' for l in self._catalog.levels if l.header.geometry_id==index)
                first = self.rom.count(AssetType.TEXTURES_3D)+len(previous)
                return replace(report,assets=tuple(replace(d,levels=uses) if d.section==2 and d.index>=first else d for d in report.assets))
            finally:
                self._set_texture_pool(previous)
        version=import_project_version(self.original_asset(AssetType.LEVEL_MODELS,index),raw,
                                self.material_references,self.minimap_references)
        from src.core.render_batches import rebatch_track
        raw = rebatch_track(raw, segmented=version == 10)
        sections,current_report = self._prepare_export()
        previous_layout_errors = make_export_report(self.rom, sections, current_report.assets).errors
        sections = list(sections)
        table = AssetTable.parse(sections[26],len(sections[27]))
        chunks: list[bytes] = []
        offsets = [0]
        packed = compress_segmented_track(raw) if version==10 else compress_asset(raw)
        verify_geometry_stream(raw, packed)
        for i in range(len(table)):
            span = table.span(i)
            chunk = packed if i==index else sections[27][span.start:span.end]
            chunks.append(chunk)
            offsets.append(offsets[-1]+len(chunk))
        chunks.append(sections[27][table.offsets[-1]:])
        lookup = bytearray(sections[26])
        struct.pack_into('>'+str(len(offsets))+'I',lookup,0,*offsets)
        sections[26],sections[27] = bytes(lookup),b''.join(chunks)
        original = self.rom.read_asset(AssetType.LEVEL_MODELS,index)
        uses = tuple(f'{l.index}: {l.name}' for l in self._catalog.levels if l.header.geometry_id==index)
        diff = AssetDiff(27,index,f'Imported track {index}',len(self.original_asset(AssetType.LEVEL_MODELS,index)),len(raw),
                         len(original),len(packed),uses,(f'Replacement with {len(LevelModel.from_bytes(raw).segments)} segment(s), generated collision and visibility.',))
        report = make_export_report(self.rom,tuple(sections),
            tuple(d for d in current_report.assets if (d.section,d.index)!=(27,index))+(diff,))
        report = report.retain_validation_errors(current_report, previous_layout_errors)
        if not report.can_export:
            raise EditError('; '.join(report.errors))
        return report

    def _install_track_import(self, index: int, raw: bytes, baseline: bytes | None) -> None:
        previous = self._track_imports.get(index)
        if baseline is not None:
            import_project_version(self.original_asset(AssetType.LEVEL_MODELS,index),baseline,
                                    self.material_references,self.minimap_references)
            self._track_imports[index] = baseline
        else:
            self._track_imports.pop(index,None)
        try:
            self._install_asset((AssetType.LEVEL_MODELS,index),raw)
        except ValueError:
            if previous is None:self._track_imports.pop(index,None)
            else:self._track_imports[index] = previous
            raise
        self._image_uses = None
        self._definition_uses = None

    def import_track(self, index: int, raw: bytes, *, textures: tuple[bytes, ...] = ()) -> bool:
        self.preview_track_import(index,raw,textures=textures)
        before = self.current_asset(AssetType.LEVEL_MODELS,index)
        baseline = self._track_imports.get(index)
        if before==raw and baseline==raw and not textures:
            return False
        previous = self._custom_textures
        try:
            if textures:self._set_texture_pool(previous+textures)
            self._install_track_import(index,raw,raw)
        except ValueError:
            self._set_texture_pool(previous)
            raise
        self._history[self._cursor:] = [TrackImportChange(index,before,baseline,raw,raw,'Import custom track and artwork' if textures else 'Import custom track',
            previous if textures else None,self._custom_textures if textures else None)]
        self._cursor += 1
        self.last_asset_key,self.last_key,self.last_keys = (AssetType.LEVEL_MODELS,index),None,()
        return True

    def restore_stock_track(self, index: int) -> bool:
        self._require_idle()
        if index not in self._track_imports:
            return False
        before = self.current_asset(AssetType.LEVEL_MODELS,index)
        baseline = self._track_imports[index]
        original = self.original_asset(AssetType.LEVEL_MODELS,index)
        textures = self._custom_textures
        self._install_track_import(index,original,None)
        removed: tuple[tuple[AssetKey, bytes], ...] = ()
        try:
            if textures:
                first = self.rom.count(AssetType.TEXTURES_3D)
                # Retain the prefix through the last referenced ID. Never
                # renumber a texture used by another track/shared definition.
                last = max((i for (section, i), uses in self.image_uses.direct.items()
                            if section == AssetType.TEXTURES_3D and i >= first and uses), default=first-1)
                # Imported baselines are serialized too and must remain valid
                # for material reverts/project reload, even if their current
                # texture slots were reassigned to stock artwork.
                last = max(last, max((texture.texture_id for raw in self._track_imports.values()
                                      for texture in LevelModel.from_bytes(raw).textures), default=first-1))
                keep = min(len(textures), last-first+1)
                removed = tuple((key, raw) for key, raw in self._assets.items()
                                if key[0] == AssetType.TEXTURES_3D and key[1] >= first+keep)
                for key, _ in removed:
                    self._assets.pop(key)
                self._set_texture_pool(textures[:keep])
        except ValueError:
            self._set_texture_pool(textures)
            self._assets.update(removed)
            self._install_track_import(index, before, baseline)
            raise
        self._history[self._cursor:] = [TrackImportChange(index,before,baseline,original,None,'Restore stock track',
            textures, self._custom_textures, removed)]
        self._cursor += 1
        self.last_asset_key,self.last_key,self.last_keys = (AssetType.LEVEL_MODELS,index),None,()
        return True

    def edit_track_materials(self, index: int, edits: tuple[MaterialEdit, ...], label: str = "Edit track materials") -> bool:
        key = AssetType.LEVEL_MODELS, index
        try:
            current = self.current_asset(*key)
            raw = edit_materials(current, edits, self.material_references,
                original=copy_geometry(copy_minimap(self.track_base(index), current), current))
        except ValueError as error:
            raise EditError(str(error)) from error
        return self._replace_asset(key, raw, label)

    def revert_track_materials(self, index: int) -> bool:
        key = AssetType.LEVEL_MODELS, index
        current = self.current_asset(*key)
        return self._replace_asset(key, copy_geometry(copy_minimap(self.track_base(index), current), current), f"Revert model {index} materials")

    def edit_track_geometry(self, index: int, keys: tuple[VertexKey, ...], delta: Position,
                            label: str = 'Move track geometry') -> bool:
        key = AssetType.LEVEL_MODELS, index
        try:
            raw = move_vertices(self.track_base(index), self.current_asset(*key), keys, delta)
        except ValueError as error:
            raise EditError(str(error)) from error
        return self._replace_asset(key, raw, label)

    def revert_track_geometry(self, index: int) -> bool:
        key = AssetType.LEVEL_MODELS, index
        return self._replace_asset(key, copy_geometry(self.current_asset(*key), self.track_base(index)),
                                   f'Revert model {index} geometry')

    def apply_track_geometry_preview(self, index: int, raw: bytes) -> bool:
        key = AssetType.LEVEL_MODELS, index
        if copy_geometry(self.current_asset(*key), raw) != raw:
            raise EditError('Geometry preview cannot change materials, minimap or other model bytes')
        return self._replace_asset(key, raw, 'Drag track geometry')

    @property
    def minimap_references(self) -> tuple[SpriteReference, ...]:
        if self._minimap_refs is None:
            self._minimap_refs = sprite_references(self.rom)
        return self._minimap_refs

    def edit_minimap(self, index: int, changes: dict[str, int | float]) -> bool:
        key = AssetType.LEVEL_MODELS, index
        try:
            raw = edit_minimap(self.current_asset(*key), changes, self.minimap_references)
        except ValueError as error:
            raise EditError(str(error)) from error
        return self._replace_asset(key, raw, f"Edit model {index} minimap")

    def revert_minimap(self, index: int) -> bool:
        key = AssetType.LEVEL_MODELS, index
        return self._replace_asset(key, copy_minimap(self.current_asset(*key), self.track_base(index)), f"Revert model {index} minimap")

    @property
    def image_uses(self) -> ImageUses:
        if self._image_uses is None:
            self._image_uses = build_image_uses(self.asset_source, self.database, dependencies=self.definition_uses)
        return self._image_uses

    @property
    def definition_uses(self) -> dict[int, DefinitionUse]:
        if self._definition_uses is None:
            self._definition_uses = definition_dependencies(self.asset_source, self.database)
        return self._definition_uses

    def original_object_model(self, index: int) -> ObjectModel:
        if index not in self._original_object_models:
            self._original_object_models[index] = ObjectModel.from_bytes(
                self.original_asset(AssetType.OBJECT_MODELS, index), index)
        return self._original_object_models[index]

    def image_texture(self, section: AssetType, index: int) -> Texture:
        if section not in TEXTURE_SECTIONS:
            raise EditError("Choose an existing 2D or 3D texture")
        return texture_from_raw(self.current_asset(section, index), index, self.rom.section(AssetType.EMPTY_14))

    def image_updates(self, section: AssetType, index: int, frame: int, pixels: Pixels) -> dict[AssetKey, bytes]:
        """Prepare and validate before changing history, including all sprite tiles."""
        if section == AssetType.SPRITES:
            canvas = sprite_canvas(self.asset_source, index, frame)
            tiles = split_sprite_png(canvas, pixels)
            updates = {(AssetType.TEXTURES_2D, tile): replace_frame(self.current_asset(AssetType.TEXTURES_2D, tile), 0, p,
                palettes=self.rom.section(AssetType.EMPTY_14)) for tile, p in tiles.items()}
        elif section in TEXTURE_SECTIONS:
            updates = {(section, index): replace_frame(self.current_asset(section, index), frame, pixels,
                palettes=self.rom.section(AssetType.EMPTY_14))}
        else:
            raise EditError("Image import is not enabled for that asset")
        for key, raw in updates.items():
            self._validate_asset(key, raw)
        return updates

    def import_image(self, section: AssetType, index: int, frame: int, pixels: Pixels) -> bool:
        return self._replace_assets(self.image_updates(section, index, frame, pixels), f"Import {section.name} {index} frame {frame} PNG")

    def set_sprite_anchor(self, index: int, x: int, y: int) -> bool:
        key = AssetType.SPRITES, index
        return self._replace_asset(key, edit_anchor(self.current_asset(*key), x, y), f"Sprite {index} anchor")

    def set_texture_timing(self, section: AssetType, index: int, value: int) -> bool:
        if section not in TEXTURE_SECTIONS:
            raise EditError("Sprites have no stored timing field; choose a texture entry")
        key = section, index
        return self._replace_asset(key, edit_timing(self.current_asset(*key), value), f"Texture {index} timing")

    def revert_image(self, section: AssetType, index: int) -> bool:
        keys = {(section, index)}
        if section == AssetType.SPRITES:
            from src.core.textures import load_sprite
            sprite = load_sprite(self.asset_source, index)
            keys.update((AssetType.TEXTURES_2D, i) for i in range(sprite.base_texture_id, sprite.base_texture_id + sprite.frame_offsets[-1]))
        elif section not in TEXTURE_SECTIONS:
            raise EditError("Choose a texture or sprite")
        return self._replace_assets({key: self.original_asset(*key) for key in keys}, f"Revert {section.name} {index} artwork")

    def _validate_asset(self, key: AssetKey, raw: bytes) -> None:
        if key[0] not in WRITABLE_ASSETS:
            raise EditError("Editing this asset type is not enabled")
        if key[0] in MODEL_ASSETS:
            validate_object_art(self, key, raw)
            return
        if key[0] == AssetType.LEVEL_NAMES:
            validate_name_edit(self.original_asset(*key),raw,self.name_fonts)
            return
        if key[0] == AssetType.OBJECTS:
            validate_definition(self.original_asset(*key), raw, self.object_resources)
            return
        if len(raw) != len(self.track_base(key[1]) if key[0]==AssetType.LEVEL_MODELS else self.original_asset(*key)):
            raise EditError("Decoded asset length must stay unchanged")
        if key[0] == AssetType.LEVEL_HEADERS:
            try:
                validate_header_edit(self.rom.read_asset(*key), raw, self.level_references(key[1]))
            except ValueError as error:
                raise EditError(str(error)) from error
        elif key[0] == AssetType.LEVEL_MODELS:
            try:
                model = validate_model_edit(self.track_base(key[1]), raw, self.material_references, self.minimap_references, allow_geometry=True)
                if key[1] in self._track_imports:
                    validate_import_runtime(model)
                    if self.track_import_version(key[1])==10:
                        validate_segmented_runtime(model,LevelModel.from_bytes(self.track_base(key[1])))
            except ValueError as error:
                raise EditError(str(error)) from error
        elif key[0] in TEXTURE_SECTIONS:
            validate_texture_edit(self.original_asset(*key), raw, self.rom.section(AssetType.EMPTY_14))
        elif key[0] == AssetType.SPRITES:
            validate_sprite_edit(self.original_asset(*key), raw)

    def level_header(self, index: int) -> LevelHeader:
        return LevelHeader.from_bytes(self.current_asset(AssetType.LEVEL_HEADERS, index))

    @property
    def object_resources(self) -> ObjectResources:
        if self._object_resources is None:
            self._object_resources = ObjectResources(self.asset_source)
        return self._object_resources

    def apply_global_objects(self, plan: GlobalObjectPlan) -> bool:
        self._require_idle()
        if self._signature() != plan.signature or any(self.current_asset(AssetType.OBJECTS, i) != raw for i, raw in plan.before):
            raise EditError('Global-object preview is stale; preview again')
        for i, raw in plan.after:
            self._validate_asset((AssetType.OBJECTS, i), raw)
        # Exact final-layout preflight includes all existing project edits.
        from src.core.global_objects import plan_global_objects
        verified = plan_global_objects(self, dict(plan.after))
        return self._replace_assets({(AssetType.OBJECTS, i): raw for i, raw in verified.after}, 'Edit global object properties')

    def apply_models(self, plan: ModelPlan) -> bool:
        self._require_idle()
        if self._signature() != plan.signature or any(self.current_asset(*k) != raw for k, raw in plan.before):
            raise EditError('Object-art preview is stale; preview again')
        verified = plan_models(self, dict(plan.after))
        return self._replace_assets(dict(verified.after), 'Edit object models and animation')

    @property
    def name_fonts(self) -> tuple[NameFont,...]:
        if self._name_fonts is None:self._name_fonts=load_name_fonts(self.rom.section(AssetType.FONTS))
        return self._name_fonts

    def course_names(self, index: int) -> LevelNames:
        return NameRecord.parse(self.current_asset(AssetType.LEVEL_NAMES,index)).values

    def apply_course_names(self, plan: NamePlan) -> bool:
        self._require_idle()
        if self._signature()!=plan.signature or any(self.current_asset(AssetType.LEVEL_NAMES,i)!=raw for i,raw in plan.before):
            raise EditError('Course-name preview is stale; preview again')
        for i,raw in plan.after:self._validate_asset((AssetType.LEVEL_NAMES,i),raw)
        # Recheck the exact budget at the commit boundary; no preview overlays
        # are temporarily installed in this session.
        fresh=plan_names(self,{i:{key:getattr(NameRecord.parse(raw).values,key) for key in EDITABLE_LANGUAGES} for i,raw in plan.after})
        if fresh.after!=plan.after:raise EditError('Course-name preview data does not match validated names')
        return self._replace_assets({(AssetType.LEVEL_NAMES,i):raw for i,raw in plan.after},'Edit course names')

    def set_course_names(self, index: int, changes: dict[str,str]) -> bool:
        return self.apply_course_names(plan_names(self,{index:changes}))

    def level_references(self, index: int, *, maps: dict[int, ObjectMap] | None = None) -> LevelReferences:
        header = self.level_header(index)
        candidates = maps if maps is not None else {}
        map_ids = {i for i in (header.object_map_id, header.secondary_object_map_id) if i >= 0}
        models = (candidates[i] if i in candidates else self.current_map(i) for i in map_ids)
        sets = {int(obj.value("vehicleType", 0)) for model in models for obj in model.objects
                if obj.definition.behavior_id == 13 and not obj.value("isAltCheckpoint", 0)}
        return replace(self._level_references, checkpoint_sets=tuple(sorted(sets)))

    def _validate_map_references(self, maps: dict[int, ObjectMap]) -> None:
        """Keep edited header references valid before installing any candidate map.

        Check the complete transaction: a group may move a set between the two
        loaded maps. Original unsupported header values retain their existing
        preservation rule; object types and checkpoint graph experiments remain
        available. Reassign the level header before removing its custom set.
        """
        for (section, index), raw in sorted(self._assets.items()):
            if section != AssetType.LEVEL_HEADERS:
                continue
            original = self.original_asset(section, index)
            if original[0x4F:0x52] == raw[0x4F:0x52]:
                continue
            header = LevelHeader.from_bytes(raw)
            if not maps.keys() & {header.object_map_id, header.secondary_object_map_id}:
                continue
            try:
                validate_header_edit(original, raw, self.level_references(index, maps=maps))
            except ValueError as error:
                raise EditError(f'Level {index}: {error}. Choose another checkpoint set in Level settings '
                    'before removing or reassigning the last main checkpoint.') from error

    def set_level_field(self, index: int, key: str, value: SettingValue) -> bool:
        raw = self.current_asset(AssetType.LEVEL_HEADERS, index)
        try:
            updated = write_field(raw, key, value)
        except ValueError as error:
            raise EditError(str(error)) from error
        if key == 'checkpoint_sets':
            self._validate_checkpoint_selection(index, raw, updated)
        return self._replace_asset((AssetType.LEVEL_HEADERS, index), updated, f"Level {index}: {FIELD_BY_KEY[key].label}")

    def _validate_checkpoint_selection(self, index: int, before: bytes, after: bytes) -> None:
        available = self.level_references(index).checkpoint_sets
        field = FIELD_BY_KEY['checkpoint_sets']
        # Compare to the live header here. Stock-only validation intentionally
        # preserves original unsupported values during unrelated edits.
        if any(a != b and b not in available for a, b in zip(field.read(before), field.read(after))):
            raise EditError('Checkpoint set does not exist among this level\'s main checkpoints')

    def revert_level(self, index: int) -> bool:
        original = self.rom.read_asset(AssetType.LEVEL_HEADERS, index)
        self._validate_checkpoint_selection(index, self.current_asset(AssetType.LEVEL_HEADERS, index), original)
        return self._replace_asset((AssetType.LEVEL_HEADERS, index), original,
                                   f"Revert level {index} settings")

    def _install_asset(self, key: AssetKey, raw: bytes) -> None:
        self._validate_asset(key, raw)
        if key[0] in (AssetType.LEVEL_HEADERS, AssetType.LEVEL_NAMES):
            self._image_uses = None
            self._definition_uses = None
        if key[0] == AssetType.LEVEL_MODELS and self._image_uses is not None:
            before = LevelModel.from_bytes(self.current_asset(*key))
            after = LevelModel.from_bytes(raw)
            if before.raw_data[0x20:0x24] != raw[0x20:0x24] or tuple(t.texture_id for t in before.textures) != tuple(t.texture_id for t in after.textures):
                self._image_uses = None
                self._definition_uses = None
        if raw == self.original_asset(*key):
            self._assets.pop(key, None)
        else:
            self._assets[key] = raw
        if key[0] in MODEL_ASSETS:
            self._object_resources = None
            self._image_uses = None
            self._definition_uses = None
        if key[0] == AssetType.LEVEL_HEADERS:
            self._catalog = replace(self._catalog, levels=tuple(
                replace(level, header=LevelHeader.from_bytes(raw)) if level.index == key[1] else level
                for level in self._catalog.levels))
        elif key[0]==AssetType.LEVEL_NAMES:
            self._catalog=replace(self._catalog,levels=tuple(replace(level,names=LevelNames.from_bytes(raw))
                if level.index==key[1] else level for level in self._catalog.levels))
        elif key[0] == AssetType.OBJECTS:
            from src.core.objects import ObjectDefinition
            self.database = replace(self.database, definitions=tuple(
                ObjectDefinition.from_bytes(raw, key[1]) if d.header_id == key[1] else d
                for d in self.database.definitions))
            self._originals.clear()
            self._parsed.clear()
            self._object_catalog = None
            self._image_uses = None
            self._definition_uses = None

    def _replace_asset(self, key: AssetKey, raw: bytes, label: str) -> bool:
        self._require_idle()
        before = self.current_asset(*key)
        self._validate_asset(key, raw)
        if before == raw:
            return False
        self._install_asset(key, raw)
        self._history[self._cursor:] = [AssetChange(key, before, raw, label)]
        self._cursor += 1
        self.last_asset_key, self.last_key = key, None
        return True

    def _replace_assets(self, updates: dict[AssetKey, bytes], label: str) -> bool:
        self._require_idle()
        for key, raw in updates.items():
            self._validate_asset(key, raw)
        keys = tuple(sorted(key for key, raw in updates.items() if self.current_asset(*key) != raw))
        if not keys:
            return False
        before = tuple(self.current_asset(*key) for key in keys)
        after = tuple(updates[key] for key in keys)
        for key, raw in zip(keys, after):
            self._install_asset(key, raw)
        self._history[self._cursor:] = [AssetGroupChange(keys, before, after, label)]
        self._cursor += 1
        self.last_asset_key, self.last_key, self.last_keys = keys[0], None, ()
        return True

    @property
    def dirty(self) -> bool:
        return self._signature() != self._saved_signature

    def _install(self, map_id: int, raw: bytes, *, check_references: bool = True) -> None:
        parsed = ObjectMap.from_bytes(raw, self.database, map_id=map_id)
        self._validate_existing_map(map_id, parsed, raw)
        if check_references:
            self._validate_map_references({map_id: parsed})
        if map_id in self._structures:
            parsed = identify(parsed, self._structures[map_id])
        if (self._image_uses is not None or self._definition_uses is not None) and any(a.value("objectIdToSpawn", -1) != b.value("objectIdToSpawn", -1)
                for a, b in zip(self.current_map(map_id).objects, parsed.objects)):
            self._image_uses = None
            self._definition_uses = None
        if raw == _raw_map(self.original_map(map_id)):
            self._modified.pop(map_id, None)
            self._parsed.pop(map_id, None)
        else:
            self._modified[map_id] = raw
            self._parsed[map_id] = parsed

    def _validate_existing_map(self, map_id: int, parsed: ObjectMap, raw: bytes) -> None:
        if map_id in self._structures:
            validate_state(self, MapState(map_id, raw, self._structures[map_id]))
            return
        original = self.original_map(map_id)
        if (len(raw) != len(_raw_map(original)) or parsed.header != original.header or parsed.padding != original.padding
                or len(parsed.objects) != len(original.objects)
                or any(a.raw_data[:2] != b.raw_data[:2] for a, b in zip(original.objects, parsed.objects))):
            raise EditError('Structural object-map editing is not enabled in editor projects')

    def _replace_entry(self, key: ObjectKey, entry: bytes, label: str) -> bool:
        self._require_idle()
        obj = self.object(key)
        assert obj.raw_data is not None and obj.offset is not None
        if len(entry) != obj.byte_size or entry[:2] != obj.raw_data[:2]:
            raise EditError("Object ID and entry length must stay unchanged")
        before = _raw_map(self.current_map(key[0]))
        if entry == obj.raw_data:
            return False
        after = before[:obj.offset] + entry + before[obj.offset + obj.byte_size:]
        self._install(key[0], after)
        self._history[self._cursor:] = [EditChange(key, before, after, label)]
        self._cursor += 1
        self.last_key = key
        self.last_asset_key = None
        self.last_keys = (key,)
        return True

    @property
    def moving_key(self) -> ObjectKey | None:
        return self._move.key if self._move is not None else self._group.keys[0] if self._group else None

    @property
    def group_active(self) -> bool:
        return self._group is not None

    def _require_idle(self) -> None:
        if self._move is not None or self._group is not None:
            raise EditError("Finish or cancel the active mouse move first")

    def begin_group(self, keys: tuple[ObjectKey, ...], label: str) -> None:
        self._require_idle()
        if not keys or len(set(keys)) != len(keys):
            raise EditError("Select distinct existing objects")
        for key in keys:
            self.object(key)
        before = tuple((i, _raw_map(self.current_map(i))) for i in sorted({key[0] for key in keys}))
        self._group = GroupPreview(keys, before, label)

    def _install_maps(self, maps: tuple[tuple[int, bytes], ...]) -> None:
        # Validate the whole transaction before installing any member map.
        candidates: dict[int, ObjectMap] = {}
        for map_id, raw in maps:
            parsed = ObjectMap.from_bytes(raw, self.database, map_id=map_id)
            self._validate_existing_map(map_id, parsed, raw)
            candidates[map_id] = parsed
        self._validate_map_references(candidates)
        for map_id, raw in maps:
            self._install(map_id, raw, check_references=False)

    def preview_group(self, entries: dict[ObjectKey, bytes]) -> bool:
        group = self._group
        if group is None or set(entries) != set(group.keys):
            raise EditError("Preview must update exactly the active object selection")
        buffers = {map_id: bytearray(raw) for map_id, raw in group.before}
        for key, entry in entries.items():
            obj = self.object(key)
            assert obj.offset is not None and obj.raw_data is not None
            if len(entry) != obj.byte_size or entry[:2] != obj.raw_data[:2]:
                raise EditError("Object ID and entry length must stay unchanged")
            buffers[key[0]][obj.offset:obj.offset + obj.byte_size] = entry
        maps = tuple((map_id, bytes(raw)) for map_id, raw in sorted(buffers.items()))
        changed = any(raw != _raw_map(self.current_map(map_id)) for map_id, raw in maps)
        self._install_maps(maps)
        return changed

    def finish_group(self, *, cancel: bool = False) -> bool:
        group = self._group
        if group is None:
            return False
        self._group = None
        if cancel:
            self._install_maps(group.before)
            return False
        after = tuple((map_id, _raw_map(self.current_map(map_id))) for map_id, _ in group.before)
        if after == group.before:
            return False
        self._history[self._cursor:] = [GroupChange(group.keys, group.before, after, group.label)]
        self._cursor += 1
        self.last_keys, self.last_key, self.last_asset_key = group.keys, group.keys[0], None
        return True

    def apply_entries(self, entries: dict[ObjectKey, bytes], label: str) -> bool:
        self.begin_group(tuple(entries), label)
        try:
            self.preview_group(entries)
        except Exception:
            self.finish_group(cancel=True)
            raise
        return self.finish_group()

    def begin_move(self, key: ObjectKey) -> None:
        self._require_idle()
        self.object(key)
        self._move = MovePreview(key, _raw_map(self.current_map(key[0])))

    def preview_move(self, position: tuple[int, int, int]) -> bool:
        if self._move is None:
            raise EditError("No mouse move is active")
        if len(position) != 3:
            raise EditError("Position needs X, Y and Z")
        values = tuple(_integer(value, -32768, 32767) for value in position)
        obj = self.object(self._move.key)
        assert obj.raw_data is not None and obj.offset is not None
        if values == obj.position:
            return False
        raw = bytearray(obj.raw_data)
        struct.pack_into(">hhh", raw, 2, *values)
        model = _raw_map(self.current_map(self._move.key[0]))
        self._install(self._move.key[0], model[:obj.offset] + raw + model[obj.offset+obj.byte_size:])
        return True

    def finish_move(self, *, cancel: bool = False) -> bool:
        move = self._move
        if move is None:
            return False
        self._move = None
        if cancel:
            self._install(move.key[0], move.before)
            return False
        after = _raw_map(self.current_map(move.key[0]))
        if after == move.before:
            return False
        self._history[self._cursor:] = [EditChange(move.key, move.before, after, "Drag object")]
        self._cursor += 1
        self.last_key = move.key
        self.last_asset_key = None
        return True

    def set_position(self, key: ObjectKey, position: tuple[int, int, int]) -> bool:
        if len(position) != 3:
            raise EditError("Position needs X, Y and Z")
        values = tuple(_integer(value, -32768, 32767) for value in position)
        raw = bytearray(self.object(key).raw_data or b"")
        struct.pack_into(">hhh", raw, 2, *values)
        return self._replace_entry(key, bytes(raw), "Move object")

    def set_parameter(self, key: ObjectKey, name: str, value: int | tuple[int, ...]) -> bool:
        obj = self.object(key)
        parameter = next((p for p in obj.parameters if p.name == name), None)
        if parameter is None:
            raise EditError(f"Unknown parameter {name}")
        count = len(parameter.value) if isinstance(parameter.value, tuple) else 1
        values = value if isinstance(value, tuple) else (value,)
        if len(values) != count or any(type(v) is not int for v in values):
            raise EditError(f"{name} needs {count} integer value(s)")
        raw = bytearray(obj.raw_data or b"")
        try:
            struct.pack_into(">" + str(count) + parameter.format, raw, parameter.offset, *values)
        except struct.error as error:
            raise EditError(str(error)) from error
        return self._replace_entry(key, bytes(raw), f"Change {name}")

    def set_raw_byte(self, key: ObjectKey, offset: int, value: int) -> bool:
        obj = self.object(key)
        _integer(offset, 8, obj.byte_size - 1)
        raw = bytearray(obj.raw_data or b"")
        raw[offset] = _integer(value, 0, 255)
        return self._replace_entry(key, bytes(raw), f"Change byte 0x{offset:02X}")

    def revert_object(self, key: ObjectKey) -> bool:
        self.object(key)
        if key[0] in self._structures:
            initial = next(i.initial for i in self._structures[key[0]] if i.value == key[1])
            return self._replace_entry(key, initial, 'Revert object')
        original = self.original_map(key[0]).objects[key[1]]
        assert original.raw_data is not None
        return self._replace_entry(key, original.raw_data, "Revert object")

    def undo(self) -> ObjectKey | None:
        self._require_idle()
        if not self.can_undo:
            return None
        change = self._history[self._cursor - 1]
        if isinstance(change, TrackImportChange):
            if change.before_textures is not None:self._set_texture_pool(change.before_textures)
            self._install_track_import(change.index,change.before,change.before_base)
            for key, raw in change.removed_texture_edits:
                self._install_asset(key, raw)
        elif isinstance(change, StructureChange):
            self._install_states(change.before)
            self._notes = dict(change.notes_before)
        elif isinstance(change, GroupChange):
            self._install_maps(change.before)
        elif isinstance(change, ResearchChange):
            self._install_research(change.key, change.field, change.before)
        elif isinstance(change, AssetGroupChange):
            for key, raw in zip(change.keys, change.before):
                self._install_asset(key, raw)
        elif isinstance(change, AssetChange):
            self._install_asset(change.key, change.before)
        else:
            self._install(change.key[0], change.before)
        self._cursor -= 1
        if isinstance(change,TrackImportChange):
            self.last_asset_key,self.last_key,self.last_keys = (AssetType.LEVEL_MODELS,change.index),None,()
            return None
        if isinstance(change, StructureChange):
            self.last_keys, self.last_key, self.last_asset_key = change.selection_before, next(iter(change.selection_before), None), None
            return self.last_key
        self.last_asset_key = change.key if isinstance(change, AssetChange) else change.keys[0] if isinstance(change, AssetGroupChange) else None
        self.last_key = change.key if isinstance(change, (EditChange, ResearchChange)) else change.keys[0] if isinstance(change, GroupChange) else None
        self.last_keys = change.keys if isinstance(change, GroupChange) else (change.key,) if isinstance(change, EditChange) else ()
        return self.last_key

    def redo(self) -> ObjectKey | None:
        self._require_idle()
        if not self.can_redo:
            return None
        change = self._history[self._cursor]
        if isinstance(change, TrackImportChange):
            for key, _ in change.removed_texture_edits:
                self._assets.pop(key, None)
            if change.after_textures is not None:self._set_texture_pool(change.after_textures)
            self._install_track_import(change.index,change.after,change.after_base)
        elif isinstance(change, StructureChange):
            self._install_states(change.after)
            self._notes = dict(change.notes_after)
        elif isinstance(change, GroupChange):
            self._install_maps(change.after)
        elif isinstance(change, ResearchChange):
            self._install_research(change.key, change.field, change.after)
        elif isinstance(change, AssetGroupChange):
            for key, raw in zip(change.keys, change.after):
                self._install_asset(key, raw)
        elif isinstance(change, AssetChange):
            self._install_asset(change.key, change.after)
        else:
            self._install(change.key[0], change.after)
        self._cursor += 1
        if isinstance(change,TrackImportChange):
            self.last_asset_key,self.last_key,self.last_keys = (AssetType.LEVEL_MODELS,change.index),None,()
            return None
        if isinstance(change, StructureChange):
            self.last_keys, self.last_key, self.last_asset_key = change.selection_after, next(iter(change.selection_after), None), None
            return self.last_key
        self.last_asset_key = change.key if isinstance(change, AssetChange) else change.keys[0] if isinstance(change, AssetGroupChange) else None
        self.last_key = change.key if isinstance(change, (EditChange, ResearchChange)) else change.keys[0] if isinstance(change, GroupChange) else None
        self.last_keys = change.keys if isinstance(change, GroupChange) else (change.key,) if isinstance(change, EditChange) else ()
        return self.last_key

    def project_document(self, selected_level: int = 0) -> dict[str, Any]:
        from src.core.project_io import project_document
        return project_document(self, selected_level)

    def _note_base(self, key: ObjectKey) -> bytes:
        if key[0] in self._structures:
            return next(i.initial for i in self._structures[key[0]] if i.value == key[1])
        return self.original_map(key[0]).objects[key[1]].raw_data

    def save_project(self, path: Path, selected_level: int = 0) -> Path:
        if self.rom.source_path is None:
            raise EditError("Load the base ROM from a file before saving a project")
        if path.suffix.casefold() != ".dkrproj":
            raise EditError("Object projects use the .dkrproj extension")
        payload = (json.dumps(self.project_document(selected_level), indent=2) + "\n").encode("utf-8")
        self.project_path = _atomic_write(path, payload, self.rom.source_path)
        self._saved_signature = self._signature()
        return self.project_path

    @classmethod
    def load_project(cls, path: Path, *, base_path: Path | None = None) -> EditSession:
        from src.core.project_io import load_project
        return load_project(cls, path, base_path=base_path)

    def _prepare_export(self) -> tuple[tuple[bytes, ...], ExportReport]:
        self._require_idle()
        signature = self._signature()
        if self._report_cache is not None and self._report_cache[0] == signature:
            return self._report_cache[1:]
        sections = [self.rom.data[span.start:span.end] for span in self.rom.sections]
        diffs: list[AssetDiff] = []
        table = self.rom.index_table(AssetType.LEVEL_OBJECT_MAPS)
        chunks: list[bytes] = []
        offsets = [0]
        for map_id in range(len(table)):
            span = table.span(map_id)
            chunk = sections[21][span.start:span.end]
            if map_id in self._modified:
                raw = self._modified[map_id]
                self._validate_existing_map(map_id, ObjectMap.from_bytes(raw, self.database, map_id=map_id), raw)
                cached = self._packed_cache.get(map_id)
                packed = cached[1] if cached is not None and cached[0] == raw else compress_object_map(raw)
                self._packed_cache[map_id] = (raw, packed)
                uses = tuple(f"{level.index}: {level.name}" for level in self._catalog.levels
                             if map_id in (level.header.object_map_id, level.header.secondary_object_map_id))
                changes: list[str] = []
                current_objects = self.current_map(map_id).objects
                original_objects = self.original_map(map_id).objects
                if map_id in self._structures:
                    changes.append(f'Structural map: {len(original_objects)} → {len(current_objects)} entries; stable editor IDs retained.')
                    current_ids = {obj.index for obj in current_objects}
                    changes.extend(f'Deleted original entry {obj.index}: {obj.definition.name}' for obj in original_objects if obj.index not in current_ids)
                    changes.extend(f'Added editor ID {obj.index}: {obj.definition.name}, XYZ {obj.position}' for obj in current_objects if obj.index >= len(original_objects))
                pairs = ((self.original_map(map_id).objects[obj.index], obj) for obj in current_objects if obj.index < len(original_objects))
                for old, new in pairs:
                    if old.raw_data == new.raw_data:
                        continue
                    changes.append(f"{new.index}: {new.definition.name} (ID {new.object_id})")
                    if old.position != new.position:
                        changes.append(f"  XYZ: {old.position} → {new.position}")
                    for before, after in zip(old.parameters, new.parameters):
                        if before.value != after.value:
                            changes.append(f"  0x{after.offset:02X} {after.name}: {before.value} → {after.value}")
                    changes.extend(f"  byte 0x{i:02X}: 0x{a:02X} → 0x{b:02X}"
                                   for i, (a, b) in enumerate(zip(old.raw_data, new.raw_data)) if a != b)
                diffs.append(AssetDiff(21, map_id, f"Object map {map_id}", len(_raw_map(self.original_map(map_id))),
                                       len(raw), len(chunk), len(packed), uses, tuple(changes)))
                chunk = packed
            chunks.append(chunk)
            offsets.append(offsets[-1] + len(chunk))
        # Preserve section-tail and table-terminator/alignment bytes verbatim.
        chunks.append(sections[21][table.offsets[-1]:])
        index = bytearray(sections[20])
        struct.pack_into(">" + str(len(offsets)) + "I", index, 0, *offsets)
        sections[20] = bytes(index)
        sections[21] = b"".join(chunks)
        AssetTable.parse(sections[20], len(sections[21]))
        header_uses = definition_uses(self) if any(section == AssetType.OBJECTS for section, _ in self._assets) else {}
        for (section, index), raw in sorted(self._assets.items()):
            if section in (AssetType.LEVEL_MODELS,AssetType.LEVEL_NAMES) or section in IMAGE_SECTIONS or section in MODEL_ASSETS:
                continue  # Compressed model entries are rebuilt with their subtable below.
            self._validate_asset((section, index), raw)
            span = self.rom.index_table(section).span(index)
            base = self.rom.read_asset(section, index)
            sections[int(section)] = sections[int(section)][:span.start] + raw + sections[int(section)][span.end:]
            uses = tuple(f"{level.index}: {level.name}" for level in self._catalog.levels if section == AssetType.LEVEL_HEADERS and level.index == index)
            fields = tuple(f"{field.label}: {field.read(base)} → {field.read(raw)}" for field in LEVEL_FIELDS if field.read(base) != field.read(raw)) if section == AssetType.LEVEL_HEADERS else ()
            changes = fields + tuple(f"byte 0x{i:02X}: 0x{a:02X} → 0x{b:02X}" for i, (a, b) in enumerate(zip(base, raw)) if a != b)
            if section == AssetType.OBJECTS:
                diffs.append(global_diff(self, index, raw, header_uses))
            else:
                diffs.append(AssetDiff(int(section), index, f"{section.name} {index}", len(base), len(raw), len(base), len(raw), uses, changes))
        name_updates={i:raw for (s,i),raw in self._assets.items() if s==AssetType.LEVEL_NAMES}
        if name_updates:
            for i,raw in name_updates.items():self._validate_asset((AssetType.LEVEL_NAMES,i),raw)
            table,names,name_diffs=prepare_name_sections(self.rom,name_updates)
            sections[24],sections[25]=table,names
            before=self.rom.index_table(AssetType.LEVEL_NAMES).offsets[-1]
            after=AssetTable.parse(table,len(names)).offsets[-1]
            diffs.extend(replace(d,changes=d.changes+(f'Whole name block loaded in RAM: {before:,} → {after:,} B ({after-before:+,}); ROM alignment is separate.',)) for d in name_diffs)
        model_ids = {index for section, index in self._assets if section == AssetType.LEVEL_MODELS}
        if model_ids:
            model_table = self.rom.index_table(AssetType.LEVEL_MODELS)
            chunks, offsets = [], [0]
            for index in range(len(model_table)):
                span = model_table.span(index)
                chunk = self.rom.section(AssetType.LEVEL_MODELS)[span.start:span.end]
                if index in model_ids:
                    key = AssetType.LEVEL_MODELS, index
                    raw = self._assets[key]
                    self._validate_asset(key, raw)
                    imported = index in self._track_imports
                    version = self.track_import_version(index)
                    overlay = raw
                    if imported:
                        from src.core.render_batches import rebatch_track
                        raw = rebatch_track(raw, segmented=version == 10)
                    cached = self._asset_packed_cache.get(key)
                    packed = cached[1] if cached is not None and cached[0] == raw else compress_segmented_track(raw) if version==10 else compress_asset(raw)
                    self._asset_packed_cache[key] = raw, packed
                    uses = tuple(f"{level.index}: {level.name}" for level in self._catalog.levels if level.header.geometry_id == index)
                    base = self.original_asset(*key)
                    if imported or geometry_changed(base, raw):
                        verify_geometry_stream(raw, packed)
                    comparison = self.track_base(index)
                    changes = ((f'Imported track: {LevelModel.from_bytes(base).triangle_count} → {self.track_model(index).triangle_count} faces / {len(self.track_model(index).segments)} segment(s); generated collision and visibility.',) if imported else ())
                    changes += material_changes(LevelModel.from_bytes(comparison), self.track_model(index)) + minimap_changes(comparison, raw) + geometry_changes(LevelModel.from_bytes(comparison), self.track_model(index))
                    if raw != overlay:
                        changes += ('Legacy draw batches split to at most 24 vertices; geometry, face order and collision retained.',)
                    diffs.append(AssetDiff(27, index, f"Track model {index}", len(base), len(raw), len(chunk), len(packed), uses, changes))
                    chunk = packed
                chunks.append(chunk)
                offsets.append(offsets[-1] + len(chunk))
            chunks.append(self.rom.section(AssetType.LEVEL_MODELS)[model_table.offsets[-1]:])
            table_raw = bytearray(sections[26])
            struct.pack_into(">" + str(len(offsets)) + "I", table_raw, 0, *offsets)
            sections[26], sections[27] = bytes(table_raw), b"".join(chunks)
            AssetTable.parse(sections[26], len(sections[27]))
        for section in sorted(IMAGE_SECTIONS):
            changed = {index for kind, index in self._assets if kind == section}
            additions = self._custom_textures if section==AssetType.TEXTURES_3D else ()
            if not changed and not additions:
                continue
            table = self.rom.index_table(section)
            data = self.rom.section(section)
            chunks, offsets = [], [0]
            for index in range(len(table)+len(additions)):
                added = index>=len(table)
                span = None if added else table.span(index)
                chunk = additions[index-len(table)] if added else data[span.start:span.end]
                if added:
                    h=validate_custom_texture(chunk)
                    uses=tuple(f'{l.index}: {l.name}' for l in self._catalog.levels if any(t.texture_id==index for t in self.track_model(l.header.geometry_id).textures))
                    diffs.append(AssetDiff(int(section),index,f'Dedicated 3D texture {index}',0,len(chunk),0,len(chunk),uses,
                        (f'{h.width}×{h.height} {h.format.name}; static, non-paletted; runtime allocation {len(chunk)+96:,} B when loaded.',)))
                if index in changed:
                    key = section, index
                    raw = self._assets[key]
                    self._validate_asset(key, raw)
                    packed = pack_texture(raw) if section in TEXTURE_SECTIONS else raw
                    base = self.original_asset(*key)
                    uses = tuple(sorted(self.image_uses.levels.get(key, set())))
                    details = tuple(sorted(self.image_uses.direct.get(key, set())))
                    if section in TEXTURE_SECTIONS:
                        before, after = texture_from_raw(base), texture_from_raw(raw)
                        import numpy as np
                        fields = tuple(f"Frame {i}: {int(np.count_nonzero(np.any(a.pixels != b.pixels, axis=2)))} changed pixels; timing {a.header.frame_advance} → {b.header.frame_advance}"
                                       for i, (a, b) in enumerate(zip(before.frames, after.frames)) if not np.array_equal(a.pixels, b.pixels) or a.header.frame_advance != b.header.frame_advance)
                    else:
                        fields = (f"Anchor {struct.unpack_from('>2h', base, 4)} → {struct.unpack_from('>2h', raw, 4)}",)
                    if not added:
                        diffs.append(AssetDiff(int(section), index, f"{section.name} {index}", len(base), len(raw), len(chunk), len(packed), uses,
                            fields + ("Known uses (compiled HUD/menu uses may also exist): " + "; ".join(details),)))
                    chunk = packed
                chunks.append(chunk)
                offsets.append(offsets[-1] + len(chunk))
            chunks.append(data[table.offsets[-1]:])
            from src.core.rom import INDEX_TABLES
            table_section = int(INDEX_TABLES[section])
            table_raw = bytearray(sections[table_section])
            if additions:
                tail = bytes(table_raw[4*len(table.offsets):])
                table_raw = bytearray(struct.pack('>'+str(len(offsets))+'I',*offsets)+tail)
                table_raw.extend(bytes(-len(table_raw)%16))
            else:
                struct.pack_into(">" + str(len(offsets)) + "I", table_raw, 0, *offsets)
            sections[table_section], sections[int(section)] = bytes(table_raw), b"".join(chunks)
            AssetTable.parse(sections[table_section], len(sections[int(section)]))
        prepared, all_diffs = prepare_object_art(self,
            {key: raw for key, raw in self._assets.items() if key[0] in MODEL_ASSETS}, tuple(sections), tuple(diffs))
        report = make_export_report(self.rom, prepared, all_diffs)
        from src.core.structure import workspace_usage
        workspace_errors = tuple(f'Object map {map_id}: {error}' for map_id, raw in sorted(self._modified.items())
            for error in workspace_usage(len(raw), len(self._packed_cache[map_id][1])).errors)
        if workspace_errors:
            report = replace(report, errors=report.errors+workspace_errors)
        from src.core.compression import CompressionError, audit_inplace_rare
        inflate_errors: list[str] = []
        for map_id in sorted(self._modified):
            try:
                audit_inplace_rare(self._packed_cache[map_id][1])
            except CompressionError as error:
                inflate_errors.append(f'Object map {map_id}: in-place inflater: {error}')
        if inflate_errors:
            report = replace(report, errors=report.errors+tuple(inflate_errors))
        if self._structures:
            try:
                validate_capacity(self, tuple(self._map_state(m) for m in sorted(self._structures)))
            except ValueError as error:
                report = replace(report, errors=report.errors+(str(error),))
        self._report_cache = signature, prepared, report
        return prepared, report

    def export_report(self) -> ExportReport:
        return self._prepare_export()[1]

    def build_rom(self) -> bytes:
        self._require_idle()
        if not self._modified and not self._assets and not self._custom_textures:
            return self.rom.data
        sections, report = self._prepare_export()
        return _assemble_rom(self.rom, sections, report)

    def save_rom(self, path: Path) -> Path:
        if path.suffix.casefold() != ".z64":
            raise EditError("Exported ROMs use big-endian .z64 format")
        if self.rom.source_path is not None and path.resolve() == self.rom.source_path.resolve():
            raise EditError("Choose a new file; the original ROM is read-only")
        return _atomic_write(path, self.build_rom(), self.rom.source_path)


class EditedRom(RomImage):
    """Read-only overlay view used by existing ROM-backed artwork loaders.

    The verified base image/section layout is retained. Entry reads resolve
    current session overlays; asset readers do not construct or publish a ROM.
    """
    session: EditSession

    def __init__(self, session: EditSession) -> None:
        rom = session.rom
        super().__init__(rom.data, rom.byte_order, rom.sections, rom.source_path)
        object.__setattr__(self, "session", session)

    def read_asset(self, asset_type: AssetType, index: int, *, decompress: bool = False) -> bytes:
        key = asset_type, index
        if asset_type==AssetType.TEXTURES_3D and index>=self.session.rom.count(asset_type):
            return self.session.current_asset(asset_type,index)
        if asset_type == AssetType.LEVEL_OBJECT_MAPS and index in self.session._modified:
            raw = _raw_map(self.session.current_map(index))
            return raw if decompress else compress_object_map(raw)
        if key in self.session._assets:
            raw = self.session._assets[key]
            if asset_type in TEXTURE_SECTIONS:
                return pack_texture(raw)
            if asset_type == AssetType.LEVEL_MODELS or asset_type in MODEL_ASSETS:
                return raw if decompress else compress_asset(raw)
            return raw
        return self.session.rom.read_asset(asset_type, index, decompress=decompress)

    def count(self, asset_type: AssetType) -> int:
        return self.session.rom.count(asset_type)+(len(self.session.custom_textures) if asset_type==AssetType.TEXTURES_3D else 0)

    @property
    def dedicated_texture_ids(self) -> range:
        start=self.session.rom.count(AssetType.TEXTURES_3D)
        return range(start,start+len(self.session.custom_textures))
