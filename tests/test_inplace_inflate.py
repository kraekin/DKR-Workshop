"""Independent streams exercise game-specific loading hazards beyond zlib."""
from __future__ import annotations

from pathlib import Path
import random
import struct
import zlib

import pytest

from src.core.compression import CompressionError, audit_inplace_rare, decompress_rare
from src.core.editing import EditError, EditSession, compress_object_map
from src.core.rom import AssetType, RomImage
from src.core.structure import StructuralDraft, decorative_reasons, raw_map, simple_instance_bytes


class Bits:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def put(self, value: int, width: int) -> None:
        self.bits.extend((value >> i) & 1 for i in range(width))

    def code(self, value: int, width: int) -> None:
        self.bits.extend((value >> i) & 1 for i in reversed(range(width)))

    def align(self) -> None:
        self.bits.extend([0] * (-len(self.bits) % 8))

    def bytes(self) -> bytes:
        self.align()
        return bytes(sum(self.bits[i+j] << j for j in range(8)) for i in range(0, len(self.bits), 8))


def wrap(raw: bytes, stream: bytes) -> bytes:
    data = struct.pack('<IB', len(raw), 9) + stream
    return data + bytes(-len(data) % 16)


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(Path(__file__).resolve().parents[1].glob('*.z64'))
    if not paths:
        pytest.skip('Local original Rev 1 ROM absent')
    return RomImage.from_file(paths[0])


@pytest.mark.parametrize('recompress', (False, True))
def test_all_nonempty_maps_model_output_accesses_and_heap(rom: RomImage, recompress: bool) -> None:
    audits = []
    for i in range(138):
        packed = rom.read_asset(AssetType.LEVEL_OBJECT_MAPS, i)
        if not packed:
            continue
        if recompress:
            packed = compress_object_map(decompress_rare(packed))
        report = audit_inplace_rare(packed)
        assert report.decoded == len(decompress_rare(packed))
        assert report.minimum_gap >= 0 and report.read_bytes <= len(packed)
        assert report.huft_bytes <= 0x2800
        audits.append(report)
    assert len(audits) == 136
    assert {kind for report in audits for kind in report.blocks} == {1, 2}
    assert min(report.minimum_gap for report in audits) == (16 if recompress else 15)


@pytest.mark.parametrize('level,strategy', ((0, zlib.Z_DEFAULT_STRATEGY), (9, zlib.Z_DEFAULT_STRATEGY), (9, zlib.Z_FIXED)))
def test_stored_fixed_dynamic_and_short_backreferences(level: int, strategy: int) -> None:
    randomizer = random.Random(71)
    for raw in (b'A'*6000, bytes(randomizer.randrange(256) for _ in range(7000)),
                b'ABC'*2200, bytes(range(256))*30):
        compressor = zlib.compressobj(level, zlib.DEFLATED, -15, 8, strategy)
        packed = wrap(raw, compressor.compress(raw)+compressor.flush())
        audit = audit_inplace_rare(packed)
        assert audit.decoded == len(raw)
        if level == 0:
            assert audit.blocks == (0,)


def test_zero_length_stored_block_valid_to_zlib_but_unsafe_for_game() -> None:
    packed = wrap(b'', b'\x01\x00\x00\xFF\xFF')
    assert decompress_rare(packed) == b''
    with pytest.raises(CompressionError, match='Zero-length stored'):
        audit_inplace_rare(packed)


def test_valid_stream_with_incomplete_zero_length_tree_is_unverified() -> None:
    bits = Bits()
    bits.put(1, 1); bits.put(2, 2)  # final dynamic block
    bits.put(1, 5); bits.put(1, 5); bits.put(14, 4)  #258 literals,2 distances,18 code lengths
    order = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1)
    for symbol in order:
        bits.put({0: 1, 1: 2, 2: 2}.get(symbol, 0), 3)
    literal_lengths = [0]*258
    literal_lengths[65], literal_lengths[256], literal_lengths[257] = 1, 2, 2
    for length in (*literal_lengths, 0, 1):
        bits.code({0: 0, 1: 2, 2: 3}[length], 1 if length == 0 else 2)
    for _ in range(8192):
        bits.code(0, 1)
    bits.code(2, 2)  #end of block
    packed = wrap(b'A'*8192, bits.bytes())
    assert decompress_rare(packed) == b'A'*8192
    with pytest.raises(CompressionError, match='uninitialized'):
        audit_inplace_rare(packed)


def test_valid_multiblock_stream_overwrites_unread_input_despite_fitting_workspace(
        rom: RomImage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bits = Bits()
    bits.put(0, 1); bits.put(1, 2)  #non-final fixed block
    bits.code(0x30+65, 8)  #literal A
    for _ in range(16):
        bits.code(0xC0+285-280, 8); bits.put(0, 5)  #length258,distance1
    bits.code(0, 7)  #end of block
    tail = bytes(range(64))*32
    for i in range(32):
        bits.put(int(i == 31), 1); bits.put(0, 2); bits.align()
        for value in struct.pack('<HH', 64, 64 ^ 0xFFFF)+tail[i*64:(i+1)*64]:
            bits.put(value, 8)
    raw = b'A'*(1+16*258)+tail
    packed = wrap(raw, bits.bytes())
    assert decompress_rare(packed) == raw
    assert len(raw)+32 <= 0x3000 and len(packed) <= len(raw)+32
    with pytest.raises(CompressionError, match='overwrites unread'):
        audit_inplace_rare(packed)
    session = EditSession(rom)
    obj = session.current_map(5).objects[0]
    session.set_position(obj.key, (obj.position[0]+1, *obj.position[1:]))
    monkeypatch.setattr('src.core.editing.compress_object_map', lambda _: packed)
    report = session.export_report()
    assert any('in-place inflater' in error for error in report.errors)
    destination = tmp_path/'must-not-be-created.z64'
    with pytest.raises(EditError): session.save_rom(destination)
    assert not destination.exists() and session.dirty and session.can_undo


def test_decoration_subset_roundtrips_all_original_templates_without_approving_additions(rom: RomImage) -> None:
    session = EditSession(rom)
    count = 0
    for map_id in range(138):
        draft = StructuralDraft(session, map_id)
        original = raw_map(draft.model)
        for obj in draft.model.objects:
            if decorative_reasons(obj):
                continue
            assert obj.definition.name in ('PalmTreeTopChea', 'PalmTreeTop')
            assert simple_instance_bytes(obj) == 208
            identity = draft.source_ids[obj.index]
            draft.append(identity)
            audit_inplace_rare(compress_object_map(draft.serialize()))
            draft.undo(); assert draft.serialize() == original
            draft.remove(identity)
            audit_inplace_rare(compress_object_map(draft.serialize()))
            draft.undo(); assert draft.serialize() == original
            count += 1
    assert count == 58 and not session.dirty


def test_bad_workspace_and_truncation_rejected() -> None:
    packed = compress_object_map(b'AB'*100)
    for kwargs in ({'workspace': 0}, {'workspace': True}, {'slack': -1}, {'workspace': 200}):
        with pytest.raises(CompressionError):
            audit_inplace_rare(packed, **kwargs)
    with pytest.raises(CompressionError):
        audit_inplace_rare(packed[:6])
