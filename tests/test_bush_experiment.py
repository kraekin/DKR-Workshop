"""Restricted export; no persistent review ROMs or emulator execution."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import pytest

from src.core import bush_experiment as bush
from src.core.editing import EditSession, n64_checksums
from src.core.objects import load_object_map
from src.core.rom import AssetType, LUT_END, LUT_START, REV1_SHA1, RomImage, parse_asset_lut
from src.core.runtime_audit import CachedAsset, PoolUsage, RuntimeSnapshot
from src.core.structure import PRODUCTION_STRUCTURAL_TYPES, StructuralDraft, StructureError, raw_map

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rom() -> RomImage:
    for path in ROOT.glob('*.z64'):
        candidate = RomImage.from_file(path)
        if hashlib.sha1(candidate.data).hexdigest() == REV1_SHA1:
            return candidate
    pytest.skip('Original local USA Rev1 ROM unavailable')


@pytest.fixture
def baseline() -> RuntimeSnapshot:
    """Synthetic observations for guard tests; not collected gameplay evidence."""
    references = tuple(2 if i == 43 else 0 for i in range(304))
    return RuntimeSnapshot('1'*64, 'Big-endian', 192, (5, 73), (
        PoolUsage('Main pool', 2926928, 363136, 329584, 955, 1600, (329584, 33552)),
        PoolUsage('Object pool', 88064, 33696, 31632, 228, 512, (31632, 2064))),
        references, (CachedAsset(108, 2),), (CachedAsset(9, 101),), 40, 396,
        tuple((name, 0, limit) for name, limit in zip(
            ('Triangle', 'Rectangle', 'Sprite', 'Line', 'Point'), (8, 16, 150, 100, 50))),
        source_digest='2'*64)


@pytest.fixture(scope='module')
def prepared(rom: RomImage) -> bush.BushExperiment:
    references = tuple(2 if i == 43 else 0 for i in range(304))
    sample = RuntimeSnapshot('a'*64, 'Big-endian', 180, (5, 73), (
        PoolUsage('Main', 2926928, 363136, 329584, 955, 1600, (329584, 33552)),
        PoolUsage('Object', 88064, 33696, 31632, 228, 512, (31632, 2064))),
        references, (CachedAsset(108, 2),), (CachedAsset(9, 84),), 40, 396, ())
    return bush.prepare_experiment(rom, (sample,))


def test_rebuild_is_exactly_one_source_bush_with_checked_local_ground(
        rom: RomImage, prepared: bush.BushExperiment) -> None:
    output = prepared.rom_bytes
    rebuilt = RomImage(output, 'z64', parse_asset_lut(output, LUT_START, LUT_END))
    session = EditSession(rom)
    original = session.current_map(5)
    changed = load_object_map(rebuilt, 5, session.database)
    assert len(changed.objects) == 99 and len(original.objects) == 98
    assert [o.raw_data for o in changed.objects[:-1]] == [o.raw_data for o in original.objects]
    assert changed.objects[-1].position == (-1074, 59, -7134)
    assert changed.objects[-1].raw_data[8:] == original.objects[4].raw_data[8:]
    assert changed.objects[-1].raw_data[:2] == original.objects[4].raw_data[:2]
    assert len(raw_map(changed)) == 2384 and len(raw_map(original)) == 2368
    assert changed.header[4:] == original.header[4:]
    assert len(output) == len(rom.data)
    assert struct.unpack_from('>2I', output, 16) == n64_checksums(output)
    for map_id in range(rom.count(AssetType.LEVEL_OBJECT_MAPS)):
        if map_id != 5:
            assert rom.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id) == rebuilt.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id)
    for index, (old, new) in enumerate(zip(rom.sections, rebuilt.sections)):
        if index not in (20, 21):
            assert rom.data[old.start:old.end] == output[new.start:new.end]
    assert hashlib.sha1(rom.data).hexdigest() == REV1_SHA1
    assert not session.dirty and not PRODUCTION_STRUCTURAL_TYPES


def test_report_distinguishes_exact_delta_observations_and_unverified_gameplay(prepared: bush.BushExperiment) -> None:
    report = json.loads(prepared.report_json)
    assert report['profile'] == bush.PROFILE
    assert report['gameplay_verified'] is report['production_structural_permissions'] is False
    assert report['output_sha256'] == hashlib.sha256(prepared.rom_bytes).hexdigest()
    change = report['change']
    assert change['object_pool_bytes_added'] == 208
    assert change['shadow_texture_section'] == 'TEXTURES_2D'
    assert change['shadow_texture_references_added'] == 1
    assert change['affected_header_levels'] == ['Ancient Lake']
    assert change['staging_required'] == 2416
    assert 'gameplay checks' in prepared.to_text()
    assert '257' in ' '.join(report['remaining_checks'])


@pytest.mark.parametrize('case', ('empty', 'duplicate', 'maps', 'header', 'sprite', 'shadow_missing',
    'shadow_wrap', 'object_list', 'interaction_list', 'pool_free', 'largest_block', 'descriptors'))
def test_baseline_resource_and_residency_refusals(baseline: RuntimeSnapshot, case: str) -> None:
    samples = (baseline,)
    if case == 'empty': samples = ()
    elif case == 'duplicate': samples = (baseline, baseline)
    elif case == 'maps': samples = (replace(baseline, map_ids=(0, 68)),)
    elif case == 'header': samples = (replace(baseline, header_references=(0,)*304),)
    elif case == 'sprite': samples = (replace(baseline, sprites=()),)
    elif case == 'shadow_missing': samples = (replace(baseline, textures=()),)
    elif case == 'shadow_wrap': samples = (replace(baseline, textures=(CachedAsset(9, 255),)),)
    elif case == 'object_list': samples = (replace(baseline, object_count=512),)
    elif case == 'interaction_list': samples = (replace(baseline, object_count=257),)
    else:
        pool = baseline.pools[1]
        if case == 'pool_free': pool = replace(pool, free_bytes=192)
        elif case == 'largest_block': pool = replace(pool, largest_free=192)
        elif case == 'descriptors': pool = replace(pool, descriptors=511)
        samples = (replace(baseline, pools=(baseline.pools[0], pool)),)
    with pytest.raises(StructureError):
        bush._baseline_report(samples)


def test_baseline_projection_uses_minima_and_maxima_without_inventing_a_limit(baseline: RuntimeSnapshot) -> None:
    other = replace(baseline, digest='3'*64, source_digest='4'*64, map_ids=(73, 5), object_count=180,
        textures=(CachedAsset(9, 84),), pools=(baseline.pools[0], replace(baseline.pools[1], free_bytes=38128)))
    report = bush._baseline_report((baseline, other))
    assert report['samples'] == 2 and report['list_peak'] == 192
    assert report['pool_free_min'] == 33696 and report['shadow_texture_reference_range'] == [84, 101]
    assert 'allowance' not in report and 'safe_objects' not in report


def test_an_edited_rom_cannot_be_used_to_compound_the_experiment(prepared: bush.BushExperiment,
                                                               baseline: RuntimeSnapshot) -> None:
    output = prepared.rom_bytes
    rom = RomImage(output, 'z64', parse_asset_lut(output, LUT_START, LUT_END))
    with pytest.raises(ValueError, match='original USA Rev 1'):
        bush.prepare_experiment(rom, (baseline,))


@pytest.mark.parametrize('mutation', ('checksum', 'executable', 'other_asset', 'existing_entry', 'clone_parameters'))
def test_independent_output_validation_rejects_corruption(rom: RomImage, prepared: bush.BushExperiment,
                                                        mutation: str) -> None:
    raw = bytearray(prepared.rom_bytes)
    expected = load_object_map(RomImage(bytes(raw), 'z64', parse_asset_lut(raw, LUT_START, LUT_END)),
                               5, EditSession(rom).database)
    if mutation == 'checksum': raw[16] ^= 1
    elif mutation == 'executable': raw[0x1000] ^= 1
    elif mutation == 'other_asset':
        span = parse_asset_lut(raw, LUT_START, LUT_END)[AssetType.OBJECTS]
        raw[span.start] ^= 1
    else:
        # Build valid alternate maps/CRCs so only the independent profile checks
        # can reject moving an old entry or copying the other bush's parameters.
        session = EditSession(rom)
        draft = StructuralDraft(session, 5)
        draft.append(draft.source_ids[4 if mutation == 'existing_entry' else 8], (-1074, 59, -7134))
        if mutation == 'existing_entry':
            document = draft.document()
            document['entries'][4]['position'][0] += 1
            draft = StructuralDraft.from_document(session, document)
        with pytest.raises(StructureError):
            bush.verify_experiment(rom, draft.experimental_rom_bytes(), draft.serialize())
        return
    if mutation != 'checksum': struct.pack_into('>2I', raw, 16, *n64_checksums(raw))
    with pytest.raises(StructureError): bush.verify_experiment(rom, bytes(raw), raw_map(expected))


def test_user_invoked_publication_and_existing_path_refusals(prepared: bush.BushExperiment, tmp_path: Path) -> None:
    output, report = bush.publish_experiment(prepared, tmp_path/'one.z64')
    assert output.read_bytes() == prepared.rom_bytes
    assert report.read_text(encoding='utf-8') == prepared.report_json
    for target in (output, tmp_path/'one.dkrproj', tmp_path/'missing'/'one.z64'):
        with pytest.raises(StructureError): bush.publish_experiment(prepared, target)
    (tmp_path/'taken.z64.research.json').write_text('retain')
    with pytest.raises(StructureError): bush.publish_experiment(prepared, tmp_path/'taken.z64')
    assert (tmp_path/'taken.z64.research.json').read_text() == 'retain'


def test_publish_failure_removes_only_new_partial_output(prepared: bush.BushExperiment, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    real_link = bush.os.link
    calls = 0
    def fail_second(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2: raise OSError('injected disk publication failure')
        real_link(source, destination)
    monkeypatch.setattr(bush.os, 'link', fail_second)
    with pytest.raises(OSError): bush.publish_experiment(prepared, tmp_path/'one.z64')
    assert list(tmp_path.iterdir()) == []


def test_concurrent_destination_appearance_is_never_overwritten(prepared: bush.BushExperiment, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    real_link = bush.os.link
    target = tmp_path/'one.z64'
    def raced_link(source: Path, destination: Path) -> None:
        if destination == target: destination.write_bytes(b'other writer')
        real_link(source, destination)
    monkeypatch.setattr(bush.os, 'link', raced_link)
    with pytest.raises(FileExistsError): bush.publish_experiment(prepared, target)
    assert target.read_bytes() == b'other writer'
    assert not target.with_suffix('.z64.research.json').exists()


def test_cli_default_is_preview_and_explicit_export_is_required(rom: RomImage, prepared: bush.BushExperiment,
        baseline: RuntimeSnapshot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    capture = tmp_path/'baseline.bin'
    capture.write_bytes(b'stub capture')
    monkeypatch.setattr(bush.RomImage, 'from_file', lambda _: rom)
    monkeypatch.setattr(bush, 'read_runtime_capture', lambda *_: baseline)
    monkeypatch.setattr(bush, 'prepare_experiment', lambda *_: prepared)
    arguments = ['--rom', 'original.z64', '--baseline', str(tmp_path/'base*.bin')]
    assert bush.main(arguments) == 0
    assert 'Preview only' in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == [capture]
    assert bush.main([*arguments, '--export', str(tmp_path/'one.z64')]) == 0
    assert (tmp_path/'one.z64').exists() and (tmp_path/'one.z64.research.json').exists()
    assert bush.main([*arguments, '--export', str(tmp_path/'one.z64')]) == 2
    assert 'already exists' in capsys.readouterr().err


def test_cli_input_errors_are_refusals_without_output(rom: RomImage, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(bush.RomImage, 'from_file', lambda _: rom)
    assert bush.main(['--rom', 'original.z64', '--baseline', str(tmp_path/'absent*.bin')]) == 2
    assert 'No baseline captures' in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
