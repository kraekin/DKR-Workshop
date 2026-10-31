"""Isolated single-decoration allocation diagnostic.

No editor integration, project loading, arbitrary templates or repeat additions.
Sources: object_functions.c:113-183; objects.c:spawn_object, load_object_header,
init_object_shadow, process_object_interactions; textures_sprites.c:load_texture,
tex_load_sprite; tracks.c:shadow_update; include/structs.h. See BUSH_EXPERIMENT.md.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import glob
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from typing import Any, Sequence

from src.core.compression import audit_inplace_rare
from src.core.editing import EditSession, compress_object_map, n64_checksums
from src.core.level_model import load_level_model
from src.core.placement import TerrainSurface
from src.core.rom import AssetType, LUT_END, LUT_START, REV1_SHA1, RomImage, parse_asset_lut
from src.core.runtime_audit import MAX_CAPTURE_BYTES, RuntimeSnapshot, read_runtime_capture
from src.core.structure import StructuralDraft, StructureError, raw_map, simple_instance_bytes

MAP_ID = 5
LEVEL_ID = 5
ENTRY_INDEX = 4
HEADER_ID = 43
SPRITE_ID = 108
SHADOW_TEXTURE_ID = 9  # ObjectHeader.unk34, 2D texture: high bit is clear.
OBJECT_BLOCK_BYTES = 208
INTERACTION_SLOTS = 257  # objects.c:process_object_interactions stack array.
PROFILE = 'ancient-lake-one-bush-v1'


@dataclass(frozen=True)
class BushExperiment:
    """Checked in-memory output from an isolated allocation diagnostic."""

    rom_bytes: bytes
    report_json: str

    def to_text(self) -> str:
        report = json.loads(self.report_json)
        baseline = report['baseline']
        change = report['change']
        return '\n'.join((
            'SINGLE-DECORATION ALLOCATION DIAGNOSTIC',
            'Stock USA Rev1 only; this diagnostic runs independently of project edits.',
            f"Ancient Lake, map5: {change['before_entries']} -> {change['after_entries']} entries.",
            f"Clone entry4 ({change['source_position']}) -> appended entry98 ({change['clone_position']}).",
            'Parameters/solidity retained; nearby terrain height obtained from the ROM mesh.',
            'Expected resident-resource delta: +208 B object pool, +1 list/interaction entry,',
            '+1 header43 / sprite108 / 2D texture9 reference; at most +1 pool descriptor.',
            'No new shared asset loads if the baseline resident-assets premise holds.',
            f"Baseline: {baseline['samples']} distinct capture(s), list peak {baseline['list_peak']}/512; "
            f"minimum object-pool free {baseline['pool_free_min']:,} B.",
            f"Map decoded {change['decoded_before']} -> {change['decoded_after']} B; "
            f"staging {change['staging_required']}/12288 B; inflater check passed.",
            'Original ROM length retained; rebuilt-map reload, other assets and CRC verified.',
            f"Expected output SHA256: {report['output_sha256']}",
            'Captured headroom is not a guaranteed reserve. Shadow geometry, transient sound,',
            'future interactive-object peaks and performance still need user gameplay checks.',
            'Start the exported ROM fresh; do not restore a state containing the old map.',
        ))


def _references(snapshot: RuntimeSnapshot, kind: str, asset_id: int) -> int:
    assets = snapshot.sprites if kind == 'sprite' else snapshot.textures
    return next((asset.references for asset in assets if asset.asset_id == asset_id), 0)


def _baseline_report(samples: tuple[RuntimeSnapshot, ...]) -> dict[str, Any]:
    if not samples or len(samples) > 64:
        raise StructureError('Supply 1-64 distinct baseline runtime captures')
    if len({sample.digest for sample in samples}) != len(samples):
        raise StructureError('Baseline captures contain duplicate RDRAM content')
    for sample in samples:
        if sorted(sample.map_ids) != [5, 73]:
            raise StructureError('Each baseline must have Ancient Lake map roles5/73')
        if (len(sample.header_references) != 304 or sample.header_references[HEADER_ID] != 2
                or _references(sample, 'sprite', SPRITE_ID) != 2):
            raise StructureError('Baseline must have the two resident stock bush header/sprite references')
        shadow = _references(sample, 'texture', SHADOW_TEXTURE_ID)
        if not 1 <= shadow < 255:
            raise StructureError('Resident 2D shadow texture9 has no spare unsigned-byte reference')
        if sample.object_count + 1 > min(512, INTERACTION_SLOTS):
            # Total list is an upper bound on the smaller nonparticle interactive subset.
            raise StructureError('Captured total list leaves no conservative interaction-list headroom')
        pool = sample.pools[1]
        if (pool.data_bytes != 0x15800 or pool.free_bytes < OBJECT_BLOCK_BYTES
                or pool.largest_free < OBJECT_BLOCK_BYTES or pool.split_allocations_remaining < 1):
            raise StructureError('Captured object pool cannot accommodate the one-bush allocation/split')
    return {
        'samples': len(samples),
        'rdram_sha256': [sample.digest for sample in samples],
        'source_sha256': [sample.source_digest or sample.digest for sample in samples],
        'list_peak': max(sample.object_count for sample in samples),
        'pool_free_min': min(sample.pools[1].free_bytes for sample in samples),
        'largest_block_min': min(sample.pools[1].largest_free for sample in samples),
        'descriptors_peak': max(sample.pools[1].descriptors for sample in samples),
        'shadow_texture_reference_range': [min(_references(s, 'texture', 9) for s in samples),
                                           max(_references(s, 'texture', 9) for s in samples)],
        'header43_references': 2, 'sprite108_references': 2,
        'conditions': 'Observed captures only; matching asset edits/mode/player count and future peaks are unverified',
    }


def prepare_experiment(rom: RomImage, samples: tuple[RuntimeSnapshot, ...]) -> BushExperiment:
    """Build exactly one clone from the original ROM, fully validate in memory."""
    session = EditSession(rom)  # Pins original Rev1 identity; edited ROMs cannot compound clones.
    baseline = _baseline_report(samples)
    source = session.current_map(MAP_ID)
    template = source.objects[ENTRY_INDEX]
    header = template.definition
    data = header.raw_data
    if (header.header_id != HEADER_ID or header.behavior_id != 2 or header.model_type != 1
            or header.model_ids != (SPRITE_ID,) or data is None or len(data) < 0x78
            or any(data[i] for i in (0x56, 0x57, 0x5A, 0x5B))
            or struct.unpack_from('>2h', data, 0x32) != (1, SHADOW_TEXTURE_ID)
            or template.byte_size != 12 or template.value('solid') != 1
            or simple_instance_bytes(template) != OBJECT_BLOCK_BYTES):
        raise StructureError('Stock bush template does not match the source-audited profile')
    contexts = tuple(level for level in session._catalog.levels if MAP_ID in (
        level.header.object_map_id, level.header.secondary_object_map_id))
    if len(contexts) != 1 or contexts[0].index != LEVEL_ID:
        raise StructureError('Unexpected shared-map contexts; only Ancient Lake is in this profile')
    level = contexts[0]
    if sorted((level.header.object_map_id, level.header.secondary_object_map_id)) != [5, 73]:
        raise StructureError('Unexpected Ancient Lake map pair')

    # Fixed small experiment: +128 Z, same X, with the mesh's local terrain Y.
    surface = TerrainSurface.from_model(load_level_model(rom, level.header.geometry_id))
    x, y, z = template.position
    position = (x, y, z + 128)
    height = surface.surface_y(position, drop=False)
    if height is None or surface.surface_y(template.position, drop=False) != y:
        raise StructureError('The diagnostic has no verified local ground placement')
    position = (x, height, z + 128)
    draft = StructuralDraft(session, MAP_ID)
    before = draft.serialize()
    draft.append(draft.source_ids[ENTRY_INDEX], position)
    after = draft.serialize()  # Includes shared contexts, staging and source-model inflate checks.
    # Undo/redo is an exact restoration, not a new change to the normal session.
    draft.undo()
    if draft.serialize() != before:
        raise StructureError('Diagnostic undo did not restore the original map')
    draft.redo()
    if draft.serialize() != after or session.dirty or session.can_undo:
        raise StructureError('Diagnostic draft changed its source session or history')
    output = draft.experimental_rom_bytes()
    verify_experiment(rom, output, after)
    packed = compress_object_map(after)
    audit_inplace_rare(packed)
    report = {
        'format': 'dkr-one-bush-research', 'version': 1, 'profile': PROFILE,
        'gameplay_verified': False, 'production_structural_permissions': False,
        'base_rom_sha1': REV1_SHA1,
        'output_sha256': hashlib.sha256(output).hexdigest(), 'rom_bytes': len(output),
        'baseline': baseline,
        'change': {
            'level_id': LEVEL_ID, 'map_id': MAP_ID, 'source_entry': ENTRY_INDEX,
            'appended_entry': len(source.objects), 'header_id': HEADER_ID, 'sprite_id': SPRITE_ID,
            'shadow_texture_id': SHADOW_TEXTURE_ID, 'shadow_texture_section': 'TEXTURES_2D',
            'source_position': list(template.position), 'clone_position': list(position),
            'before_entries': len(source.objects), 'after_entries': len(source.objects) + 1,
            'decoded_before': len(before), 'decoded_after': len(after),
            'staging_required': len(after) + 32, 'compressed_bytes': len(packed),
            'map_before_sha256': hashlib.sha256(before).hexdigest(),
            'map_after_sha256': hashlib.sha256(after).hexdigest(),
            'inflater': 'source-model check passed',
            'object_pool_bytes_added': OBJECT_BLOCK_BYTES, 'object_list_slots_added': 1,
            'interaction_entries_added': 1, 'descriptor_splits_added_at_most': 1,
            'header_references_added': 1, 'sprite_references_added': 1,
            'shadow_texture_references_added': 1,
            'expected_loaded_header43_references': 3, 'expected_loaded_sprite108_references': 3,
            'new_cached_assets_with_resident_premise': 0,
            'affected_header_levels': [level.name],
        },
        'remaining_checks': [
            'Fresh single-player Ancient Lake load; visible new bush, collision/bending/sound and shadow',
            'Weapons/particles, restart and exit/re-enter; measure new captures rather than assuming equal activity',
            'Expected resident header43/sprite108 references become3; texture9 gains1 under equal other usage',
            '257 interaction-list and fixed shadow-geometry usage are not bounded over all future gameplay',
            'This measurement does not establish a multiplayer or global object limit',
        ],
    }
    return BushExperiment(output, json.dumps(report, indent=2) + '\n')


def verify_experiment(rom: RomImage, output: bytes, expected_map: bytes) -> None:
    """Independently reload the only changed map and compare all other assets."""
    if len(output) != len(rom.data) or struct.unpack_from('>2I', output, 16) != n64_checksums(output):
        raise StructureError('Diagnostic ROM length or N64 checksum failed')
    rebuilt = RomImage(output, 'z64', parse_asset_lut(output, LUT_START, LUT_END))
    session = EditSession(rom)
    from src.core.objects import load_object_map
    parsed = load_object_map(rebuilt, MAP_ID, session.database)
    original = session.current_map(MAP_ID)
    if (raw_map(parsed) != expected_map or len(parsed.objects) != len(original.objects) + 1
            or tuple(o.raw_data for o in parsed.objects[:-1]) != tuple(o.raw_data for o in original.objects)
            or parsed.header[4:] != original.header[4:]):
        raise StructureError('Diagnostic map changed existing entries or failed reload')
    clone, template = parsed.objects[-1], original.objects[ENTRY_INDEX]
    if clone.raw_data[:2] != template.raw_data[:2] or clone.raw_data[8:] != template.raw_data[8:]:
        raise StructureError('Clone ID/size/flags/parameters differ from the stock template')
    for index, (old, new) in enumerate(zip(rom.sections, rebuilt.sections)):
        if index not in (AssetType.LEVEL_OBJECT_MAPS_TABLE, AssetType.LEVEL_OBJECT_MAPS):
            if rom.data[old.start:old.end] != output[new.start:new.end]:
                raise StructureError(f'Untouched asset section{index} changed')
    for map_id in range(rom.count(AssetType.LEVEL_OBJECT_MAPS)):
        if map_id != MAP_ID and rom.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id) != rebuilt.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id):
            raise StructureError(f'Untouched object map{map_id} changed')
    # Outside asset offsets, executable/bootstrap bytes must remain identical.
    if output[:16] != rom.data[:16] or output[24:LUT_START] != rom.data[24:LUT_START]:
        raise StructureError('Diagnostic export altered executable/bootstrap bytes')


def publish_experiment(experiment: BushExperiment, destination: Path) -> tuple[Path, Path]:
    """User-invoked, no-overwrite publication; stage and roll back partial publication."""
    destination = destination.absolute()
    if destination.suffix.lower() != '.z64' or not destination.parent.is_dir():
        raise StructureError('Choose a .z64 path in an existing directory')
    manifest = destination.with_suffix('.z64.research.json')
    if os.path.lexists(destination) or os.path.lexists(manifest):
        raise StructureError('Output ROM/report already exists; choose a new filename')
    published: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix='.dkr-one-bush-', dir=destination.parent) as temp:
            staged_rom, staged_report = Path(temp)/'output.z64', Path(temp)/'report.json'
            staged_rom.write_bytes(experiment.rom_bytes)
            staged_report.write_text(experiment.report_json, encoding='utf-8')
            # Hard-link publication is atomic and refuses existing paths on Windows/POSIX.
            # Report first, ROM last; a failed second link removes only our own new report.
            for staged, target in ((staged_report, manifest), (staged_rom, destination)):
                os.link(staged, target)
                published.append(target)
    except OSError:
        for path in reversed(published):
            path.unlink()
        raise
    return destination, manifest


def _capture_paths(patterns: Sequence[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if not matches:
            raise StructureError(f'No baseline captures match: {pattern}')
        for match in matches:
            path = Path(match).resolve()
            if path not in paths:
                paths.append(path)
    if len(paths) > 64:
        raise StructureError('Supply at most64 baseline captures')
    return tuple(paths)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True, help='Original USA Rev1 ROM; projects/edited ROMs are refused')
    parser.add_argument('--baseline', nargs='+', required=True, help='Read-only baseline capture paths or quoted wildcard patterns')
    parser.add_argument('--export', type=Path, help='Export the one-bush allocation diagnostic and JSON report; never overwrite')
    args = parser.parse_args(argv)
    try:
        rom = RomImage.from_file(args.rom)
        paths = _capture_paths(args.baseline)
        samples: list[RuntimeSnapshot] = []
        for path in paths:
            if path.stat().st_size > MAX_CAPTURE_BYTES:
                raise StructureError(f'Baseline capture exceeds32 MiB: {path}')
            samples.append(read_runtime_capture(path.read_bytes(), rom, rom.count(AssetType.OBJECTS)))
        experiment = prepare_experiment(rom, tuple(samples))
        print(experiment.to_text())
        if args.export is None:
            print('\nPreview only: no ROM or report written. Use --export PATH to write the diagnostic.')
        else:
            output, manifest = publish_experiment(experiment, args.export)
            print(f'\nExported: {output}\nAllocation report: {manifest}')
        return 0
    except (OSError, ValueError) as error:
        print(f'One-bush diagnostic refused: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
