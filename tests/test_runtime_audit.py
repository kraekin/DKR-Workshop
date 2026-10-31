"""Read-only runtime research: generated RAM fixtures and local source symbols."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import struct
import io
import zipfile
import zstandard

import pytest

from src.core.rom import AssetType, RomImage
from src.core.runtime_audit import (CODE_ADDRESSES, MEMORY_POOLS, NUMBER_OF_POOLS,
    OBJECT_POOL_POINTER, OBJECT_COUNT, OBJECT_LIST, OBJECT_MAP_IDS, OBJECT_MAP_POINTERS, HEADER_REFERENCES,
    LOADED_HEADERS, SPRITE_CACHE, SPRITE_COUNT, TEXTURE_CACHE, TEXTURE_COUNT, PARTICLES,
    RuntimeAuditError, read_runtime_snapshot, read_runtime_capture, snapshot_summary)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:
        pytest.skip('Local original Rev 1 ROM absent')
    return RomImage.from_file(paths[0])


def make_snapshot(rom: RomImage, *, size: int = 4*1024*1024) -> bytes:
    """Synthetic heap, not a recorded gameplay measurement or bundled game data."""
    ram = bytearray(size)
    def pack(fmt: str, address: int, *values: int) -> None:
        struct.pack_into(fmt, ram, address-0x80000000, *values)
    for address in CODE_ADDRESSES:
        ram[address-0x80000000:address-0x80000000+64] = rom.data[address-0x80000400+0x1000:address-0x80000400+0x1040]
    pack('>i', NUMBER_OF_POOLS, 1)
    pack('>I', 0x80000318, size)
    pack('>iiIi', MEMORY_POOLS, 1600, 3, 0x80200000, 0x200000)
    pack('>iiIi', MEMORY_POOLS+16, 512, 3, 0x80210000, 0x18000)
    # Main free / reserved object subpool / main free. Every descriptor is20B.
    pack('>IihhhhI', 0x80200000, 0x80207D00, 0x8300, 0, -1, 1, 0, 0)
    pack('>IihhhhI', 0x80200014, 0x80210000, 0x18000, 1, 0, 2, 1, 0)
    pack('>IihhhhI', 0x80200028, 0x80228000, 0x1D8000, 0, 1, -1, 2, 0)
    # Object shared header / one208B instance / remaining free.
    pack('>IihhhhI', 0x80210000, 0x80212800, 128, 1, -1, 1, 0, 0)
    pack('>IihhhhI', 0x80210014, 0x80212880, 208, 1, 0, 2, 1, 0)
    pack('>IihhhhI', 0x80210028, 0x80212950, 0x15800-336, 0, 1, -1, 2, 0)
    pack('>I', OBJECT_POOL_POINTER, 0x80210000)
    pack('>i', OBJECT_COUNT, 1)
    pack('>I', OBJECT_LIST, 0x80180000)
    pack('>I', 0x80180000, 0x80212880)
    pack('>2i', OBJECT_MAP_IDS, 0, 68)
    pack('>2I', OBJECT_MAP_POINTERS, 0x80190000, 0x80193000)
    pack('>I', HEADER_REFERENCES, 0x80181000)
    pack('>B', 0x80181000+52, 1)
    pack('>I', LOADED_HEADERS, 0x80182000)
    pack('>I', 0x80182000+52*4, 0x80212800)
    pack('>I', SPRITE_CACHE, 0x80183000)
    pack('>i', SPRITE_COUNT, 2)  # one active and one cache hole
    pack('>iI', 0x80183000, 116, 0x80186000)
    pack('>iI', 0x80183008, -1, 0)
    pack('>h', 0x80186004, 1)
    pack('>I', TEXTURE_CACHE, 0x80184000)
    pack('>i', TEXTURE_COUNT, 1)
    pack('>iI', 0x80184000, 123, 0x80187000)
    pack('>B', 0x80187005, 1)
    for (_, live, maximum), limit in zip(PARTICLES, (8, 16, 150, 100, 50)):
        pack('>i', live, 0)
        pack('>i', maximum, limit)
    return bytes(ram)


def test_addresses_match_the_authoritative_rev1_symbols() -> None:
    symbols = ROOT/'research/Diddy-Kong-Racing/ver/symbols/symbol_addrs.us.v80.txt'
    if not symbols.exists():
        pytest.skip('Local decomp absent')
    text = symbols.read_text()
    expected = dict(zip(('spawn_object', 'mempool_slot_find', 'gzip_inflate'), CODE_ADDRESSES))
    expected.update(gMemoryPools=MEMORY_POOLS, gNumberOfMemoryPools=NUMBER_OF_POOLS,
        gObjectCount=OBJECT_COUNT, gObjPtrList=OBJECT_LIST, gObjectMemoryPool=OBJECT_POOL_POINTER,
        gObjectMapID=OBJECT_MAP_IDS, gObjectMap=OBJECT_MAP_POINTERS, gObjectHeaderReferences=HEADER_REFERENCES,
        gLoadedObjectHeaders=LOADED_HEADERS, gSpriteCache=SPRITE_CACHE,
        gSpriteCacheCount=SPRITE_COUNT, gTextureCache=TEXTURE_CACHE,
        gNumberOfLoadedTextures=TEXTURE_COUNT)
    for label, address in expected.items():
        match = re.search(rf'^{label} = (0x[0-9A-Fa-f]+);', text, re.MULTILINE)
        assert match and int(match[1], 16) == address
    for name, count, maximum in PARTICLES:
        assert f'gNum{name}Particles = 0x{count:08X};' in text
        assert f'gMax{name}Particles = 0x{maximum:08X};' in text


@pytest.mark.parametrize('width,size', ((1, 4*1024*1024), (2, 4*1024*1024), (4, 8*1024*1024)))
def test_dump_orders_heap_fragmentation_and_caches(rom: RomImage, width: int, size: int) -> None:
    data = make_snapshot(rom, size=size)
    if width > 1:
        swapped = bytearray(size)
        for i in range(width):
            swapped[i::width] = data[width-i-1::width]
        data = bytes(swapped)
    snapshot = read_runtime_snapshot(data, rom, 304)
    import hashlib
    assert snapshot.source_digest == hashlib.sha256(data).hexdigest()
    assert snapshot.object_count == 1 and snapshot.map_ids == (0, 68)
    pool = snapshot.pools[1]
    assert pool.data_bytes == 88064 and pool.free_bytes == pool.largest_free == 88064-336
    assert pool.descriptors == 3 and pool.split_allocations_remaining == 508
    assert snapshot.sprite_high_water == 2 and len(snapshot.sprites) == 1
    assert snapshot.sprites[0].asset_id == 116 and snapshot.sprites[0].references == 1
    assert snapshot.header_references[52] == 1 and snapshot.textures[0].references == 1
    text = snapshot.to_text()
    assert 'NOW' in text and 'cannot establish a safe extra-object count' in text
    assert 'Do not subtract particle counts again' in text
    assert 'not identify the loaded asset/project edits' in text


@pytest.mark.parametrize('mutation', ('size', 'code', 'count', 'pointer', 'pools', 'cycle',
    'size_total', 'prev_link', 'header_pointer', 'sprite_wrap', 'texture_wrap',
    'cache_count', 'cache_duplicate', 'particle_count', 'maps', 'duplicate_object'))
def test_inconsistent_or_unsupported_snapshots_are_rejected(rom: RomImage, mutation: str) -> None:
    data = bytearray(make_snapshot(rom))
    def pack(fmt: str, address: int, *values: int) -> None:
        struct.pack_into(fmt, data, address-0x80000000, *values)
    if mutation == 'size': data.pop()
    elif mutation == 'code': data[CODE_ADDRESSES[1]-0x80000000] ^= 1
    elif mutation == 'count': pack('>i', OBJECT_COUNT, 513)
    elif mutation == 'pointer': pack('>I', OBJECT_LIST, 0xBFFFFFFC)
    elif mutation == 'pools': pack('>i', NUMBER_OF_POOLS, 0)
    elif mutation == 'cycle': pack('>h', 0x80210028+12, 0)
    elif mutation == 'size_total': pack('>i', 0x80210028+4, 16)
    elif mutation == 'prev_link': pack('>h', 0x80210014+10, -1)
    elif mutation == 'header_pointer': pack('>I', 0x80182000+52*4, 0)
    elif mutation == 'sprite_wrap': pack('>h', 0x80186004, -32768)
    elif mutation == 'texture_wrap': pack('>B', 0x80187005, 0)
    elif mutation == 'cache_count': pack('>i', SPRITE_COUNT, 101)
    elif mutation == 'cache_duplicate': pack('>iI', 0x80183008, 116, 0x80186000)
    elif mutation == 'particle_count': pack('>i', PARTICLES[0][1], 8)
    elif mutation == 'maps': pack('>i', OBJECT_MAP_IDS, 138)
    else:
        pack('>i', OBJECT_COUNT, 2)
        pack('>I', 0x80180004, 0x80212880)
    with pytest.raises(RuntimeAuditError):
        read_runtime_snapshot(bytes(data), rom, 304)


def test_sample_ranges_are_observations_grouped_by_map_roles(rom: RomImage) -> None:
    first = read_runtime_snapshot(make_snapshot(rom), rom, 304)
    second = replace(first, object_count=4, pools=(first.pools[0], replace(first.pools[1], free_bytes=16000, largest_free=8000)))
    third = replace(first, map_ids=(5, 73), object_count=99)
    text = snapshot_summary((first, second, third))
    assert 'Map roles (0, 68): 2 samples' in text and '4/512' in text
    assert 'Map roles (5, 73): 1 samples' in text and '99/512' in text
    assert '16,000 B' in text and '8,000 B' in text
    assert 'no worst-case or structural-edit approval' in text
    unloaded = bytearray(make_snapshot(rom))
    struct.pack_into('>I', unloaded, OBJECT_MAP_POINTERS-0x80000000+4, 0)
    assert read_runtime_snapshot(bytes(unloaded), rom, 304).map_ids == (0, -1)


def test_bad_configuration_and_changed_source_rejected(rom: RomImage) -> None:
    with pytest.raises(RuntimeAuditError):
        read_runtime_snapshot(make_snapshot(rom), rom, 10)
    with pytest.raises(RuntimeAuditError):
        read_runtime_snapshot(make_snapshot(rom), replace(rom, data=rom.data[:-1]+bytes([rom.data[-1]^1])), 304)


def make_state(core: bytes, *, version: bytes = b'Version 2.10\r\n') -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('BizState 1.0', b'1.0')
        archive.writestr('BizVersion.txt', version)
        # Real BizHawk carriers omit the content size; cover that decoding path.
        archive.writestr('Core.bin', zstandard.ZstdCompressor(write_content_size=False).compress(core))
    return output.getvalue()


def test_bizhawk_state_locates_ram_from_code_anchors_not_fixed_offset(rom: RomImage) -> None:
    ram = make_snapshot(rom)
    swapped = bytearray(len(ram))
    for i in range(4): swapped[i::4] = ram[3-i::4]
    # Deliberately different from the observed carrier offset0x1C0.
    header = struct.pack('<I', len(ram))+b'M64+SAVE\x00\x01\x00\x00'+bytes(0x650)
    state = make_state(header+swapped+bytes(100))
    snapshot = read_runtime_capture(state, rom, 304)
    assert snapshot.rdram_offset == len(header) and snapshot.object_count == 1
    assert snapshot.byte_order == '32-bit word swap' and snapshot.source_digest
    assert 'BizHawk 2.10' in snapshot.source_format and snapshot.core_digest
    assert 'three independent executable anchors' in snapshot.to_text()
    assert read_runtime_capture(ram, rom, 304).rdram_offset is None


@pytest.mark.parametrize('mutation', ('version', 'core', 'missing_ram', 'ambiguous', 'mem_size', 'truncated_zip'))
def test_bizhawk_carrier_refusals(rom: RomImage, mutation: str) -> None:
    ram = make_snapshot(rom)
    header = struct.pack('<I', len(ram))+b'M64+SAVE\x00\x01\x00\x00'
    core = header+ram
    version = b'Version 2.10'
    if mutation == 'version': version = b'Version 2.11'
    elif mutation == 'core': core = b'Unknown emulator'+ram
    elif mutation == 'missing_ram': core = header+bytes(len(ram))
    elif mutation == 'ambiguous': core += ram
    elif mutation == 'mem_size': core = core[:len(header)+0x318]+bytes(4)+core[len(header)+0x31C:]
    state = make_state(core, version=version)
    if mutation == 'truncated_zip': state = state[:-30]
    with pytest.raises(RuntimeAuditError): read_runtime_capture(state, rom, 304)


def test_oversized_or_unrecognized_carriers_rejected(rom: RomImage) -> None:
    for data in (b'PK\x03\x04truncated', bytes(33*1024*1024), b'unsupported'):
        with pytest.raises(RuntimeAuditError): read_runtime_capture(data, rom, 304)
