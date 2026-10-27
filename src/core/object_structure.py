"""All translated object types: templates, stable identities and structural IO.

Source: level_object_entries.h/ENTRY_LAYOUTS, buildObjectMap.cpp, objects.c.
Templates preserve source encodings for all object types;
known serialization/capacity constraints still apply. Pure core, no Qt/GL.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import struct
from typing import TYPE_CHECKING, Any

from src.core.objects import ENTRY_LAYOUTS, ObjectMap, LevelObject
from src.core.rom import AssetType
from src.core.structure import (OBJECT_BYTES, OBJECT_POOL, OBJECT_SLOTS,
    POOL_ALLOCATION_BOUND, StructureError, raw_map, workspace_usage, known_incoming)
from src.core.compression import audit_inplace_rare

if TYPE_CHECKING:
    from src.core.editing import EditSession

MAX_IDENTITY = 1_000_000


@dataclass(frozen=True)
class ObjectTemplate:
    object_id: int
    map_id: int | None = None
    entry_index: int | None = None

    def raw(self, session: EditSession) -> bytes:
        definition = session.database.resolve(self.object_id)
        if self.map_id is None:
            if self.entry_index is not None:
                raise StructureError('Schema template cannot have a source entry')
            size = ENTRY_LAYOUTS[definition.behavior_id][0] if definition.behavior_id >= 0 else 8
            entry = bytearray(size)  # Explicit zero-initialized schema, no invented semantic defaults.
            entry[1] = size
        else:
            if type(self.entry_index) is not int or not 0 <= self.entry_index < len(session.original_map(self.map_id).objects):
                raise StructureError('Template source entry is absent')
            source = session.original_map(self.map_id).objects[self.entry_index]
            if source.definition.header_id != definition.header_id:
                raise StructureError('Template object header does not match its source')
            entry = bytearray(source.raw_data or b'')
        if not 8 <= len(entry) <= 63:
            raise StructureError('Template entry length is outside the six-bit serialized range')
        entry[0] = self.object_id & 255
        entry[1] = (entry[1] & 0x7F) | ((self.object_id >> 1) & 0x80)
        return bytes(entry)

    @property
    def description(self) -> str:
        return f'Stock map {self.map_id}, entry {self.entry_index}' if self.map_id is not None else 'Zeroed schema defaults (untested)'


@dataclass(frozen=True)
class EntryIdentity:
    value: int
    template: ObjectTemplate
    initial: bytes


@dataclass(frozen=True)
class MapState:
    map_id: int
    raw: bytes
    identities: tuple[EntryIdentity, ...]


@dataclass(frozen=True)
class StructureChange:
    before: tuple[MapState, ...]
    after: tuple[MapState, ...]
    notes_before: tuple[tuple[tuple[int, int, str], Any], ...]
    notes_after: tuple[tuple[tuple[int, int, str], Any], ...]
    selection_before: tuple[tuple[int, int], ...]
    selection_after: tuple[tuple[int, int], ...]
    label: str


def base_identities(session: EditSession, map_id: int) -> tuple[EntryIdentity, ...]:
    return tuple(EntryIdentity(obj.index, ObjectTemplate(obj.object_id, map_id, obj.index), obj.raw_data or b'')
                 for obj in session.original_map(map_id).objects)


def identify(model: ObjectMap, identities: tuple[EntryIdentity, ...]) -> ObjectMap:
    if len(identities) != len(model.objects):
        raise StructureError('Stable identity count differs from serialized entry count')
    return replace(model, objects=tuple(replace(obj, index=identity.value)
        for obj, identity in zip(model.objects, identities)))


def rebuild(session: EditSession, map_id: int, entries: tuple[bytes, ...]) -> bytes:
    original = session.original_map(map_id)
    if entries == tuple(obj.raw_data for obj in original.objects):
        return raw_map(original)
    header = bytearray(original.header or bytes(16))
    payload = b''.join(entries)
    struct.pack_into('>I', header, 0, len(payload))
    return bytes(header) + payload + bytes((-len(payload)) % 8)


def validate_state(session: EditSession, state: MapState) -> ObjectMap:
    model = ObjectMap.from_bytes(state.raw, session.database, map_id=state.map_id)
    original = session.original_map(state.map_id)
    if state.raw and (len(model.header) != 16 or model.header[4:] != (original.header or bytes(16))[4:]):
        raise StructureError('Reserved object-map header bytes changed')
    if len(state.identities) != len(model.objects) or len({i.value for i in state.identities}) != len(state.identities):
        raise StructureError('Missing/duplicate stable object identities')
    for obj, identity in zip(model.objects, state.identities):
        if type(identity.value) is not int or not 0 <= identity.value < MAX_IDENTITY:
            raise StructureError('Invalid stable object identity')
        template = identity.template.raw(session)
        if (len(identity.initial) != len(template) or identity.initial[:2] != template[:2]
                or obj.raw_data[:2] != template[:2] or len(obj.raw_data) != len(template)):
            raise StructureError('Entry ID/size/flags differ from the verified template')
        # Original IDs continue to mean their original entry even after deletions.
        if identity.value < len(original.objects):
            base = original.objects[identity.value]
            if (identity.template != ObjectTemplate(base.object_id, state.map_id, base.index)
                    or identity.initial != base.raw_data):
                raise StructureError('Original entry identity/provenance was reassigned')
    if len(model.objects) > OBJECT_SLOTS:
        raise StructureError('Object map exceeds the 512-entry list bound')
    return identify(model, state.identities)


def validate_capacity(session: EditSession, states: tuple[MapState, ...]) -> None:
    from src.core.editing import compress_object_map
    if len({state.map_id for state in states}) != len(states):
        raise StructureError('Duplicate map in structural transaction')
    candidates: dict[int, ObjectMap] = {}
    for state in states:
        model = validate_state(session, state)
        candidates[state.map_id] = model
        if state.raw:
            packed = compress_object_map(state.raw)
            errors = workspace_usage(len(state.raw), len(packed)).errors
            if errors:
                raise StructureError('; '.join(errors))
            audit_inplace_rare(packed)
    contexts = []
    covered: set[int] = set()
    for level in session._catalog.levels:
        header = session.level_header(level.index)
        maps = tuple(m for m in (header.object_map_id, header.secondary_object_map_id) if m >= 0)
        if any(m in candidates for m in maps):
            contexts.append((f'{level.index}: {level.name}', maps))
            covered.update(maps)
    contexts.extend((f'Map {m}', (m,)) for m in candidates if m not in covered)
    for name, maps in contexts:
        objects = tuple(obj for m in maps for obj in (candidates[m] if m in candidates else session.current_map(m)).objects)
        definitions = {obj.definition.header_id: obj.definition for obj in objects}
        if len(objects) > OBJECT_SLOTS:
            raise StructureError(f'{name}: combined map entries exceed 512 object slots')
        if max(Counter(obj.definition.header_id for obj in objects).values(), default=0) > 255:
            raise StructureError(f'{name}: placed header references exceed the unsigned-byte counter')
        if len(objects) + len(definitions) > POOL_ALLOCATION_BOUND:
            raise StructureError(f'{name}: minimum object/header allocations exceed the descriptor bound')
        minimum = sum(((OBJECT_BYTES + 4*len(obj.definition.model_ids) + 4 + 15) & ~15) for obj in objects)
        minimum += sum((len(d.raw_data or b'') + 15) & ~15 for d in definitions.values())
        if minimum > OBJECT_POOL:
            raise StructureError(f'{name}: minimum object/header allocation exceeds the object pool')


def catalog(session: EditSession) -> tuple[ObjectTemplate, ...]:
    """Every valid translated ID, preferring actual placements over schema zeros."""
    stock: dict[int, ObjectTemplate] = {}
    for map_id in range(session.rom.count(AssetType.LEVEL_OBJECT_MAPS)):
        for obj in session.original_map(map_id).objects:
            stock.setdefault(obj.definition.header_id, ObjectTemplate(obj.object_id, map_id, obj.index))
    return tuple(ObjectTemplate(i, stock[header].map_id, stock[header].entry_index)
        if header in stock else ObjectTemplate(i)
        for i, header in enumerate(session.database.translation) if 0 <= header < len(session.database.definitions))


def diagnostics(session: EditSession, objects: tuple[LevelObject, ...], *, deleting: bool = False) -> tuple[str, ...]:
    lines = ['Object additions share runtime pools, asset caches and interaction/shadow buffers with the active scene.']
    for obj in objects:
        if obj.definition.behavior_id in (13, 16, 49):
            lines.append(f'{obj.definition.name}: identity/order/link fields are copied verbatim; update IDs and links manually. No automatic graph repair.')
        if deleting:
            maps = {obj.map_id}
            for level in session._catalog.levels:
                header = session.level_header(level.index)
                pair = (header.object_map_id, header.secondary_object_map_id)
                if obj.map_id in pair:
                    maps.update(m for m in pair if m >= 0)
            lines.extend(known_incoming(tuple(o for m in maps for o in session.current_map(m).objects), obj))
    return tuple(dict.fromkeys(lines))


def _patches(base: bytes, current: bytes) -> list[dict[str, int]]:
    return [{'offset': i, 'value': b} for i, (a, b) in enumerate(zip(base, current)) if a != b]


def _apply(base: bytes, rows: object) -> bytes:
    if not isinstance(rows, list) or len(rows) > len(base)-2:
        raise StructureError('Invalid structural entry patches')
    raw = bytearray(base)
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise StructureError('Invalid entry patch')
        offset, value = row.get('offset'), row.get('value')
        if type(offset) is not int or not 2 <= offset < len(raw) or offset in seen or type(value) is not int or not 0 <= value <= 255:
            raise StructureError('Invalid/duplicate entry patch offset or value')
        seen.add(offset)
        raw[offset] = value
    return bytes(raw)


def state_document(session: EditSession, state: MapState, next_id: int) -> dict[str, Any]:
    model = validate_state(session, state)
    rows = []
    for obj, identity in zip(model.objects, state.identities):
        template = identity.template
        base = template.raw(session)
        rows.append({'id': identity.value, 'template': {'object_id': template.object_id,
            'map_id': template.map_id, 'entry_index': template.entry_index,
            'sha1': hashlib.sha1(base).hexdigest()}, 'initial': _patches(base, identity.initial),
            'bytes': _patches(identity.initial, obj.raw_data)})
    return {'map_id': state.map_id, 'base_map_sha1': hashlib.sha1(raw_map(session.original_map(state.map_id))).hexdigest(),
            'next_id': next_id, 'entries': rows}


def state_from_document(session: EditSession, doc: object) -> tuple[MapState, int]:
    if not isinstance(doc, dict) or type(doc.get('map_id')) is not int:
        raise StructureError('Invalid structural map document')
    map_id = doc['map_id']
    original = session.original_map(map_id)
    if doc.get('base_map_sha1') != hashlib.sha1(raw_map(original)).hexdigest():
        raise StructureError('Structural map does not match its base ROM')
    rows, counter = doc.get('entries'), doc.get('next_id')
    if not isinstance(rows, list) or len(rows) > OBJECT_SLOTS or type(counter) is not int or not len(original.objects) <= counter <= MAX_IDENTITY:
        raise StructureError('Invalid structural entry list/counter')
    identities, entries = [], []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('template'), dict):
            raise StructureError('Invalid structural entry template')
        t = row['template']
        object_id, source_map, source_index = t.get('object_id'), t.get('map_id'), t.get('entry_index')
        if type(object_id) is not int or not 0 <= object_id < 512 or (source_map is not None and type(source_map) is not int):
            raise StructureError('Invalid structural template ID/source')
        template = ObjectTemplate(object_id, source_map, source_index)
        raw = template.raw(session)
        if t.get('sha1') != hashlib.sha1(raw).hexdigest():
            raise StructureError('Structural template hash mismatch')
        identity = row.get('id')
        if type(identity) is not int or not 0 <= identity < counter:
            raise StructureError('Stable identity would reuse or exceed its counter')
        initial = _apply(raw, row.get('initial'))
        identities.append(EntryIdentity(identity, template, initial))
        entries.append(_apply(initial, row.get('bytes')))
    state = MapState(map_id, rebuild(session, map_id, tuple(entries)), tuple(identities))
    validate_state(session, state)
    return state, counter
