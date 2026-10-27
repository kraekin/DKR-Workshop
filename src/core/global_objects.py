"""Fixed-layout shared object definitions, source-traced fields and references.

Local sources: structs.h:ObjectHeader (0x78; shadowBottom is 0x46 despite
its stale comment); objects.c:891-920,1934-2147,2290-2418,3480-3640,
7879-7899,10458-10594; tracks.c:2328-2349,3421-3461,3565-3566.
Unknowns, allocation flags, behavior/type/counts, pointers and tail data stay
byte-exact. This module does not enable behavior conversion or asset creation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import TYPE_CHECKING

from src.core.export_report import AssetDiff, ExportReport, make_export_report
from src.core.objects import BEHAVIOR_NAMES, ObjectDefinition
from src.core.rom import AssetType, RomImage
from src.core.object_models import ObjectLibrary
from src.core.object_dependencies import DefinitionUse
from src.core.textures import load_sprite, load_texture

if TYPE_CHECKING:
    from src.core.editing import EditSession


@dataclass(frozen=True)
class HeaderField:
    key: str
    label: str
    offset: int
    format: str
    minimum: float
    maximum: float
    help: str

    def read(self, raw: bytes) -> int | float:
        return struct.unpack_from('>'+self.format, raw, self.offset)[0]

    def write(self, raw: bytes, value: int | float) -> bytes:
        if (type(value) not in (int, float) or not self.minimum <= value <= self.maximum
                or not math.isfinite(value)
                or self.format != 'f' and type(value) is not int):
            raise ValueError(f'{self.label}: choose {self.minimum:g}..{self.maximum:g}')
        out = bytearray(raw)
        struct.pack_into('>'+self.format, out, self.offset, value)
        return bytes(out)


FIELDS: tuple[HeaderField, ...] = (
    HeaderField('scale', 'Base scale', 0x0C, 'f', .001, 64,
        'Shared starting scale; per-entry size and behavior code can multiply or override it. Editor range 0.001..64.'),
    HeaderField('draw_distance', 'Draw distance', 0x4E, 'h', 0, 32767,
        'Game units. 0 skips this distance cutoff; fade begins at 80%. Four-player rendering halves it. Editor preview does not cull by it.'),
    HeaderField('ambient', 'Ambient lighting', 0x28, 'f', 0, 1,
        'Ambient factor used by shaded 3D models; game lighting can override it. Preview uses neutral lighting.'),
    HeaderField('diffuse', 'Diffuse lighting', 0x2C, 'f', 0, 1.999,
        'Directional diffuse factor, below 2 as in the runtime lighting controls. Preview uses neutral lighting.'),
    HeaderField('light_red', 'Light red', 0x3A, 'B', 0, 255, 'RGB override used when light intensity is nonzero.'),
    HeaderField('light_green', 'Light green', 0x3B, 'B', 0, 255, 'RGB override used when light intensity is nonzero.'),
    HeaderField('light_blue', 'Light blue', 0x3C, 'B', 0, 255, 'RGB override used when light intensity is nonzero.'),
    HeaderField('light_intensity', 'Light intensity', 0x3D, 'B', 0, 255, '0 retains normal game light initialization; nonzero enables this RGB/intensity override.'),
    HeaderField('light_angle_y', 'Light angle Y (raw)', 0x3E, 'h', -32768, 32767, 'Signed binary angle; 65536 units per revolution.'),
    HeaderField('light_angle_z', 'Light angle Z (raw)', 0x40, 'h', -32768, 32767, 'Signed binary angle; 65536 units per revolution.'),
    HeaderField('directional', 'Directional point lighting', 0x71, 'B', 0, 1,
        'Requires a shaded 3D behavior and models with generated normals. Changes the game point-light rendering mode.'),
    HeaderField('shadow_scale', 'Shadow scale', 0x04, 'f', 0, 64, 'Scale for existing shadow allocation/group. 0 suppresses its projected area; does not create a shadow system.'),
    HeaderField('shadow_bottom', 'Shadow bottom offset', 0x46, 'h', -32768, 32767, 'Lower projection bound relative to object Y.'),
    HeaderField('shadow_top', 'Shadow top offset', 0x48, 'h', -32768, 32767, 'Upper projection bound relative to object Y.'),
    HeaderField('shadow_outer', 'Shadow cutoff distance', 0x4A, 'h', 0, 32767, 'Outside this distance the single-player shadow is omitted (source name shadowFadeMin).'),
    HeaderField('shadow_inner', 'Shadow fade-start distance', 0x4C, 'h', 0, 32767, 'Fade starts here if below cutoff; otherwise the shadow has a hard cutoff (source name shadowFadeMax).'),
    HeaderField('water_scale', 'Water-effect scale', 0x08, 'f', 0, 64, 'Scale for an existing behavior water effect; no new group, emitter or allocation is enabled.'),
)
FIELD_BY_KEY = {field.key: field for field in FIELDS}
MODEL_TYPES = ('3D model', 'Billboard sprite', 'Vehicle-part sprite', 'Unknown type 3', 'Texture / special')
# Exact SHADED cases in obj_init_property_flags; attachment-only headers can
# bypass that initializer, so point-light enabling also excludes those below.
SHADED = frozenset(BEHAVIOR_NAMES.index('BHV_'+name) for name in (
    'RACER', 'SCENERY', 'DINO_WHALE', 'HIT_TESTER', 'HIT_TESTER_2', 'SNOWBALL',
    'SNOWBALL_2', 'STOPWATCH_MAN', 'BRIDGE_WHALE_RAMP', 'SEA_MONSTER', 'UNK_30',
    'UNK_3F', 'ANIMATED_OBJECT', 'VEHICLE_ANIMATION', 'PARK_WARDEN_2', 'WIZPIG_SHIP',
    'ANIMATED_OBJECT_4', 'PIG_ROCKETEER', 'CHARACTER_SELECT', 'TROPHY_CABINET',
    'DYNAMIC_LIGHT_OBJECT_2', 'ROCKET_SIGNPOST', 'ROCKET_SIGNPOST_2', 'UNK_5B',
    'PARK_WARDEN', 'FROG', 'UNK_72'))


class ObjectResources:
    """Lazy validation of existing artwork; never changes resource assets."""
    def __init__(self, source: RomImage) -> None:
        self.source = source
        self.library = ObjectLibrary(source)
        self._signatures: dict[tuple[int, int], tuple[int, ...]] = {}
        self.attachment_headers: set[bytes] = set()
        for i in range(source.count(AssetType.OBJECTS)):
            raw = RomImage.read_asset(source, AssetType.OBJECTS, i)
            start = struct.unpack_from('>I', raw, 0x14)[0]
            for offset in range(raw[0x56]):
                if start < 0x78 or start+(offset+1)*4 > len(raw):
                    raise ValueError('Protected attachment array exceeds its header')
                target = struct.unpack_from('>i', raw, start+offset*4)[0]
                if 0 <= target < source.count(AssetType.OBJECTS):
                    self.attachment_headers.add(RomImage.read_asset(source, AssetType.OBJECTS, target))

    def signature(self, kind: int, index: int) -> tuple[int, ...]:
        key = kind, index
        if key in self._signatures:
            return self._signatures[key]
        if kind == 0:
            if not 0 <= index < self.source.count(AssetType.OBJECT_MODELS):
                raise ValueError('3D model ID is outside the object-model table')
            model = self.library.model(index)
            raw = model.raw_data
            attach = struct.unpack_from('>h', raw, 0x18)[0]
            spheres = struct.unpack_from('>h', raw, 0x20)[0]
            for pointer, count, width in ((0x14, attach, 2), (0x1C, spheres, 2)):
                start = struct.unpack_from('>I', raw, pointer)[0]
                if count < 0 or count and (start < 0x58 or start+count*width > len(raw)):
                    raise ValueError('Model attachment/collision array is outside the model')
            if spheres % 2:
                raise ValueError('Model collision-sphere array needs pairs')
            if attach:
                start = struct.unpack_from('>I', raw, 0x14)[0]
                vertices = struct.unpack_from('>'+str(attach)+'h', raw, start)
                if any(v < 0 or v >= len(model.mesh.segments[0].vertices) for v in vertices):
                    raise ValueError('Model attachment vertex is outside its vertex array')
            clips = self.library.clip_count(index)
            for clip in range(clips):
                self.library.clip(index, clip)
            lit = int(model.uses_normals)
            value = clips, attach, spheres, lit, len(raw)
        elif kind in (1, 2):
            if not 0 <= index < self.source.count(AssetType.SPRITES):
                raise ValueError('Sprite ID is outside the sprite table')
            sprite = load_sprite(self.source, index)
            for tile in {tile for frame in range(sprite.frame_count) for tile in sprite.texture_ids(frame)}:
                load_texture(self.source, tile, asset_type=AssetType.TEXTURES_2D)
            value = (sprite.frame_count,)
        elif kind == 4:
            if not 0 <= index <= 0xFFFF:
                raise ValueError('Texture reference needs a 16-bit encoded texture ID')
            texture = load_texture(self.source, index & 0x7FFF,
                asset_type=AssetType.TEXTURES_3D if index & 0x8000 else AssetType.TEXTURES_2D)
            value = (len(texture.frames),)
        else:
            raise ValueError('This model type has no verified artwork writer')
        self._signatures[key] = value
        return value

    def compatible(self, kind: int, before: int, after: int) -> None:
        if before == after:
            return
        old, new = self.signature(kind, before), self.signature(kind, after)
        if kind == 0:
            if old[0] != new[0] or new[1] < old[1] or new[2] < old[2] or new[3] != old[3]:
                raise ValueError('3D replacement must keep animation clip count and lighting layout, '
                    'and retain attachment/collision-sphere capacity')
        elif new[0] < old[0]:
            raise ValueError('Replacement needs at least the original sprite/texture frame count')


def model_array(raw: bytes) -> tuple[int, int]:
    definition = ObjectDefinition.from_bytes(raw, 0)
    return struct.unpack_from('>I', raw, 0x10)[0], len(definition.model_ids)


def edit_definition(raw: bytes, key: str, value: int | float) -> bytes:
    """Write one draft scalar/reference; cross-field checks happen at preview."""
    if key in FIELD_BY_KEY:
        return FIELD_BY_KEY[key].write(raw, value)
    if key.startswith('model_'):
        try:
            slot = int(key[6:])
        except ValueError as error:
            raise ValueError('Invalid artwork slot') from error
        start, count = model_array(raw)
        if type(value) is not int or not 0 <= value <= 0xFFFF or not 0 <= slot < count:
            raise ValueError('Invalid artwork slot or ID')
        out = bytearray(raw)
        struct.pack_into('>I', out, start+slot*4, value)
        return bytes(out)
    raise ValueError('This header field is protected')


def validate_definition(original: bytes, raw: bytes, resources: ObjectResources) -> ObjectDefinition:
    if len(raw) != len(original):
        raise ValueError('Global object definition must keep its exact asset length')
    old = ObjectDefinition.from_bytes(original, 0)
    new = ObjectDefinition.from_bytes(raw, 0)
    writable: set[int] = set()
    for field in FIELDS:
        size = struct.calcsize('>'+field.format)
        writable.update(range(field.offset, field.offset+size))
        if raw[field.offset:field.offset+size] != original[field.offset:field.offset+size]:
            field.write(raw, field.read(raw))
    start, count = model_array(original)
    # Model arrays may not overlap another tail array, even if a corrupt header
    # would otherwise pass its model-offset parser.
    tail = [(struct.unpack_from('>I', original, p)[0], original[n]*stride)
            for p, n, stride in ((0x14, 0x56, 4), (0x18, 0x56, 1), (0x1C, 0x57, 8), (0x24, 0x5A, 24))]
    if count and any(size and max(start, p) < min(start+count*4, p+size) for p, size in tail):
        raise ValueError('Object artwork array overlaps protected data')
    writable.update(range(start, start+count*4))
    if any(a != b and i not in writable for i, (a, b) in enumerate(zip(original, raw))):
        raise ValueError('Behavior, type, flags, counts, pointers, unknown bytes and tail data are protected')
    if any(raw[i:i+2] != original[i:i+2] for i in (0x46, 0x48)) and struct.unpack_from('>h', raw, 0x46)[0] >= struct.unpack_from('>h', raw, 0x48)[0]:
        raise ValueError('Shadow bottom must be below shadow top')
    if raw[0x71] != original[0x71] and raw[0x71]:
        if new.model_type != 0 or new.behavior_id not in SHADED or not new.model_ids or original in resources.attachment_headers:
            raise ValueError('Directional point lighting requires a shaded 3D behavior')
        if any(not resources.signature(0, index)[3] for index in new.model_ids):
            raise ValueError('Directional point lighting requires lit 3D models')
    for before, after in zip(old.model_ids, new.model_ids):
        resources.compatible(old.model_type, before, after)
    return new


def definition_changes(before: bytes, after: bytes) -> tuple[str, ...]:
    fields = tuple(f'{f.label}: {f.read(before):g} → {f.read(after):g}' for f in FIELDS if f.read(before) != f.read(after))
    old, new = ObjectDefinition.from_bytes(before, 0), ObjectDefinition.from_bytes(after, 0)
    return fields+tuple(f'Artwork slot {i}: {a} → {b}' for i, (a, b) in enumerate(zip(old.model_ids, new.model_ids)) if a != b)


def definition_uses(session: EditSession) -> dict[int, DefinitionUse]:
    return session.definition_uses


def global_diff(session: EditSession, index: int, raw: bytes, uses: dict[int, DefinitionUse]) -> AssetDiff:
    original = session.original_asset(AssetType.OBJECTS, index)
    name = session.database.definitions[index].name
    return AssetDiff(34, index, f'Global object {index}: {name}', len(original), len(raw),
        len(original), len(raw), uses[index].levels, definition_changes(original, raw)+(
        f'Known placed instances: {uses[index].instances}; maps: '+', '.join(map(str, uses[index].maps)),
        'Shared definition; compiled spawns, racers and menu/cutscene code may add uses. Header size and array counts unchanged.'))


@dataclass(frozen=True)
class GlobalObjectPlan:
    signature: str
    before: tuple[tuple[int, bytes], ...]
    after: tuple[tuple[int, bytes], ...]
    report: ExportReport


def plan_global_objects(session: EditSession, drafts: dict[int, bytes]) -> GlobalObjectPlan:
    session._require_idle()
    updates: dict[int, bytes] = {}
    for index, raw in drafts.items():
        if type(index) is not int or not 0 <= index < session.rom.count(AssetType.OBJECTS) or type(raw) is not bytes:
            raise ValueError('Invalid shared object definition')
        session._validate_asset((AssetType.OBJECTS, index), raw)
        if session.current_asset(AssetType.OBJECTS, index) != raw:
            updates[index] = raw
    signature = session._signature()
    sections, old_report = session._prepare_export()
    previous_layout_errors = make_export_report(session.rom, sections, old_report.assets).errors
    sections = list(sections)
    current = {i: raw for (section, i), raw in session._assets.items() if section == AssetType.OBJECTS}
    current.update(updates)
    current = {i: raw for i, raw in current.items() if raw != session.original_asset(AssetType.OBJECTS, i)}
    uses = definition_uses(session)
    data = bytearray(sections[34])
    for index, raw in updates.items():
        span = session.rom.index_table(AssetType.OBJECTS).span(index)
        data[span.start:span.end] = raw
    sections[34] = bytes(data)
    report = make_export_report(session.rom, tuple(sections),
        tuple(d for d in old_report.assets if d.section != 34)+tuple(global_diff(session, i, raw, uses) for i, raw in sorted(current.items())))
    report = report.retain_validation_errors(old_report, previous_layout_errors)
    if not report.can_export:
        raise ValueError('; '.join(report.errors))
    return GlobalObjectPlan(signature,
        tuple((i, session.current_asset(AssetType.OBJECTS, i)) for i in sorted(updates)),
        tuple(sorted(updates.items())), report)
