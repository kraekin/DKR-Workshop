"""Read-only ROM About art, tile compositing and bounded menu references."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import struct

import numpy as np
import pytest

from src.core import about_artwork as art
from src.core.rom import RomImage
from src.core.textures import SpriteAsset, TextureError


def test_composite_uses_alpha_and_retains_negative_tile_positions() -> None:
    green = np.array([[[0, 255, 0, 255], [0, 255, 0, 255]]], np.uint8)
    red = np.array([[[255, 0, 0, 0], [255, 0, 0, 255]]], np.uint8)
    result = art._compose(((green, -5, -2), (red, -5, -2)))
    np.testing.assert_array_equal(result, [[[0, 255, 0, 255], [255, 0, 0, 255]]])
    assert not result.flags.writeable


@pytest.mark.parametrize('bounds', [(0, 0, 0, 1), (0, 0, 1, 0), (-5, 0, 2044, 2)])
def test_composite_refuses_invalid_bounds_before_allocating(bounds: tuple[int, ...]) -> None:
    with pytest.raises(TextureError):
        art._compose((), bounds)


@pytest.mark.parametrize('table', [b'', bytes(181), bytes(183)])
def test_title_refuses_short_or_odd_table(table: bytes) -> None:
    with pytest.raises(TextureError, match='Truncated'):
        art._title(SimpleNamespace(section=lambda _: table))


def test_title_rejects_nontexture_menu_reference() -> None:
    with pytest.raises(TextureError, match='not a menu texture'):
        art._title(SimpleNamespace(section=lambda _: bytes(0x5B*2)))


def test_title_reads_references_and_fifteen_pixel_stride(monkeypatch: pytest.MonkeyPatch) -> None:
    table = bytearray(0x5B*2)
    for i in range(11):
        struct.pack_into('>H', table, (0x50+i)*2, 0xC000+30+i)
    seen = []
    def texture(source: object, index: int, **kwargs: object) -> object:
        seen.append(index)
        pixels = np.zeros((2, 16, 4), np.uint8)
        pixels[:] = (index, 0, 0, 255)
        return SimpleNamespace(frames=(SimpleNamespace(pixels=pixels),))
    monkeypatch.setattr(art, 'load_texture', texture)
    result = art._title(SimpleNamespace(section=lambda _: bytes(table)))
    assert seen == list(range(30, 41)) and result.shape == (2, 166, 4)
    assert result[0, 14, 0] == 30 and result[0, 15, 0] == 31 and result[0, -1, 0] == 40


def test_sprite_frames_keep_a_common_origin_and_empty_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(art, 'load_sprite', lambda *_: SpriteAsset(3, 5, (0, 0), (0, 1, 1, 2)))
    def texture(source: object, index: int, **kwargs: object) -> object:
        header = bytearray(32)
        struct.pack_into('>bb', header, 3, -2 if index == 5 else 3, 0)
        pixels = np.array([[[255, 0, 0, 255]]], np.uint8)
        return SimpleNamespace(frames=(SimpleNamespace(header=SimpleNamespace(raw=header), pixels=pixels),))
    monkeypatch.setattr(art, 'load_texture', texture)
    frames = art._sprite_frames(None, 3)
    assert len(frames) == 3 and all(p.shape == (1, 6, 4) for p in frames)
    assert frames[0][0, 0, 3] == 255 and frames[2][0, 5, 3] == 255
    assert not frames[1].any()


def test_stock_about_artwork_is_complete_and_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = list(root.glob('*.z64'))
    if not paths:
        pytest.skip('Local original Rev 1 ROM not present')
    rom = RomImage.from_file(paths[0])
    original = hashlib.sha1(rom.data).hexdigest()
    result = art.load_about_artwork(rom)
    assert len(result.balloons) == 6 and len(result.pop_frames) == 10
    assert result.logo.shape == (64, 162, 4)
    assert result.background.shape == (32, 64, 4)
    assert all(np.any(p[:, :, 3]) for p in result.balloons)
    assert len({p.shape for p in result.pop_frames}) == 1
    assert all(not p.flags.writeable for p in (*result.balloons, *result.pop_frames, result.logo,
                                             result.background, result.sun, result.zipper))
    assert hashlib.sha1(rom.data).hexdigest() == original
