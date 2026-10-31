"""Export capacity, shared map use, read-only diffs and project migration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.core.editing import EditError, EditSession
from src.core.export_report import make_export_report
from src.core.rom import AssetType, REV1_SHA1, RomImage


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


def test_original_budget_and_reports_are_read_only(rom: RomImage) -> None:
    session = EditSession(rom)
    report = session.export_report()
    assert report.can_export and report.padding_bytes == 471088
    assert report.remaining_bytes == 471088 and report.growth_bytes == 0
    assert report.projected_end == 0xB8CFD0 and len(report.sections) == 50
    assert not report.assets and "byte-identical" in report.to_text()
    assert not session.dirty and not session.can_undo
    assert session.export_report() is report
    assert session.build_rom() == rom.data


def test_exact_growth_shared_usage_diff_and_history(rom: RomImage) -> None:
    session = EditSession(rom)
    obj = session.current_map(95).objects[0]
    session.set_position(obj.key, (obj.position[0] + 1, *obj.position[1:]))
    before = session.project_document()
    report = session.export_report()
    assert report.growth_bytes == 16 and report.remaining_bytes == 471072
    asset, = report.assets
    assert asset.index == 95 and asset.edited_stored - asset.original_stored == 16
    assert "XYZ:" in report.to_text() and "0x" in report.to_text()
    expected = tuple(f"{l.index}: {l.name}" for l in session._catalog.levels
                     if 95 in (l.header.object_map_id, l.header.secondary_object_map_id))
    assert asset.levels == expected
    assert before == session.project_document() and session.dirty
    sections, _ = session._prepare_export()
    assert sum(map(len, sections)) + 0xED1B0 == report.projected_end
    for section in report.sections[22:]:
        assert section.edited_start == section.original_start + 16
        assert section.edited_bytes == section.original_bytes
    session.undo()
    assert not session.export_report().assets and not session.dirty
    session.redo()
    assert session.export_report() == report


def test_capacity_exact_boundary_alignment_and_protected_tail(rom: RomImage) -> None:
    sections = tuple(rom.data[s.start:s.end] for s in rom.sections)
    padding = 471088
    full = sections[:-1] + (sections[-1] + bytes(padding),)
    assert make_export_report(rom, full, ()).remaining_bytes == 0
    assert make_export_report(rom, full, ()).can_export
    over = sections[:-1] + (sections[-1] + bytes(padding + 16),)
    report = make_export_report(rom, over, ())
    assert not report.can_export and report.remaining_bytes == -16
    assert "padding" in report.to_text()
    smaller = sections[:-1] + (sections[-1][:-16],)
    assert make_export_report(rom, smaller, ()).remaining_bytes == padding + 16
    unaligned = sections[:-1] + (sections[-1] + b"x",)
    assert any("alignment" in error for error in make_export_report(rom, unaligned, ()).errors)
    data = bytearray(rom.data)
    data[rom.sections[-1].end + 16] = 1
    guarded = RomImage(bytes(data), "z64", rom.sections)
    assert make_export_report(guarded, full, ()).padding_bytes == 16
    assert not make_export_report(guarded, full, ()).can_export


def test_v1_migrates_and_v2_round_trips(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    session.set_position((5, 0), (11, 22, 33))
    legacy = session.project_document(5)
    legacy["version"] = 1
    legacy.pop("asset_edits")
    legacy.pop("research")
    path = tmp_path / "legacy.dkrproj"
    path.write_text(json.dumps(legacy))
    loaded = EditSession.load_project(path)
    assert loaded.object((5, 0)).position == (11, 22, 33) and not loaded.dirty
    assert loaded.project_document()["version"] == 6
    upgraded = loaded.save_project(tmp_path / "upgraded.dkrproj", 5)
    assert EditSession.load_project(upgraded).build_rom() == loaded.build_rom()
    assert hashlib.sha1(rom.source_path.read_bytes()).hexdigest() == REV1_SHA1


@pytest.mark.parametrize("section", [21, 29, 34])
def test_future_asset_writers_disabled(rom: RomImage, tmp_path: Path, section: int) -> None:
    session = EditSession(rom)
    document = session.project_document()
    document["asset_edits"] = [{"section": section, "index": 0, "bytes": []}]
    path = tmp_path / "unsupported.dkrproj"
    path.write_text(json.dumps(document))
    with pytest.raises(EditError, match="not enabled"):
        EditSession.load_project(path)
    assert not session.dirty
