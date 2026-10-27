"""Object-map resource estimates and isolated structural drafts.

Sources: objects.c:44–51, 891–928, 978–1014, spawn_object; memory.c;
structs.h/object_properties.h; buildObjectMap.cpp. Nothing here enables the
production project's structural writer or a creation/deletion UI.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import re
import struct
from typing import TYPE_CHECKING, Any

from src.core.objects import LevelObject, ObjectDatabase, ObjectMap
from src.core.rom import REV1_SHA1, AssetType
from src.core.research import FieldNote, research_fields
from src.core.compression import CompressionError, audit_inplace_rare

if TYPE_CHECKING:
    from src.core.editing import EditSession

MAP_WORKSPACE = 0x3000
STAGING_SLACK = 0x20
OBJECT_POOL = 0x15800
OBJECT_SLOTS = 512
BLUEPRINT = 0x800
OBJECT_BYTES = 0x80  # 0x78 + eight-byte ObjProperties, NOT the stale 0x630 comment
MEMORY_SLOT_BYTES = 0x14
POOL_ALLOCATION_BOUND = 510  # allocator starts with a free slot, refuses at curNumSlots == 511
LAB_BEHAVIORS = frozenset((2, 17, 32))
PRODUCTION_STRUCTURAL_TYPES: frozenset[int] = frozenset()  # no blanket runtime certification; structural editing supports every object type


class StructureError(ValueError):
    """A structural experiment or source identity failed a checked constraint."""


def align(value: int, boundary: int) -> int:
    return (value+boundary-1) & -boundary


def raw_map(model: ObjectMap) -> bytes:
    if any(obj.raw_data is None for obj in model.objects):
        raise StructureError('Structural experiments require lossless ROM entries, not glTF records')
    return model.header+b''.join(obj.raw_data for obj in model.objects)+model.padding


@dataclass(frozen=True)
class WorkspaceUsage:
    decoded: int
    stored: int
    compressed_start: int
    required: int
    errors: tuple[str, ...]

    @property
    def remaining(self) -> int:
        return MAP_WORKSPACE-self.required


def workspace_usage(decoded: int, stored: int) -> WorkspaceUsage:
    """Necessary address bounds for source staging [U-C+32, U+32).

    U includes the 16-byte header and decoded alignment; C includes stored
    entry padding. These bounds alone do not certify in-place inflate overlap.
    """
    if type(decoded) is not int or type(stored) is not int or min(decoded, stored) < 0:
        raise StructureError('Map sizes must be nonnegative integers')
    if not stored:
        return WorkspaceUsage(decoded, stored, 0, 0, ('Nonempty decoded map has no stored stream',) if decoded else ())
    start, end = decoded-stored+STAGING_SLACK, decoded+STAGING_SLACK
    errors = []
    if start < 0:
        errors.append('Compressed map staging starts before its allocation')
    if end > MAP_WORKSPACE:
        errors.append(f'Map staging needs {end:,} B; workspace is {MAP_WORKSPACE:,} B')
    return WorkspaceUsage(decoded, stored, start, end, tuple(errors))


def simple_instance_bytes(obj: LevelObject) -> int | None:
    """Exact object-block size only for audited simple billboard candidates.

    Excludes shared headers, sprite/texture/main-pool allocations and runtime
    spawns. Every property function reserves (size & ~3)+4, including size zero.
    """
    h = obj.definition
    raw = h.raw_data
    if h.behavior_id not in LAB_BEHAVIORS or h.model_type != 1 or not h.model_ids or raw is None or len(raw) < 0x78:
        return None
    if any(raw[index] != 0 for index in (0x56, 0x57, 0x5A)):
        return None  # attachments, emitters, lights need their own resource audit
    properties = {2: 4, 17: 12, 32: 16}[h.behavior_id]
    shading = 12 if h.behavior_id == 2 else 0  # billboard shading returns (8 & ~3)+4
    return align(OBJECT_BYTES+4*len(h.model_ids)+properties+shading+16+40, 16)


def _pool_baseline(objects: tuple[LevelObject, ...]) -> int:
    headers = {obj.definition.header_id: obj.definition for obj in objects}
    return (sum(align(OBJECT_BYTES+4*len(o.definition.model_ids)+4, 16) for o in objects)
            + sum(align(len(d.raw_data or b''), 16) for d in headers.values()))


def _pool_allocations(objects: tuple[LevelObject, ...]) -> int:
    return len(objects)+len({o.definition.header_id for o in objects})


def template_reasons(obj: LevelObject) -> tuple[str, ...]:
    reasons: list[str] = []
    if obj.definition.behavior_id not in LAB_BEHAVIORS:
        reasons.append('Behavior is outside the ordinary scenery/banana/weapon-balloon allocation-estimate subset')
    if simple_instance_bytes(obj) is None:
        reasons.append('Object-block allocation is not fully audited for this header')
    if obj.definition.behavior_id == 2:
        selection = int(obj.value('modelIndex', 0))
        if not 0 <= selection < len(obj.definition.model_ids):
            reasons.append('Scenery model index is outside its header')
    if obj.definition.behavior_id == 17:
        selection = int(obj.value('balloonType', -1))
        if not 0 <= selection < min(5, len(obj.definition.model_ids)):
            reasons.append('Balloon type is outside its verified five choices/header models')
    if obj.raw_data is None:
        reasons.append('Lossless template bytes are unavailable')
    return tuple(reasons)


def decorative_reasons(obj: LevelObject) -> tuple[str, ...]:
    """Conservative cost/reference subset for allocation estimates.

    Scenery's four parameters have no node/reference ID. Non-solid entries with
    zero emitters cannot enter its collision sound/emission path. Shadow group
    zero avoids per-instance texture loads (textures have u8 reference counts).
    """
    reasons = list(template_reasons(obj))
    header = obj.definition.raw_data
    if obj.definition.behavior_id != 2 or obj.byte_size != 12:
        reasons.append('Only the complete 12-byte scenery schema is in this subset')
    if obj.value('solid', -1) != 0:
        reasons.append('Collidable scenery has sound/interaction side effects')
    if header is None or len(header) < 0x34 or struct.unpack_from('>h', header, 0x32)[0] != 0:
        reasons.append('Shadow textures add per-instance texture references')
    if len(obj.definition.model_ids) != 1:
        reasons.append('Only one-sprite headers are in the narrow decorative subset')
    return tuple(reasons)


def known_incoming(objects: tuple[LevelObject, ...], target: LevelObject) -> tuple[str, ...]:
    """Known references are evidence for blocking, never proof of no references."""
    references: list[str] = []
    if target.definition.behavior_id == 13:
        references.append('Checkpoint ordering, set counts and alternate pairing require graph rebuilding')
    for obj in objects:
        if target.definition.behavior_id == 16 and obj.definition.behavior_id == 16:
            ident = int(target.value('nodeID', 255))
            if ident != 255 and ident in obj.value('adjacent', ()):
                references.append(f'AI node {obj.map_id}:{obj.index} links to ID {ident}')
        if target.definition.behavior_id == 49 and obj.definition.behavior_id == 49:
            actor = int(target.value('actorIndex', 0))
            if ((obj.value('rotateType', 0) == 3 and obj.value('nextAnim', -1) == actor)
                    or (actor >= 0 and obj.value('unk15', -1) == actor)):
                references.append(f'Animation {obj.map_id}:{obj.index} refers to actor {actor}')
    return tuple(dict.fromkeys(references))


def rebuild_map(model: ObjectMap, entries: tuple[bytes, ...], database: ObjectDatabase) -> bytes:
    """Deterministic payload/header/padding; exact no-edit identity, no alias IDs lost."""
    original = raw_map(model)
    if entries == tuple(obj.raw_data for obj in model.objects):
        return original
    if not model.header:
        raise StructureError('Vacant asset slots have no template header; activation is not enabled')
    if not isinstance(entries, tuple) or any(not isinstance(entry, bytes) for entry in entries):
        raise StructureError('Entries must be immutable byte records')
    header = bytearray(model.header)
    if len(header) != 16:
        raise StructureError('Object maps require a 16-byte template header')
    payload = b''.join(entries)
    struct.pack_into('>I', header, 0, len(payload))
    raw = bytes(header)+payload+bytes((-len(payload)) % 8)
    parsed = ObjectMap.from_bytes(raw, database, map_id=model.map_id)
    if len(parsed.objects) != len(entries) or tuple(o.raw_data for o in parsed.objects) != entries:
        raise StructureError('Entry boundaries or schema changed during rebuilding')
    return raw


@dataclass(frozen=True)
class MapAudit:
    map_id: int
    entries: int
    usage: WorkspaceUsage
    header_bytes: int
    baseline_object_bytes: int
    simple_count: int
    simple_object_bytes: int
    template_count: int
    maximum_header_references: int
    levels: tuple[str, ...]
    errors: tuple[str, ...]
    inflate_gap: int | None = None
    huft_bytes: int = 0
    decorative_count: int = 0


@dataclass(frozen=True)
class StructuralAudit:
    maps: tuple[MapAudit, ...]
    maximum_loaded_entries: int
    maximum_entry_context: str
    maximum_pool_baseline: int
    pool_context: str
    errors: tuple[str, ...]
    references: tuple[str, ...]

    def to_text(self) -> str:
        lines = ['OBJECT MAP RESOURCE USAGE — read-only estimate',
            'ROM padding is storage. It is not map workspace or spare runtime object memory.',
            f'Map workspace {MAP_WORKSPACE:,} B; require decoded U + 32 <= {MAP_WORKSPACE:,}, stored C <= U + 32.',
            'U includes header/alignment. Maximum decoded U = 12,256 B (0x2FE0).',
            'Per-stream source-model checks report in-place inflate gaps and errors below.',
            'Address bounds alone do not certify in-place inflate; modified exports are checked again.',
            f'Object pool {OBJECT_POOL:,} B; object list {OBJECT_SLOTS} slots; spawn blueprint {BLUEPRINT:,} B.',
            'Pool metadata: 512 × 20 B allocated separately from the 88,064 B pool data.',
            'Allocator refuses when 511 descriptors are in use; fragmentation can exhaust them before bytes.',
            'Object is 128 B + pointers/properties/effects; shared headers ALSO occupy this pool.',
            '512 is a total runtime limit, not an allowed number of placed objects.',
            f'Largest header-referenced entry total: {self.maximum_loaded_entries} ({self.maximum_entry_context}).',
            f'Largest all-entry baseline demand: {self.maximum_pool_baseline:,} B ({self.pool_context}).',
            'Baseline includes aligned Object+model-pointer+minimum-property blocks and distinct headers only.',
            'It excludes larger behavior/effect blocks, live racers, attachments, script targets, weapons,',
            'dropped bananas, particles, model/sprite/texture allocations and heap fragmentation.',
            'No proven peak/spawn reserve or safe additional-object count is established.',
            'Gameplay particle buffers allow up to 319 particles; menu buffers up to 193.',
            'Particles use the SAME object list, though their buffers are outside the object subpool.',
            'These are independent maxima, not observed simultaneous peaks or an addition allowance.',
            'Other caches also have limits: 70 object models, 100 sprites, 700 textures, 20 palettes.',
            'Their transitive/current dynamic use is not a proven reserve in this audit.',
            'Simple billboard scenery, bananas and weapon balloons have baseline allocation estimates.',
            'Dynamic behavior can allocate additional resources beyond these baseline estimates.',
            'Narrower decoration candidates have no collision/emitter/attachment/light/shadow texture.',
            f'Current narrow decoration candidates: {sum(m.decorative_count for m in self.maps)} placements.',
            'Load RDRAM snapshots to inspect the active object list, allocator and asset counters.',
            'Review node IDs, progression fields and copied links when adding or duplicating objects.',
            'There is also a separate 257-pointer interaction array and fixed shadow buffers; peaks are unproven.',
            'Shared uses below are current level-header references; compiled/script uses may add more.', '']
        lines.extend(f'ISSUE: {error}' for error in self.errors)
        lines.extend(('', 'Known graph/reference diagnostics (pre-existing findings are not repaired):'))
        lines.extend(self.references or ('No known graph/reference diagnostics found.',))
        lines.append('')
        for m in self.maps:
            lines.append(f'Map {m.map_id}: {m.entries} entries; decoded {m.usage.decoded:,}; stored {m.usage.stored:,}; '
                         f'staging {m.usage.required:,}/{MAP_WORKSPACE}; templates {m.template_count}; '
                         f'max placed/header {m.maximum_header_references}; simple blocks {m.simple_count}/{m.entries} = {m.simple_object_bytes:,} B')
            if m.inflate_gap is not None:
                lines.append(f'  Source-model inflate: minimum unread-input gap {m.inflate_gap} B; Huffman heap {m.huft_bytes}/10240 B.')
            lines.append(f'  Cost-audited narrow decoration candidates: {m.decorative_count}; not an all-type runtime reserve.')
            lines.append('  Shared levels: '+('; '.join(m.levels) or 'No current header reference'))
            lines.extend('  ISSUE: '+error for error in m.errors)
        return '\n'.join(lines)


def audit_session(session: EditSession) -> StructuralAudit:
    """Current overlays, both map roles including duplicates; no project mutation."""
    from src.core.editing import compress_object_map
    contexts: list[tuple[str, tuple[int, ...]]] = []
    uses: dict[int, list[str]] = {}
    for level in session._catalog.levels:
        header = session.level_header(level.index)
        maps = tuple(i for i in (header.object_map_id, header.secondary_object_map_id) if i >= 0)
        label = f'{level.index}: {level.name}'
        contexts.append((label, maps))
        for map_id in set(maps):
            uses.setdefault(map_id, []).append(label)
    audits: list[MapAudit] = []
    parsed: dict[int, ObjectMap] = {}
    table = session.rom.index_table(AssetType.LEVEL_OBJECT_MAPS)
    for map_id in range(len(table)):
        model = session.current_map(map_id)
        parsed[map_id] = model
        raw = raw_map(model)
        stored = len(compress_object_map(raw)) if map_id in session.modified_maps else table.span(map_id).size
        usage = workspace_usage(len(raw), stored)
        definitions = {o.definition.header_id: o.definition for o in model.objects}
        headers = sum(align(len(d.raw_data or b''), 16) for d in definitions.values())
        baseline = sum(align(OBJECT_BYTES+4*len(o.definition.model_ids)+4, 16) for o in model.objects)
        exact = [size for o in model.objects if (size := simple_instance_bytes(o)) is not None]
        maximum = max(Counter(o.definition.header_id for o in model.objects).values(), default=0)
        errors = list(usage.errors)
        inflate = None
        if stored:
            packed = compress_object_map(raw) if map_id in session.modified_maps else session.rom.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id)
            try:
                inflate = audit_inplace_rare(packed)
            except CompressionError as error:
                errors.append(f'In-place inflater: {error}')
        if len(model.objects) > OBJECT_SLOTS:
            errors.append('Placed entries alone exceed the runtime object list')
        if maximum > 255:
            errors.append('Placed header references alone overflow the unsigned-byte reference count')
        audits.append(MapAudit(map_id, len(model.objects), usage, headers, baseline, len(exact), sum(exact),
            sum(not template_reasons(o) for o in model.objects), maximum, tuple(uses.get(map_id, ())), tuple(errors),
            inflate.minimum_gap if inflate else None, inflate.huft_bytes if inflate else 0,
            sum(not decorative_reasons(o) for o in model.objects)))
    max_count, count_context, max_floor, floor_context = 0, '', 0, ''
    errors: list[str] = []
    for label, maps in contexts:
        objects = tuple(o for map_id in maps for o in parsed[map_id].objects)
        floor = _pool_baseline(objects)
        if len(objects) > max_count:
            max_count, count_context = len(objects), label
        if floor > max_floor:
            max_floor, floor_context = floor, label
        if len(objects) > OBJECT_SLOTS or floor > OBJECT_POOL:
            errors.append(f'{label}: all-entry baseline exceeds a runtime bound; runtime filtering is not modeled')
        if _pool_allocations(objects) > POOL_ALLOCATION_BOUND:
            errors.append(f'{label}: placed object/header allocation count exceeds the allocator descriptor bound')
        if max(Counter(o.definition.header_id for o in objects).values(), default=0) > 255:
            errors.append(f'{label}: combined placed header references exceed 255')
    from src.core.routes import route_diagnostics
    references: list[str] = []
    for (label, maps), level in zip(contexts, session._catalog.levels):
        objects = tuple(o for map_id in maps for o in parsed[map_id].objects)
        header = session.level_header(level.index)
        for issue in route_diagnostics(objects, header.checkpoint_sets):
            if issue.code in ('dangling-link', 'ambiguous-link', 'duplicate-node', 'orphan-alternate', 'checkpoint-capacity'):
                references.append(f'{label}: {issue.message}')
        for obj in objects:
            if obj.definition.behavior_id == 49 and obj.value('objectIdToSpawn', -1) >= 0:
                try:
                    session.database.resolve(int(obj.value('objectIdToSpawn')))
                except ValueError:
                    references.append(f'{label}: Animation {obj.map_id}:{obj.index} has an unresolved spawn ID')
    return StructuralAudit(tuple(audits), max_count, count_context, max_floor, floor_context, tuple(errors), tuple(references))


@dataclass(frozen=True)
class DraftEntry:
    identity: str
    template: str
    raw: bytes


@dataclass(frozen=True)
class DraftChange:
    before: tuple[DraftEntry, ...]
    after: tuple[DraftEntry, ...]
    label: str


class StructuralDraft:
    """Isolated diagnostic draft, separate from editor projects.

    Supports templates, serialization and history, and can return diagnostic ROM
    bytes in memory. This API does not install changes into an editor session.
    The source session is an immutable dependency: a changed signature rejects
    export/reload instead of merging silently. Use the editor object tools for normal editing.
    """
    def __init__(self, session: EditSession, map_id: int) -> None:
        if session._structures:
            raise StructureError('Use the editor structural tools for version7 structural projects; this older diagnostic draft needs original identities')
        self._session = session
        self.source_signature = session._signature()
        self.model = session.current_map(map_id)
        self.source_raw = raw_map(self.model)
        self.source_digest = hashlib.sha256(self.source_raw).hexdigest()
        self.source_ids = tuple(f'base:{map_id}:{o.index}:{hashlib.sha1(session.original_map(map_id).objects[o.index].raw_data).hexdigest()}'
                                for o in self.model.objects)
        self.templates = dict(zip(self.source_ids, self.model.objects))
        self.entries = tuple(DraftEntry(identity, identity, o.raw_data) for identity, o in zip(self.source_ids, self.model.objects))
        self.notes: dict[tuple[str, str], FieldNote] = {(identity, field.key): session.note(o.key, field.key)
            for identity, o in zip(self.source_ids, self.model.objects) for field in research_fields(o)
            if session.note(o.key, field.key) != FieldNote()}
        self._history: list[DraftChange] = []
        self._cursor = 0
        self._serial = 1  # not rolled back; branching never reuses a discarded new identity

    @property
    def map_id(self) -> int:
        return self.model.map_id

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._history)

    def index(self, identity: str) -> int:
        try:
            return next(i for i, item in enumerate(self.entries) if item.identity == identity)
        except StopIteration as error:
            raise StructureError('Entry identity is absent from this draft') from error

    def _candidate(self, identity: str) -> DraftEntry:
        entry = self.entries[self.index(identity)]
        reasons = template_reasons(self.templates[entry.template])
        if reasons:
            incoming = known_incoming(self.model.objects, self.templates[entry.template])
            raise StructureError('Protected/unresolved template: '+'; '.join((*reasons, *incoming)))
        return entry

    def _validate(self, entries: tuple[DraftEntry, ...]) -> bytes:
        from src.core.editing import compress_object_map
        if len({e.identity for e in entries}) != len(entries):
            raise StructureError('Duplicate stable entry identities')
        raw = rebuild_map(self.model, tuple(e.raw for e in entries), self._session.database)
        usage = workspace_usage(len(raw), len(compress_object_map(raw)))
        if usage.errors:
            raise StructureError('; '.join(usage.errors))
        if raw:
            try:
                audit_inplace_rare(compress_object_map(raw))
            except CompressionError as error:
                raise StructureError(f'In-place inflater: {error}') from error
        if len(entries) > OBJECT_SLOTS:
            raise StructureError('Placed entries exceed the total runtime object-list bound')
        definitions = [self.templates[e.template].definition for e in entries]
        if len(definitions)+len({d.header_id for d in definitions}) > POOL_ALLOCATION_BOUND:
            raise StructureError('Object/header allocation count exceeds the pool descriptor bound')
        if max(Counter(d.header_id for d in definitions).values(), default=0) > 255:
            raise StructureError('Placed header references exceed the unsigned-byte count bound')
        floor = sum(align(OBJECT_BYTES+4*len(d.model_ids)+4, 16) for d in definitions)
        floor += sum(align(len(d.raw_data or b''), 16) for d in {d.header_id: d for d in definitions}.values())
        if floor > OBJECT_POOL:
            raise StructureError('All-entry baseline exceeds the object pool before dynamic/effect costs')
        candidate = ObjectMap.from_bytes(raw, self._session.database, map_id=self.map_id)
        for level in self._session._catalog.levels:
            header = self._session.level_header(level.index)
            maps = tuple(i for i in (header.object_map_id, header.secondary_object_map_id) if i >= 0)
            if self.map_id not in maps:
                continue
            combined = tuple(o for map_id in maps for o in (candidate if map_id == self.map_id else self._session.current_map(map_id)).objects)
            if len(combined) > OBJECT_SLOTS or _pool_baseline(combined) > OBJECT_POOL:
                raise StructureError(f'Level {level.index}: combined shared-map entries exceed a necessary runtime bound')
            if _pool_allocations(combined) > POOL_ALLOCATION_BOUND:
                raise StructureError(f'Level {level.index}: combined pool allocation count exceeds the descriptor bound')
            if max(Counter(o.definition.header_id for o in combined).values(), default=0) > 255:
                raise StructureError(f'Level {level.index}: combined header reference count exceeds 255')
        return raw

    def _commit(self, entries: tuple[DraftEntry, ...], label: str) -> bool:
        if entries == self.entries:
            return False
        self._validate(entries)
        self._history[self._cursor:] = [DraftChange(self.entries, entries, label)]
        self._cursor += 1
        self.entries = entries
        return True

    def append(self, identity: str, position: tuple[int, int, int] | None = None) -> str:
        if self._serial >= 1000000:
            raise StructureError('Diagnostic identity counter is exhausted')
        template = self._candidate(identity)
        raw = bytearray(template.raw)
        if position is not None:
            if not isinstance(position, tuple) or len(position) != 3 or any(type(v) is not int or not -32768 <= v <= 32767 for v in position):
                raise StructureError('Position must contain three signed16 integers')
            struct.pack_into('>hhh', raw, 2, *position)
        new_id = f'new:{self.map_id}:{self._serial}'
        self._commit((*self.entries, DraftEntry(new_id, template.template, bytes(raw))), 'Append diagnostic template')
        self._serial += 1
        return new_id

    def remove(self, identity: str) -> None:
        self._candidate(identity)
        self._commit(tuple(e for e in self.entries if e.identity != identity), 'Remove diagnostic entry')

    def reorder(self, identities: tuple[str, ...]) -> None:
        if not isinstance(identities, tuple) or len(identities) != len(self.entries) or set(identities) != {e.identity for e in self.entries}:
            raise StructureError('Order must contain every current stable identity exactly once')
        by_id = {e.identity: e for e in self.entries}
        entries = tuple(by_id[identity] for identity in identities)
        for old, new in zip(self.entries, entries):
            if old.identity != new.identity:
                self._candidate(old.identity)
                self._candidate(new.identity)
        self._commit(entries, 'Reorder diagnostic entries')

    def undo(self) -> None:
        if self.can_undo:
            self._cursor -= 1
            self.entries = self._history[self._cursor].before

    def redo(self) -> None:
        if self.can_redo:
            self.entries = self._history[self._cursor].after
            self._cursor += 1

    def serialize(self) -> bytes:
        return self._validate(self.entries)

    def document(self) -> dict[str, Any]:
        """Legacy diagnostic format: templates and positions without arbitrary binary patches."""
        return {'format': 'dkr-structural-research', 'version': 1, 'base_rom_sha1': REV1_SHA1,
            'source_signature': self.source_signature, 'source_map_sha256': self.source_digest,
            'map_id': self.map_id, 'next_serial': self._serial,
            'entries': [{'id': e.identity, 'template': e.template, 'position': list(struct.unpack_from('>hhh', e.raw, 2))} for e in self.entries]}

    @classmethod
    def from_document(cls, session: EditSession, document: dict[str, Any]) -> StructuralDraft:
        if (not isinstance(document, dict) or document.get('format') != 'dkr-structural-research'
                or type(document.get('version')) is not int or document['version'] != 1
                or document.get('base_rom_sha1') != REV1_SHA1 or type(document.get('map_id')) is not int):
            raise StructureError('Unsupported structural diagnostic document')
        draft = cls(session, document['map_id'])
        if (document.get('source_signature') != draft.source_signature or document.get('source_map_sha256') != draft.source_digest):
            raise StructureError('Diagnostic document does not match its source project/map')
        rows = document.get('entries')
        serial = document.get('next_serial')
        if not isinstance(rows, list) or len(rows) > OBJECT_SLOTS or type(serial) is not int or not 1 <= serial <= 1000000:
            raise StructureError('Invalid diagnostic entry list/identity counter')
        entries: list[DraftEntry] = []
        maximum = 0
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('template'), str) or row['template'] not in draft.templates:
                raise StructureError('Diagnostic entry has an invalid template')
            identity, template = row.get('id'), row['template']
            new = re.fullmatch(rf'new:{draft.map_id}:([1-9][0-9]*)', identity) if isinstance(identity, str) else None
            if identity != template:
                if new is None or template_reasons(draft.templates[template]):
                    raise StructureError('Protected/unresolved new entry template/identity')
                maximum = max(maximum, int(new[1]))
            position = row.get('position')
            if not isinstance(position, list) or len(position) != 3 or any(type(v) is not int or not -32768 <= v <= 32767 for v in position):
                raise StructureError('Invalid diagnostic signed16 position')
            raw = bytearray(draft.templates[template].raw_data)
            struct.pack_into('>hhh', raw, 2, *position)
            if template_reasons(draft.templates[template]) and bytes(raw) != draft.templates[template].raw_data:
                raise StructureError('Protected graph/unknown entry cannot be changed in diagnostic documents')
            entries.append(DraftEntry(identity, template, bytes(raw)))
        protected = [e.identity for e in draft.entries if template_reasons(draft.templates[e.template])]
        if [e.identity for e in entries if e.identity in protected] != protected:
            raise StructureError('Protected graph/unknown entries cannot be removed or reordered')
        if serial <= maximum:
            raise StructureError('New identity counter would reuse an existing identity')
        draft._validate(tuple(entries))
        draft.entries, draft._serial = tuple(entries), serial
        return draft

    def experimental_rom_bytes(self) -> bytes:
        """Diagnostic in-memory writer; no save method or editor integration."""
        from src.core.editing import compress_object_map, _assemble_rom
        from src.core.export_report import make_export_report
        if self._session._signature() != self.source_signature:
            raise StructureError('Source project changed after this diagnostic draft was created')
        raw = self.serialize()
        if raw == self.source_raw:
            return self._session.build_rom()
        sections = list(self._session._prepare_export()[0])
        from src.core.rom import AssetTable
        table = AssetTable.parse(sections[20], len(sections[21]))
        chunks: list[bytes] = []
        offsets = [0]
        for map_id in range(len(table)):
            span = table.span(map_id)
            chunk = compress_object_map(raw) if map_id == self.map_id else sections[21][span.start:span.end]
            chunks.append(chunk); offsets.append(offsets[-1]+len(chunk))
        chunks.append(sections[21][table.offsets[-1]:])
        index = bytearray(sections[20])
        struct.pack_into('>'+str(len(offsets))+'I', index, 0, *offsets)
        sections[20], sections[21] = bytes(index), b''.join(chunks)
        prepared = tuple(sections)
        return _assemble_rom(self._session.rom, prepared, make_export_report(self._session.rom, prepared, ()))
