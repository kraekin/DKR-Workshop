"""Data-backed object dependencies shared by model, header and image reports.

Follow placed entries, animation targets, attached headers and level skyboxes.
Compiled gameplay/menu spawns remain outside this metadata-only graph.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from src.core.level_header import load_level_catalog
from src.core.objects import ObjectDatabase, load_object_map
from src.core.rom import AssetType, DecompAssets, RomImage


@dataclass(frozen=True)
class DefinitionUse:
    aliases: tuple[int, ...]
    maps: tuple[int, ...]
    levels: tuple[str, ...]
    instances: int
    parents: tuple[int, ...]


def definition_dependencies(source: RomImage | DecompAssets, database: ObjectDatabase) -> dict[int, DefinitionUse]:
    """Known placed, actor-target and attachment dependencies; not compiled spawns."""
    catalog = load_level_catalog(source)
    definitions = database.definitions
    maps: dict[int, set[int]] = {d.header_id: set() for d in definitions}
    instances = {d.header_id: 0 for d in definitions}
    parents: dict[int, set[int]] = {d.header_id: set() for d in definitions}
    for d in definitions:
        raw = d.raw_data
        if raw is None:
            continue
        count, start = raw[0x56], struct.unpack_from('>I', raw, 0x14)[0]
        if count and (start < 0x78 or start+count*4 > len(raw)):
            raise ValueError('Protected attachment header array is invalid')
        for (target,) in struct.iter_unpack('>i', raw[start:start+count*4]):
            if target in parents:
                parents[target].add(d.header_id)
    for map_id in range(source.count(AssetType.LEVEL_OBJECT_MAPS)):
        for obj in load_object_map(source, map_id, database).objects:
            maps[obj.definition.header_id].add(map_id)
            instances[obj.definition.header_id] += 1
            if obj.definition.behavior_id == 49:
                target = obj.value('objectIdToSpawn', -1)
                if type(target) is int and 0 <= target < len(database.translation):
                    header = database.translation[target]
                    if header in maps:
                        maps[header].add(map_id)
    changed = True
    while changed:
        changed = False
        for child, owners in parents.items():
            before = len(maps[child])
            for owner in owners:
                maps[child].update(maps[owner])
            changed |= len(maps[child]) != before
    levels = {d.header_id: set() for d in definitions}
    for level in catalog.levels:
        header = level.header
        name = f'{level.index}: {level.name}'
        for index in levels:
            if maps[index].intersection((header.object_map_id, header.secondary_object_map_id)):
                levels[index].add(name)
        if header.skybox_id in levels:
            levels[header.skybox_id].add(name)
    changed = True
    while changed:
        changed = False
        for child, owners in parents.items():
            before = len(levels[child])
            for owner in owners:
                levels[child].update(levels[owner])
            changed |= len(levels[child]) != before
    return {d.header_id: DefinitionUse(
        tuple(i for i, target in enumerate(database.translation) if target == d.header_id),
        tuple(sorted(maps[d.header_id])),
        tuple(sorted(levels[d.header_id], key=lambda text: int(text.split(':', 1)[0]))),
        instances[d.header_id], tuple(sorted(parents[d.header_id]))) for d in definitions}
