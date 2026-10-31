"""Headless checks; proprietary data is read from the user's local ROM."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib

import pytest

from src.core.compression import CompressionError, decode_asset, decompress_rare
from src.core.level_header import JP_CHARACTERS, LevelHeader, LevelNames, load_level_catalog
from src.core.rom import (
    AssetError, AssetTable, AssetType, DecompAssets, LUT_END, LUT_START,
    REV1_SHA1, RomImage, normalize_rom, parse_asset_lut,
)

ROOT = Path(__file__).resolve().parents[1]
DECOMP = ROOT / "research/Diddy-Kong-Racing"


@pytest.fixture(scope="session")
def rom() -> RomImage:
    paths = list(ROOT.glob("*.z64"))
    if not paths:
        pytest.skip("Local USA Rev 1 ROM not present")
    return RomImage.from_file(paths[0])


def wrap(payload: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    return struct.pack("<IB", len(payload), 9) + compressor.compress(payload) + compressor.flush()


@pytest.mark.parametrize("order,width", [("z64", 1), ("v64", 2), ("n64", 4)])
def test_rom_normalization_in_memory_preserves_identity(rom: RomImage, order: str, width: int) -> None:
    source = b"".join(rom.data[i:i + width][::-1] for i in range(0, len(rom.data), width)) if width > 1 else rom.data
    original = source
    loaded = RomImage.from_bytes(source)
    assert loaded.byte_order == order
    assert loaded.data == rom.data and source == original
    assert hashlib.sha1(loaded.data).hexdigest() == REV1_SHA1


@pytest.mark.parametrize("data", [b"", b"bad!" * 16, b"\x37\x80\x40\x12" + bytes(61),
                                 b"\x40\x12\x37\x80" + bytes(62)],
                         ids=["short", "unknown-magic", "partial-v64", "partial-n64"])
def test_bad_rom_magic_and_partial_swapped_words_are_rejected(data: bytes) -> None:
    with pytest.raises(AssetError):
        normalize_rom(data)


def test_modified_rom_is_rejected(rom: RomImage) -> None:
    with pytest.raises(AssetError, match="Unsupported or modified ROM"):
        RomImage.from_bytes(rom.data[:-1] + bytes([rom.data[-1] ^ 1]))


def test_master_lut_and_section_ids_match_local_decomp(rom: RomImage) -> None:
    if not DECOMP.is_dir():
        pytest.skip("Local decomp not present")
    config = json.loads((DECOMP / "tools/dkr_assets_tool_extract.json").read_text())
    version = next(item for item in config["inputs-supported"] if item["sha1"] == REV1_SHA1)
    assert version["dkr_version"] == "us.v80" and version["assets"] == LUT_START
    splat = (DECOMP / "ver/splat/dkr.us.v80.yaml").read_text()
    assert "start: 0xED0E0" in splat and "start: 0xED1B0" in splat
    assert len(rom.sections) == 50
    assert rom.sections[0].start == LUT_END
    assert rom.sections[-1].end == version["assets_end"]
    for kind in AssetType:
        assert config["sections"][int(kind)]["build-id"] == f"ASSET_{kind.name}"


@pytest.mark.parametrize("kind,start,end,count", [
    (AssetType.TEXTURES_3D, 0xED2D0, 0x29A270, 1416),
    (AssetType.LEVEL_OBJECT_MAPS, 0x38F980, 0x3AD050, 138),
    (AssetType.LEVEL_HEADERS, 0x3AD160, 0x3B0430, 65),
    (AssetType.LEVEL_NAMES, 0x3B0540, 0x3B1210, 65),
    (AssetType.LEVEL_MODELS, 0x3B1300, 0x55B0A0, 55),
    (AssetType.OBJECTS, 0x6CC110, 0x6D79D0, 304),
])
def test_real_asset_spans_and_terminal_entry(rom: RomImage, kind: AssetType,
                                           start: int, end: int, count: int) -> None:
    assert (rom.sections[kind].start, rom.sections[kind].end) == (start, end)
    assert rom.count(kind) == count
    table = rom.index_table(kind)
    for index in range(count):
        span = table.span(index)
        assert rom.read_asset(kind, index) == rom.data[start + span.start:start + span.end]
    for invalid in (-1, count):
        with pytest.raises(AssetError):
            rom.read_asset(kind, invalid)


@pytest.mark.parametrize("words,data_size", [
    ([0, 8], 8),  # No sentinel.
    ([0, 8, 4, 0xFFFFFFFF], 8),  # Backwards span.
    ([0, 9, 0xFFFFFFFF], 8),  # Past data.
    ([1, 8, 0xFFFFFFFF], 8),  # Wrong base.
    ([0xFFFFFFFF], 0),
])
def test_malformed_subtables_fail_before_slicing(words: list[int], data_size: int) -> None:
    with pytest.raises(AssetError):
        AssetTable.parse(struct.pack(f">{len(words)}I", *words), data_size)


def test_subtable_ignores_alignment_after_sentinel() -> None:
    table = AssetTable.parse(struct.pack(">6I", 0, 3, 8, 0xFFFFFFFF, 0xABCD, 0), 12)
    assert len(table) == 2
    assert table.span(1).size == 5


@pytest.mark.parametrize("count,offsets", [(999, (0, 0, 0)), (2, (0, 9, 8)),
                                          (2, (0, 4, 17)), (2, (1, 4, 8))])
def test_malformed_master_tables_are_rejected(count: int, offsets: tuple[int, ...]) -> None:
    data = struct.pack(">4I", count, *offsets) + bytes(16)
    with pytest.raises(AssetError):
        parse_asset_lut(data, 0, 16)


def test_rare_wrapper_and_explicit_uncompressed_passthrough() -> None:
    payload = b"Reference asset with signed fields\0" * 50
    compressed = wrap(payload)
    assert compressed[:5] == struct.pack("<IB", len(payload), 9)
    assert decompress_rare(compressed + bytes(15)) == payload
    assert decode_asset(compressed, compressed=False) == compressed
    assert decode_asset(payload, compressed=False) is payload
    assert decode_asset(compressed, compressed=True) == payload
    assert decompress_rare(wrap(b"")) == b""


@pytest.mark.parametrize("variant", ["short", "level", "size", "truncated", "deflate", "bomb"])
def test_bad_compression_is_bounded_and_never_silently_raw(variant: str) -> None:
    data = wrap(b"abcd" * 200)
    if variant == "short":
        data = data[:4]
    elif variant == "level":
        data = data[:4] + b"\x08" + data[5:]
    elif variant == "size":
        data = struct.pack("<I", 1) + data[4:]
    elif variant == "truncated":
        data = data[:-2]
    elif variant == "deflate":
        data = data[:5] + b"\x07"
    else:
        data = struct.pack("<I", 0xFFFFFFFF) + data[4:]
    with pytest.raises(CompressionError):
        decompress_rare(data)


@pytest.mark.parametrize("kind,count", [(AssetType.LEVEL_MODELS, 55), (AssetType.LEVEL_OBJECT_MAPS, 138)])
def test_every_real_compressed_model_and_map(rom: RomImage, kind: AssetType, count: int) -> None:
    assert rom.count(kind) == count
    for index in range(count):
        raw = rom.read_asset(kind, index)
        output = rom.read_asset(kind, index, decompress=True)
        if not raw:
            assert kind == AssetType.LEVEL_OBJECT_MAPS and index in (81, 99) and output == b""
            continue
        assert len(output) == struct.unpack_from("<I", raw)[0]
    if kind == AssetType.LEVEL_MODELS:
        assert len(rom.read_asset(kind, 0, decompress=True)) == 135994
    else:
        assert len(rom.read_asset(kind, 0, decompress=True)) == 4256


def test_real_level_catalog_fields_and_signed_sentinels(rom: RomImage) -> None:
    catalog = load_level_catalog(rom)
    assert len(catalog.levels) == 65
    central, ancient, walrus, wizpig = (catalog.levels[i] for i in (0, 5, 1, 55))
    assert central.name == "Central Area" and central.header.category == "Hub"
    assert ancient.name == "Ancient Lake"
    assert (ancient.header.geometry_id, ancient.header.object_map_id, ancient.header.secondary_object_map_id) == (5, 73, 5)
    assert ancient.header.background_color == (120, 65, 24)
    assert ancient.names.german == "Rumpelsee" and ancient.names.french == "LAC ANCESTRAL"
    assert ancient.names.japanese == "サンシャインレイク"
    assert (walrus.header.fog.near, walrus.header.fog.far, walrus.header.fog.color) == (994, 1001, (200, 230, 255))
    assert wizpig.header.skybox_id == -1 and wizpig.header.category == "Boss"
    assert catalog.levels[21].header.world == -1
    assert catalog.levels[64].name == "Lastbitb"
    assert {level.header.category for level in catalog.levels} >= {"Track", "Hub", "Boss", "Challenge", "Cutscene / Menu"}
    assert all(level.header.raw_data is not None and len(level.header.raw_data) == 0xC8 for level in catalog.levels)


def test_header_offsets_are_big_endian_and_unknown_tail_is_preserved() -> None:
    raw = bytearray(0xC8)
    struct.pack_into(">b", raw, 0, -1)
    struct.pack_into(">f", raw, 8, 123.5)
    struct.pack_into(">10b", raw, 0x20, -1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    struct.pack_into(">3h", raw, 0x34, 0x1234, 0x2345, -1)
    struct.pack_into(">5h", raw, 0x3A, 1000, 1020, 12, 34, 56)
    struct.pack_into(">h", raw, 0xBA, -1)
    raw[0xC4:] = b"TAIL"
    header = LevelHeader.from_bytes(bytes(raw))
    assert (header.geometry_id, header.object_map_id, header.skybox_id) == (0x1234, 0x2345, -1)
    assert header.ai_adv1 == (-1, 2, 3, 4, 5) and header.ai_adv2 == (6, 7, 8, 9, 10)
    assert header.world == -1 and header.course_height == 123.5
    assert header.raw_data is not None and header.raw_data[0xC4:] == b"TAIL"
    assert replace(header, raw_data=bytes(raw[:0xC4])) == LevelHeader.from_bytes(bytes(raw[:0xC4]))
    with pytest.raises(AssetError):
        LevelHeader.from_bytes(bytes(raw[:100]))


@pytest.mark.parametrize("data", [b"abc", b"a\0b\0c\0\x80", b"a\0b\0c\0\x81\xFF\0"])
def test_malformed_name_entries_are_rejected(data: bytes) -> None:
    with pytest.raises(AssetError):
        LevelNames.from_bytes(data)


def test_jp_character_map_matches_local_text_source() -> None:
    path = DECOMP / "tools/dkr_assets_tool_src/text/dkrText.cpp"
    if not path.is_file():
        pytest.skip("Local text reference not present")
    section = path.read_text(encoding="utf-8").split("DKRJP_FONT_CHARACTERS = {", 1)[1].split("};", 1)[0]
    literals = re.findall(r'"(?:\\.|[^"\\])*"', section)
    assert tuple(json.loads(literal) for literal in literals) == JP_CHARACTERS


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def extracted(tmp_path: Path) -> Path:
    root = tmp_path / "decomp/assets/.vanilla/us.v80"
    definitions = {
        "ASSET_LEVEL_HEADERS": ["ASSET_LEVEL_TEST"],
        "ASSET_LEVEL_MODELS": ["MODEL_A", "MODEL_WITH_MISLEADING_999"],
        "ASSET_LEVEL_OBJECT_MAPS": ["MAP_B", "MAP_A"],
        "ASSET_OBJECTS": ["SKY_TEST"],
        "ASSET_LEVEL_NAMES": ["TEST_NAME"],
    }
    sections: dict[str, object] = {}
    for name, order in definitions.items():
        filename = name.lower() + ".meta.json"
        sections[name] = {"filename": filename}
        write_json(root / filename, {"folder": "levels", "files": {
            "order": order, "sections": {key: {"filename": key + ".json"} for key in order}}})
    write_json(root / "assets.meta.json", {"@dkr-version": "us.v80", "assets": {"sections": sections}})
    rgb = {"red": 12, "green": 34, "blue": 56}
    write_json(root / "levels/ASSET_LEVEL_TEST.json", {
        "type": "LevelHeader", "name": {"LANGUAGE_ENGLISH": "Test Hub", "LANGUAGE_FRENCH": "Test FR"},
        "world": "WORLD_DINO_DOMAIN", "model": "MODEL_WITH_MISLEADING_999",
        "map-collectables": "MAP_A", "map-2": "MAP_B", "race-type": "RACETYPE_HUBWORLD",
        "default-vehicle": "VEHICLE_PLANE", "avaliable-vehicles": ["VEHICLE_CAR", "VEHICLE_PLANE"],
        "course-height": 99.5, "fog": {"near": 994, "far": 1001, "colour": rgb},
        "background": {"colour": rgb, "skybox": {"id": "SKY_TEST"}, "multiplayer": {
            "gradient-colour": {"bottom": rgb, "top": rgb}}},
    })
    return root


def test_extracted_json_resolves_manifest_order_and_builder_defaults(extracted: Path) -> None:
    # Selecting the source checkout root discovers .vanilla/us.v80 automatically.
    source = DecompAssets.from_directory(extracted.parents[2])
    assert source.root == extracted
    entry, = load_level_catalog(source).levels
    assert entry.name == "Test Hub" and entry.names.french == "Test FR"
    assert (entry.header.geometry_id, entry.header.object_map_id, entry.header.secondary_object_map_id) == (1, 1, 0)
    assert (entry.header.world, entry.header.vehicle, entry.header.available_vehicles) == (1, 2, 5)
    assert (entry.header.camera_fov, entry.header.laps) == (60, 3)
    assert entry.header.fog.color == (12, 34, 56) and entry.header.raw_data is None


@pytest.mark.parametrize("direct", [False, True], ids=["raw-descriptor", "direct-bin"])
def test_extracted_binary_catalog_reads_existing_files(extracted: Path, direct: bool) -> None:
    header = bytearray(0xC8)
    struct.pack_into(">3h", header, 0x34, 1, 1, -1)
    path = extracted / "levels/ASSET_LEVEL_TEST.json"
    write_json(path, {"type": "Binary", "raw": "test-header.bin"})
    (path.parent / "test-header.bin").write_bytes(header)
    write_json(extracted / "levels/TEST_NAME.json", {"type": "LevelName", "languages": {
        "LANGUAGE_ENGLISH": "Binary Stage", "LANGUAGE_GERMAN": "Bin"}})
    if direct:
        header_manifest = extracted / "asset_level_headers.meta.json"
        value = json.loads(header_manifest.read_text())
        value["files"]["sections"]["ASSET_LEVEL_TEST"]["filename"] = "test-header.bin"
        write_json(header_manifest, value)
        name_manifest = extracted / "asset_level_names.meta.json"
        value = json.loads(name_manifest.read_text())
        value["files"]["sections"]["TEST_NAME"]["filename"] = "test-name.bin"
        write_json(name_manifest, value)
        (extracted / "levels/test-name.bin").write_bytes(b"Binary Stage\0Bin\0\0\0")
    entry, = load_level_catalog(DecompAssets.from_directory(extracted)).levels
    assert entry.name == "Binary Stage" and entry.names.german == "Bin"
    assert entry.header.geometry_id == 1 and entry.header.skybox_id == -1


@pytest.mark.parametrize("field,value", [("model", "MISSING_MODEL"), ("name", []),
                                         ("course-height", 10 ** 400), ("fov", "sixty")])
def test_invalid_extracted_headers_fail_with_asset_errors(extracted: Path, field: str, value: object) -> None:
    path = extracted / "levels/ASSET_LEVEL_TEST.json"
    document = json.loads(path.read_text())
    document[field] = value
    write_json(path, document)
    with pytest.raises(AssetError, match="Level 0"):
        load_level_catalog(DecompAssets.from_directory(extracted))


def test_extracted_raw_compressed_asset_and_path_bounds(extracted: Path) -> None:
    source = DecompAssets.from_directory(extracted)
    write_json(extracted / "levels/MODEL_A.json", {"type": "LevelModel", "raw": "model.bin"})
    (extracted / "levels/model.bin").write_bytes(wrap(b"test model bytes"))
    assert source.read_asset(AssetType.LEVEL_MODELS, 0, decompress=True) == b"test model bytes"
    write_json(extracted / "levels/MODEL_A.json", {"raw": "../../escape.bin"})
    with pytest.raises(AssetError, match="outside"):
        source.read_asset(AssetType.LEVEL_MODELS, 0)


def test_missing_extraction_and_wrong_revision_have_clear_errors(tmp_path: Path, extracted: Path) -> None:
    with pytest.raises(AssetError, match="No extracted us.v80"):
        DecompAssets.from_directory(tmp_path / "empty")
    manifest = extracted / "assets.meta.json"
    value = json.loads(manifest.read_text())
    value["@dkr-version"] = "us.v77"
    write_json(manifest, value)
    with pytest.raises(AssetError, match="us.v80"):
        DecompAssets.from_directory(extracted)


def test_core_imports_do_not_initialize_qt_or_gl() -> None:
    code = (
        "import sys; import src.core.rom, src.core.compression, src.core.level_header, src.core.level_model, src.core.exporter, src.core.editing; "
        "assert not any(k.startswith(('PySide6', 'OpenGL')) for k in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)
