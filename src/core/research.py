"""Parameter descriptions and compatible project-note annotations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from src.core.objects import LevelObject

if TYPE_CHECKING:
    from src.core.editing import EditSession

from src.core.parameter_labels import (ParameterInfo, CHECKPOINT_PARAMETERS, CHECKPOINT_BEHAVIORS, CHECKPOINT_CUES, parameter_info)


RESULTS = ("Untested", "Observed change", "No visible change", "Inconclusive")


@dataclass(frozen=True)
class FieldNote:
    text: str = ""
    result: str = "Untested"


@dataclass(frozen=True)
class ResearchField:
    key: str
    label: str
    offset: int
    size: int
    status: str
    description: str


def research_fields(obj: LevelObject) -> tuple[ResearchField, ...]:
    fields = [ResearchField(f"position:{axis}", f"Position {axis}", 2 + i * 2, 2, "Known",
                            "Big-endian signed16 world coordinate.") for i, axis in enumerate("XYZ")]
    for parameter in obj.parameters:
        info = parameter_info(obj.definition.behavior_id, parameter.name)
        status, description = "Unknown", "Serialized field; no semantic claim is assigned here. The purpose of this field has not been established."
        if info is not None:
            status = "Apparently unused" if info.label.startswith('Unused byte') else "Known"
            description = info.description
            if obj.definition.behavior_id == 13 and parameter.name in ("unk13", "unk14", "unk15", "unk16") and parameter.value == 3:
                status = "Unknown value"
        elif obj.definition.behavior_id == 16:
            descriptions = {"nodeID": "Global loaded-node ID 0..127; 255 requests runtime assignment. Duplicate IDs compete for the same table slot.",
                            "adjacent": "Four directed global node IDs. 255 means no connection; dangling targets are cleared by the game. Reciprocal links are separate stored bytes.",
                            "elevation": "Only the low two bits are used to select an elevation group in ainode_update. Remaining bits have no meaning established here."}
            if parameter.name in descriptions:
                status, description = "Known", descriptions[parameter.name]
        elif obj.definition.behavior_id == 17 and parameter.name == "unk8":
            status, description = "Apparently unused", "WeaponBalloon initialization does not read this byte in the inspected Revision 1 code. Original intent remains unknown."
        size = {"b":1,"B":1,"h":2,"H":2,"i":4,"I":4,"f":4}[parameter.format] * (len(parameter.value) if isinstance(parameter.value, tuple) else 1)
        fields.append(ResearchField(parameter.name, info.label if info else parameter.name, parameter.offset, size, status, description))
    # Keep individual unknown/padding bytes addressable independently of schemas.
    fields.extend(ResearchField(f"byte:{i}", f"Raw byte 0x{i:02X}", i, 1, "Raw",
                                "One unsigned byte. Notes do not change it; the existing raw editor accepts decimal/hex/binary and individual bits.")
                  for i in range(8, obj.byte_size))
    return tuple(fields)


def compare_sessions(current: EditSession, saved: EditSession) -> tuple[tuple[str, str, str, str], ...]:
    """Read-only saved/current comparison, including unclassified bytes and notes."""
    rows: list[tuple[str, str, str, str]] = []
    for map_id in sorted(set(current.modified_maps) | set(saved.modified_maps) | set(current._structures) | set(saved._structures)):
        before = {obj.index: obj for obj in saved.current_map(map_id).objects}
        after = {obj.index: obj for obj in current.current_map(map_id).objects}
        for identity in sorted(set(before) | set(after)):
            a, b = before.get(identity), after.get(identity)
            if a is None or b is None:
                obj = b if b is not None else a
                rows.append((f'Map {map_id} / entry {identity} · {obj.definition.name}',
                    'Object', 'Absent' if a is None else str(a.position), 'Absent' if b is None else str(b.position)))
                continue
            if a.raw_data == b.raw_data:
                continue
            location = f"Map {map_id} / entry {b.index} · {b.definition.name}"
            if a.position != b.position:
                rows.append((location, "XYZ", str(a.position), str(b.position)))
            for old, new in zip(a.parameters, b.parameters):
                if old.value != new.value:
                    rows.append((location, f"0x{new.offset:02X} {new.name}", str(old.value), str(new.value)))
            for offset, (old, new) in enumerate(zip(a.raw_data or b"", b.raw_data or b"")):
                if old != new:
                    rows.append((location, f"Raw byte 0x{offset:02X}", f"0x{old:02X}", f"0x{new:02X}"))
    for key in sorted(set(current._assets) | set(saved._assets)):
        old, new = saved.current_asset(*key), current.current_asset(*key)
        for offset, (a, b) in enumerate(zip(old, new)):
            if a != b:
                rows.append((f"{key[0].name} {key[1]}", f"Byte 0x{offset:02X}", f"0x{a:02X}", f"0x{b:02X}"))
    if current.experiment_name != saved.experiment_name:
        rows.append(("Project notes", "Label", saved.experiment_name, current.experiment_name))
    for map_id, index, field in sorted(set(current._notes) | set(saved._notes)):
        old, new = saved.note((map_id, index), field), current.note((map_id, index), field)
        if old != new:
            rows.append((f"Map {map_id} / entry {index}", f"Note · {field}", f"{old.result}: {old.text}", f"{new.result}: {new.text}"))
    return tuple(rows)
