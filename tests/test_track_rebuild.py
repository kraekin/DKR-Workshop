"""lossless record compiler, source-model dependencies and ROM isolation."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import struct

import numpy as np
import pytest

from src.core.compression import decompress_rare
from src.core.editing import EditSession, n64_checksums
from src.core.level_model import LevelModel
from src.core.geometry import collision_base_planes
from src.core.rom import RomImage, AssetType, LUT_START, LUT_END, parse_asset_lut
from src.core.track_rebuild import (HEADER, SEGMENT, RebuildError, OpaqueSpan, StockRebuild,
    decode_stock_track, encode_stock_track, rebuild_stock_track, runtime_track,
    stock_rebuild_layout, build_stock_rebuild_rom, export_stock_rebuild_rom)


def example() -> bytes:
    """Two flat adjacent triangles with duplicated batch vertices and known facet links."""
    raw = bytearray(0x160)
    struct.pack_into('>6I', raw, 0, 0x50, 0x58, 0x12C, 0x149, 0x148, 0x149)
    struct.pack_into('>2h', raw, 0x18, 1, 1)
    struct.pack_into('>6h', raw, 0x3C, -200, 200, -200, 200, -200, 200)
    struct.pack_into('>i', raw, 0x48, len(raw))
    struct.pack_into('>IBBBb', raw, 0x50, 42, 32, 32, 0, 1)
    struct.pack_into('>7I', raw, 0x58, 0xF0, 0xD0, 0x12345678, 0xA0, 0xABCDEF, 0x138, 0x987654)
    struct.pack_into('>3h', raw, 0x74, 6, 2, 2)
    raw[0x98] = 2
    for i in range(3):
        struct.pack_into('>BbhhBBI', raw, 0xA0+i*12, 0 if i<2 else 253, -1, i*3, i, 255, 4, 0 if i<2 else 0xDEADBEEF)
    for i in range(2):
        struct.pack_into('>BBBBhhhhhh', raw, 0xD0+16*i, 0x40, 0, 1, 2, -32, 0, 32, -64, -32768, 32767)
    for i, point in enumerate(((0,0,0),(0,0,100),(100,0,0),(100,0,0),(0,0,100),(100,0,100))):
        struct.pack_into('>hhhBBBB', raw, 0xF0+i*10, *point, 1, 1, 123, 45)
    struct.pack_into('>6h', raw, 0x12C, -200, -200, -200, 200, 200, 200)
    struct.pack_into('>8H', raw, 0x138, 0,0,1,0, 1,0,1,1)
    raw[0x148] = 0xAD  # Includes unused high visibility bits that must survive.
    raw[0x149:] = bytes(range(23))
    return bytes(raw)


@pytest.fixture(scope='module')
def rom() -> RomImage:
    for path in Path.cwd().glob('*.z64'):
        try:
            return RomImage.from_file(path)
        except ValueError:
            pass
    pytest.skip('Original local Rev1 ROM unavailable')


@pytest.fixture(scope='module')
def rebuilt(rom: RomImage) -> tuple[StockRebuild, ...]:
    return tuple(rebuild_stock_track(rom.read_asset(AssetType.LEVEL_MODELS, i, decompress=True), model_id=i)
                 for i in range(rom.count(AssetType.LEVEL_MODELS)))


def test_source_struct_sizes_and_record_reconstruction_preserve_every_bit() -> None:
    raw = bytearray(example())
    struct.pack_into('>2I', raw, 0x28, 0x7F800001, 0x80000000)  # signaling-NaN bits and negative zero
    assert struct.calcsize(HEADER) == 0x4C and struct.calcsize(SEGMENT) == 0x44
    document = decode_stock_track(bytes(raw))
    assert encode_stock_track(document) == raw
    assert sum(b.byte_size for b in document.records)+sum(len(s.data) for s in document.opaque) == len(raw)
    vertex = next(b for b in document.records if b.kind == 'vertices')
    assert vertex.rows[0] == (0,0,0,1,1,123,45)
    terminal = next(b for b in document.records if b.kind == 'batches').rows[-1]
    assert terminal == (253,-1,6,2,255,4,0xDEADBEEF)
    assert next(b for b in document.records if b.kind == 'visibility').rows == ((0xAD,),)
    # The document has no full-source passthrough field.
    assert not hasattr(document, 'raw_data')


def test_encoding_uses_record_values_and_refuses_mutation_in_stock_mode() -> None:
    doc = decode_stock_track(example())
    vertex = next(b for b in doc.records if b.kind == 'vertices')
    row = list(vertex.rows[0])
    row[0] = 1
    new = replace(vertex, rows=(tuple(row), *vertex.rows[1:]))
    changed = replace(doc, records=tuple(new if b is vertex else b for b in doc.records))
    with pytest.raises(RebuildError, match='changed protected bytes'):
        encode_stock_track(changed)
    # With the matching hash, the encoded location really reflects the changed row;
    # stock export independently requires exact original ROM bytes.
    expected = bytearray(example())
    struct.pack_into('>h', expected, 0xF0, 1)
    assert encode_stock_track(replace(changed, source_sha256=hashlib.sha256(expected).hexdigest())) == expected


def test_encoder_checks_coverage_overlap_formats_bounds_and_integer_fields() -> None:
    doc = decode_stock_track(example())
    cases = (
        replace(doc, opaque=doc.opaque[1:]),
        replace(doc, opaque=(*doc.opaque, OpaqueSpan(0,b'bad'))),
        replace(doc, records=(replace(doc.records[0],offset=-1),*doc.records[1:])),
        replace(doc, records=(replace(doc.records[0],format='>76B'),*doc.records[1:])),
        replace(doc, records=(replace(doc.records[0],kind='visibility',format='>0B',rows=()),*doc.records[1:])),
        replace(doc, byte_size=0xFFFFFF),
        replace(doc, records=(replace(doc.records[0],rows=((None,),)),*doc.records[1:])),
    )
    for invalid in cases:
        with pytest.raises(ValueError):
            encode_stock_track(invalid)


@pytest.mark.parametrize('offset,value', [(0x10,0),(0x10,0xFFFFFF00),(0x58+0x28,0x7FFF),
    (0x58+0x14,0xFFFFFF00),(0x58+0x14,0xF0)])
def test_invalid_visibility_facet_and_overlapping_regions_are_refused(offset: int,value: int) -> None:
    raw = bytearray(example())
    struct.pack_into('>h' if offset == 0x58+0x28 else '>I', raw, offset, value)
    with pytest.raises(ValueError):
        rebuild_stock_track(bytes(raw))


def test_known_runtime_planes_bisectors_inversion_grid_and_allocation() -> None:
    state = runtime_track(LevelModel.from_bytes(example()))
    segment = state.segments[0]
    assert segment.grid_masks == (0x3838, 0x3838)
    assert state.byte_size == 0x1E0  # align(0x160+4)+7*16, already aligned
    np.testing.assert_array_equal(segment.facets, [[0,2,3,4],[1,0x8003,5,6]])
    np.testing.assert_array_equal(segment.planes[:2], [[0,1,0,0],[0,1,0,0]])
    np.testing.assert_allclose(segment.planes[2], [-1,0,0,0])
    np.testing.assert_allclose(segment.planes[3], [2**-.5,0,2**-.5,-100*2**-.5],rtol=1e-6)
    np.testing.assert_allclose(segment.planes[4], [0,0,-1,0])
    assert not segment.planes.flags.writeable and not segment.facets.flags.writeable
    assert segment.water_batches == () and segment.water_height == -10000


def test_source_degenerate_planes_retain_signed_zeros_without_normalizing() -> None:
    plane = collision_base_planes(np.full((1,3,3), -1, np.float32))
    assert plane.astype('>f4').tobytes() == struct.pack('>4I', *([0x80000000]*4))


def test_cutscene_source_branch_has_base_planes_and_unmodified_facet_links() -> None:
    model = LevelModel.from_bytes(example())
    state = runtime_track(model, cutscene=True)
    assert state.byte_size == 0x190
    assert len(state.segments[0].planes) == 2
    np.testing.assert_array_equal(state.segments[0].facets, [[0,0,1,0],[1,0,1,1]])
    assert state.segments[0].grid_masks == (0x3838,0x3838)


def test_runtime_collision_hidden_inactive_and_water_consumers() -> None:
    raw = bytearray(example())
    struct.pack_into('>I',raw,0xA8,0x100)  # Render-hidden still has collision.
    assert runtime_track(LevelModel.from_bytes(bytes(raw))).sha256 == runtime_track(LevelModel.from_bytes(example())).sha256
    struct.pack_into('>I',raw,0xA8,0x2000)
    segment = runtime_track(LevelModel.from_bytes(bytes(raw))).segments[0]
    assert segment.water_batches == (0,) and segment.water_height == 0
    struct.pack_into('>I',raw,0xA8,0x200)
    no_collision = runtime_track(LevelModel.from_bytes(bytes(raw)))
    assert len(no_collision.segments[0].planes) < 7
    assert no_collision.segments[0].grid_masks == (0x3838,0x3838)
    raw[0xD0] |= 0x80
    struct.pack_into('>4H',raw,0x140,0,0,0,0)
    skipped = runtime_track(LevelModel.from_bytes(bytes(raw))).segments[0]
    assert skipped.grid_masks[0] == 0
    np.testing.assert_array_equal(skipped.planes[0], [0,1,0,0])


@pytest.mark.parametrize('model_id',range(55))
def test_every_stock_model_rebuilds_record_for_record_and_fits_runtime(rom: RomImage,rebuilt,model_id: int) -> None:
    r = rebuilt[model_id]
    original = rom.read_asset(AssetType.LEVEL_MODELS,model_id,decompress=True)
    assert r.model_id == model_id and r.raw == original
    assert r.sha256 == hashlib.sha256(original).hexdigest()
    assert r.record_bytes+r.opaque_bytes == len(original) and r.record_bytes > r.opaque_bytes
    assert r.visibility_rows == r.segments and r.runtime_bytes <= 0x82A00
    assert r.cutscene_bytes <= r.runtime_bytes
    assert decompress_rare(r.packed) == original and 'PASS' in r.to_text()


def test_all_stock_recompressed_rom_preserves_geometry_assets_other_sections_and_crc(rom: RomImage,rebuilt) -> None:
    output,report = build_stock_rebuild_rom(rom,rebuilt)
    assert report.can_export and len(report.assets) == 55 and len(output) == len(rom.data)
    assert report.remaining_bytes >= 0
    new = RomImage(output,'z64',parse_asset_lut(output,LUT_START,LUT_END))
    assert struct.unpack_from('>2I',output,0x10) == n64_checksums(output)
    assert output[:0x10] == rom.data[:0x10] and output[0x18:LUT_START] == rom.data[0x18:LUT_START]
    for section in AssetType:
        if int(section) >= len(rom.sections) or section in (AssetType.LEVEL_MODELS,AssetType.LEVEL_MODELS_TABLE):
            continue
        assert new.section(section) == rom.section(section)
    for i in range(55):
        assert new.read_asset(AssetType.LEVEL_MODELS,i,decompress=True) == rebuilt[i].raw
    old_table = rom.index_table(AssetType.LEVEL_MODELS)
    new_table = new.index_table(AssetType.LEVEL_MODELS)
    assert new.section(AssetType.LEVEL_MODELS)[new_table.offsets[-1]:] == rom.section(AssetType.LEVEL_MODELS)[old_table.offsets[-1]:]
    assert new.section(AssetType.LEVEL_MODELS_TABLE)[len(new_table.offsets)*4:] == rom.section(AssetType.LEVEL_MODELS_TABLE)[len(old_table.offsets)*4:]


def test_selected_stock_export_preserves_unselected_compressed_entries_and_dirty_project(rom: RomImage,rebuilt) -> None:
    session = EditSession(rom)
    session.edit_track_geometry(5,((0,0),),(0,16,0),'User geometry')
    signature,history,raw = session._signature(),session._cursor,session.track_model(5).raw_data
    output,_ = build_stock_rebuild_rom(rom,(rebuilt[5],))
    new = RomImage(output,'z64',parse_asset_lut(output,LUT_START,LUT_END))
    assert new.read_asset(AssetType.LEVEL_MODELS,5,decompress=True) == rebuilt[5].raw
    for i in range(55):
        if i != 5:
            assert new.read_asset(AssetType.LEVEL_MODELS,i) == rom.read_asset(AssetType.LEVEL_MODELS,i)
    assert session._signature() == signature and session._cursor == history
    assert session.track_model(5).raw_data == raw and session.dirty


@pytest.mark.parametrize('kind', ['empty','duplicate','id','raw','hash','packed','alignment'])
def test_stock_export_rejects_unverified_or_modified_inputs(rom: RomImage,rebuilt,kind: str) -> None:
    r = rebuilt[5]
    cases = {
        'empty':(), 'duplicate':(r,r), 'id':(replace(r,model_id=-1),),
        'raw':(replace(r,raw=r.raw[:-1]+bytes([r.raw[-1]^1])),),
        'hash':(replace(r,sha256='0'*64),), 'packed':(replace(r,packed=r.packed[:5]),),
        'alignment':(replace(r,packed=r.packed+b'\0'),),
    }
    with pytest.raises(ValueError):
        stock_rebuild_layout(rom,cases[kind])


def test_stock_export_failures_preserve_destination_and_original(rom: RomImage,rebuilt,tmp_path: Path) -> None:
    destination = tmp_path/'existing.z64'
    destination.write_bytes(b'Unrelated existing user output')
    original_hash = hashlib.sha256(rom.source_path.read_bytes()).digest()
    with pytest.raises(ValueError):
        export_stock_rebuild_rom(rom,(replace(rebuilt[5],sha256='bad'),),destination)
    assert destination.read_bytes() == b'Unrelated existing user output'
    with pytest.raises(ValueError,match='original ROM'):
        export_stock_rebuild_rom(rom,(rebuilt[5],),rom.source_path)
    assert hashlib.sha256(rom.source_path.read_bytes()).digest() == original_hash
    assert list(tmp_path.iterdir()) == [destination]


def test_combined_recompression_budget_refuses_growth_beyond_real_rom_padding(rom: RomImage,rebuilt) -> None:
    padded = tuple(replace(rebuilt[i], packed=rebuilt[i].packed+bytes(200000)) for i in (0,1,5))
    _,report = stock_rebuild_layout(rom,padded)
    assert not report.can_export and report.remaining_bytes < 0
    with pytest.raises(ValueError,match='padding'):
        build_stock_rebuild_rom(rom,padded)
