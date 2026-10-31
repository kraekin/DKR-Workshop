"""Headless saved environment values, animation flags and transient water."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct

import numpy as np
import pytest

from src.core.environment import (WaveSettings, _wave_grid, flashy_sky, fog_defaults,
                                  fog_factor, scroll_rates, scroll_delta, texture_frame, water_preview)
from src.core.editing import EditSession
from src.core.level_header import load_level_catalog
from src.core.level_model import TriangleBatchInfo, load_level_model
from src.core.objects import load_object_database, load_object_map
from src.core.rom import AssetType, RomImage
from src.core.textures import Texture, load_model_textures, load_texture

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:
        pytest.skip('Local Rev1 ROM absent')
    return RomImage.from_file(paths[0])


def flipbook(advance: int = 256) -> Texture:
    data = bytearray()
    for index in range(3):
        h = bytearray(32); h[:3] = (2, 2, 0x10); h[18] = 3
        struct.pack_into('>Hh', h, 20, advance, 48)
        data.extend(h+bytes((index*80, 255-index*80, 0, 255))*4)
    return Texture.from_bytes(bytes(data))


@pytest.mark.parametrize('flags,expected', (
    (0x10000, [0, 1, 2, 0, 1, 2, 0]),
    (0x10000 | 0x4000000, [0, 2, 1, 0, 2, 1, 0]),
    (0x10000 | 0x2000000, [0, 1, 2, 2, 1, 0, 0]),
    (0x10000 | 0x800000, [0]*7),
    (0, [0]*7),
))
def test_source_flipbook_modes(flags: int, expected: list[int]) -> None:
    batch = TriangleBatchInfo(0, 0, 0, 0, 0, 0, flags)
    texture = flipbook()
    assert [texture_frame(texture, batch, tick/60+.0000001) for tick in range(7)] == expected
    assert texture_frame(texture, batch, 0) == expected[0]
    assert texture_frame(texture, batch, -1) == expected[0]


def test_fractional_frame_bits_static_offset_and_triggered_one_shot() -> None:
    texture = flipbook(32)
    batch = TriangleBatchInfo(0, 0, 0, 0, 0, 0, 0x10000)
    assert texture_frame(texture, batch, 1) == 0  # track discards six fractional bits
    retained = replace(batch, flags=batch.flags | 0x80000000)
    assert texture_frame(texture, retained, 8/60+.0000001) == 1
    assert texture_frame(texture, retained, 16/60+.0000001) == 2
    assert texture_frame(texture, replace(batch, flags=0, texture_offset=8), 20) == 2
    one_shot = replace(batch, flags=0x10000 | 0x800000 | 0x2000000)
    texture = flipbook()
    assert [texture_frame(texture, one_shot, t/60+.0000001) for t in range(10)] == [0, 1, 2, 2, 1, 0, 0, 0, 0, 0]


def test_long_scrub_matches_cycle_without_state_mutation() -> None:
    texture = flipbook()
    batch = TriangleBatchInfo(0, 0, 0, 0, 0, 0, 0x10000)
    assert texture_frame(texture, batch, 500) == 0
    assert texture_frame(texture, batch, 500+1/60+.0000001) == 1
    assert texture_frame(texture, batch, 0) == 0


def test_saved_fog_projection_units_clamps_and_reset(rom: RomImage) -> None:
    catalog = load_level_catalog(rom)
    assert not fog_defaults(catalog.levels[0].header)[-1]
    h = catalog.levels[6].header
    assert fog_defaults(h) == (996., 1002., (0., 0., 48/255), True)
    modified = replace(h, fog=replace(h.fog, near=1200, far=1010))
    assert fog_defaults(modified)[:2] == (1010., 1023.)
    modified = replace(h, fog=replace(h.fog, near=1000, far=1000))
    assert fog_defaults(modified)[:2] == (995., 1000.)
    assert fog_factor(10, 996, 1002) == 0
    assert 0 < fog_factor(3000, 996, 1002) < 1
    assert fog_factor(15000, 996, 1002) == pytest.approx(2/3)


def test_wave_header_offsets_signs_and_missing_structured_fields(rom: RomImage) -> None:
    header = load_level_catalog(rom).levels[7].header
    settings = WaveSettings.from_header(header)
    assert settings.subdivisions == 4 and settings.tiles == 8
    assert settings.height0 == 18 and settings.height1 == pytest.approx(4172/256)
    assert settings.seed_size == 120 and settings.power == 207/256
    assert settings.uv_scroll[1] == -2 and not settings.translucent
    assert WaveSettings.from_header(replace(header, raw_data=None)) is None
    raw = bytearray(header.raw_data); raw[0x56] = 255
    with pytest.raises(ValueError, match='bounds'):
        WaveSettings.from_header(replace(header, raw_data=bytes(raw)))


def test_wave_grid_time_period_bounds_and_boundary_continuity(rom: RomImage) -> None:
    settings = WaveSettings.from_header(load_level_catalog(rom).levels[4].header)
    grid = _wave_grid(settings.tiles, settings.seed_size)
    assert grid.shape == (16, 16, 2) and grid.min() >= 0 and grid.max() < settings.seed_size
    assert not grid.flags.writeable
    xz = np.array(((0., 0.), (10., 20.), (100., 200.)), np.float32)
    first = settings.heights(xz, 0, (0., 0.), (100., 100.))
    second = settings.heights(xz, .5, (0., 0.), (100., 100.))
    assert not np.array_equal(first, second)
    np.testing.assert_array_equal(first, settings.heights(xz, settings.seed_size/60+.0000001, (0., 0.), (100., 100.)))
    assert np.abs(first).max() <= 2*(abs(settings.height0)+abs(settings.height1))*settings.power
    boundary = np.array(((99.9999, 100.), (100., 100.), (100.0001, 100.)), np.float32)
    assert np.ptp(settings.heights(boundary, .5, (0., 0.), (100., 100.))) < .01


def test_stock_water_is_transient_and_preserves_original_footprints(rom: RomImage) -> None:
    catalog = load_level_catalog(rom)
    found = 0
    for level in catalog.levels:
        model = load_level_model(rom, level.header.geometry_id)
        textures = load_model_textures(rom, model)
        before = model.raw_data
        water = water_preview(model, WaveSettings.from_header(level.header), textures)
        if water is None:
            continue
        found += 1
        assert water.vertices.shape[1] == 9 and len(water.vertices) % 3 == 0
        assert not water.vertices.flags.writeable and water.faces
        for seconds in (0., .5, 2.):
            data = water.buffer(textures[water.texture_id], seconds)
            assert np.isfinite(data).all() and np.all(data[:, 6] >= 0) and np.all(data[:, 6] <= 1)
            np.testing.assert_array_equal(data[:, (0, 2)], water.vertices[:, (0, 2)])
        assert before == model.raw_data
    assert found >= 10


def test_scroll_controllers_resolve_slots_without_mutating_entries(rom: RomImage) -> None:
    db = load_object_database(rom)
    catalog = load_level_catalog(rom)
    controllers = 0
    for level in catalog.levels:
        objects = tuple(o for m in dict.fromkeys((level.header.object_map_id, level.header.secondary_object_map_id)) if m >= 0
                        for o in load_object_map(rom, m, db).objects)
        slots = len(load_level_model(rom, level.header.geometry_id).textures)
        rates = scroll_rates(objects, slots)
        if rates:
            controllers += 1
        assert all(0 <= slot < slots for slot in rates)
        assert scroll_rates(objects, 0) == {}
    assert controllers > 10


def test_flash_sky_has_verified_plane_frame_and_camera_translation(rom: RomImage) -> None:
    h = load_level_catalog(rom).levels[55].header
    texture = load_texture(rom, h.special_sky_texture, asset_type=AssetType.TEXTURES_2D)
    camera = np.array((10., 20., 30.), np.float32)
    data = flashy_sky(h, texture, camera, -90, 0)
    assert data.shape == (24, 9)
    assert np.all(data[:, 1] == 212.) and data[:, 6].min() == 0 and data[:, 6].max() == 1
    shifted = flashy_sky(h, texture, camera+(20., 30., 40.), -90, 0)
    np.testing.assert_allclose(shifted[:, :3]-data[:, :3], np.tile((20., 30., 40.), (24, 1)))


def test_environment_previews_do_not_change_session_or_overlay(rom: RomImage) -> None:
    session = EditSession(rom)
    signature = session._signature()
    h = session.level_header(4); model = session.track_model(h.geometry_id)
    textures = load_model_textures(session.asset_source, model)
    water = water_preview(model, WaveSettings.from_header(h), textures)
    water.buffer(textures[water.texture_id], 10)
    fog_defaults(h)
    assert not session.dirty and session._signature() == signature


def test_scroll_fraction_is_kept_per_controller_before_combining() -> None:
    rates = ((1, -1), (1, -1))
    np.testing.assert_array_equal(scroll_delta(rates, 2), (0, -2))
    np.testing.assert_array_equal(scroll_delta(rates, 4), (2, -2))
    np.testing.assert_array_equal(scroll_delta(rates, 0), (0, 0))
