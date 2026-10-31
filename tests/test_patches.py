"""Patch format integrity, relocation, normalized bases and ROM export safety."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import random
import struct
import zlib
import pytest

from src.core.patches import encode_bps, encode_xdelta, apply_bps, apply_generated_xdelta
from src.core.editing import EditSession
from src.core.rom import RomImage


@pytest.mark.parametrize("kind", ["bps", "xdelta"])
def test_empty_identical_insert_delete_and_relocated_bytes(kind: str) -> None:
    encoder, decoder = (encode_bps, apply_bps) if kind == "bps" else (encode_xdelta, apply_generated_xdelta)
    randomizer = random.Random(729)
    source = randomizer.randbytes(65536)
    targets = [b"", source, b"prefix" + source + b"suffix", source[1000:40000],
               source[30000:] + source[:30000], source[:500] + b"new bytes" * 200 + source[2500:]]
    for original in (b"", source):
        for target in targets:
            patch = encoder(original, target)
            assert decoder(original, patch) == target
    assert len(encoder(source, source[30000:] + source[:30000])) < 1000


@pytest.mark.parametrize("kind", ["bps", "xdelta"])
def test_corruption_and_wrong_base_are_refused(kind: str) -> None:
    encoder, decoder = (encode_bps, apply_bps) if kind == "bps" else (encode_xdelta, apply_generated_xdelta)
    source = bytes(range(256)) * 40
    target = source[:100] + b"changed" + source[120:]
    patch = encoder(source, target)
    for size in (0, 4, 9, len(patch) - 1):
        with pytest.raises(ValueError):
            decoder(source, patch[:size])
    corrupt = bytearray(patch)
    corrupt[-1] ^= 1
    with pytest.raises(ValueError):
        decoder(source, bytes(corrupt))
    with pytest.raises(ValueError):
        decoder(bytes(len(source)), patch)


def test_bps_golden_literal_and_crc_fields() -> None:
    # Hand-computed BPS1: empty source, three literal target bytes, no metadata.
    header = b"BPS1\x80\x83\x80\x89abc"
    body = header + struct.pack("<II", 0, zlib.crc32(b"abc"))
    golden = body + struct.pack("<I", zlib.crc32(body))
    assert encode_bps(b"", b"abc") == golden
    assert apply_bps(b"", golden) == b"abc"


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


@pytest.mark.parametrize("extension", [".bps", ".xdelta"])
def test_real_export_matches_existing_rom_builder_and_preserves_history(rom: RomImage, tmp_path: Path, extension: str) -> None:
    session = EditSession(rom)
    session.edit_minimap(5, {"red": 42})
    expected = session.build_rom()
    signature, history = session._signature(), session._cursor
    path = session.save_patch(tmp_path / ("course" + extension))
    decoder = apply_bps if extension == ".bps" else apply_generated_xdelta
    assert decoder(rom.data, path.read_bytes()) == expected
    assert session._signature() == signature and session._cursor == history
    assert session.dirty


def test_original_path_wrong_extension_and_failed_export_do_not_write(rom: RomImage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "original.bps"
    session = EditSession(replace(rom, source_path=path))
    with pytest.raises(ValueError, match="original ROM"):
        session.save_patch(path)
    with pytest.raises(ValueError, match="filename"):
        session.save_patch(tmp_path / "wrong.z64")
    destination = tmp_path / "existing.bps"
    destination.write_bytes(b"keep me")
    def refuse() -> bytes:
        raise ValueError("preflight refused")
    monkeypatch.setattr(session, "build_rom", refuse)
    with pytest.raises(ValueError, match="preflight refused"):
        session.save_patch(destination)
    assert destination.read_bytes() == b"keep me" and not path.exists()


@pytest.mark.parametrize("unit", [2, 4])
def test_patch_base_is_normalized_for_swapped_input(rom: RomImage, tmp_path: Path, unit: int) -> None:
    import numpy as np
    swapped = np.frombuffer(rom.data, np.uint8).reshape(-1, unit)[:, ::-1].copy().tobytes()
    source = RomImage.from_bytes(swapped)
    assert source.byte_order in ("v64", "n64") and source.data == rom.data
    session = EditSession(source)
    session.edit_minimap(5, {"green": 34})
    path = session.save_patch(tmp_path / "normalized.bps")
    assert apply_bps(rom.data, path.read_bytes()) == session.build_rom()
    with pytest.raises(ValueError, match="original source"):
        apply_bps(swapped, path.read_bytes())
