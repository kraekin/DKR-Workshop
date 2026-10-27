"""Read-only export budgets and diffs; no Qt, GL or file writes.

Section addresses follow local src/asset_loading.c:asset_table_load.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from src.core.rom import AssetType, LUT_END, RomImage


@dataclass(frozen=True)
class AssetDiff:
    section: int
    index: int
    name: str
    original_bytes: int
    edited_bytes: int
    original_stored: int
    edited_stored: int
    levels: tuple[str, ...]
    changes: tuple[str, ...]


@dataclass(frozen=True)
class SectionBudget:
    index: int
    name: str
    original_start: int
    edited_start: int
    original_bytes: int
    edited_bytes: int


@dataclass(frozen=True)
class ExportReport:
    rom_bytes: int
    original_end: int
    projected_end: int
    padding_bytes: int
    sections: tuple[SectionBudget, ...]
    assets: tuple[AssetDiff, ...]
    errors: tuple[str, ...]

    @property
    def growth_bytes(self) -> int:
        return self.projected_end - self.original_end

    @property
    def remaining_bytes(self) -> int:
        return self.padding_bytes - self.growth_bytes

    @property
    def can_export(self) -> bool:
        return not self.errors

    @property
    def summary(self) -> str:
        return (f"{'Ready to export' if self.can_export else 'Export blocked'} · "
                f"{len(self.assets)} changed asset(s) · growth {self.growth_bytes:+,} B · "
                f"{self.remaining_bytes:,} B padding remaining")

    def retain_validation_errors(self, previous: ExportReport,
                                 previous_layout_errors: tuple[str, ...]) -> ExportReport:
        """Keep runtime/writer refusals while replacing stale storage errors.

        The new report already checks the complete candidate layout. A previous
        padding/alignment failure must not veto a candidate that repairs it.
        """
        return replace(self, errors=tuple(dict.fromkeys((
            *(error for error in previous.errors if error not in previous_layout_errors),
            *self.errors,
        ))))

    def to_text(self) -> str:
        lines = [self.summary, "", f"ROM size: {self.rom_bytes:,} B (unchanged)",
                 f"Asset end: 0x{self.original_end:X} → 0x{self.projected_end:X}",
                 f"Original usable trailing padding: {self.padding_bytes:,} B",
                 "Padding is ROM storage, not additional game RAM.",
                 "The original ROM remains read-only. Export writes a separate file."]
        lines.extend(f"BLOCKED: {error}" for error in self.errors)
        if not self.assets:
            lines.extend(("", "No changes. Export is byte-identical to the original ROM."))
        for asset in self.assets:
            lines.extend(("", f"{asset.name} (section {asset.section}, entry {asset.index})",
                          f"  Decoded bytes: {asset.original_bytes:,} → {asset.edited_bytes:,}",
                          f"  Stored bytes: {asset.original_stored:,} → {asset.edited_stored:,} "
                          f"({asset.edited_stored - asset.original_stored:+,})",
                          "  Affected levels: " + ("; ".join(asset.levels) or "No level-header reference")))
            lines.extend(f"  {change}" for change in asset.changes)
        lines.extend(("", "Asset sections (untouched contents are preserved even when relocated):"))
        for section in self.sections:
            delta = section.edited_bytes - section.original_bytes
            lines.append(f"  {section.index:02d} {section.name}: {section.original_bytes:,} → "
                         f"{section.edited_bytes:,} B ({delta:+,}); "
                         f"0x{section.original_start:X} → 0x{section.edited_start:X}")
        return "\n".join(lines)


def make_export_report(rom: RomImage, sections: tuple[bytes, ...],
                       assets: tuple[AssetDiff, ...]) -> ExportReport:
    """Calculate the exact layout used by the writer, including rejected layouts."""
    original_end = rom.sections[-1].end
    padding_end = original_end
    while padding_end < len(rom.data) and rom.data[padding_end] in (0, 255):
        padding_end += 1
    address = LUT_END
    budgets: list[SectionBudget] = []
    errors: list[str] = []
    for index, (old, raw) in enumerate(zip(rom.sections, sections)):
        try:
            name = AssetType(index).name
        except ValueError:
            name = f"Section {index}"
        budgets.append(SectionBudget(index, name, old.start, address, old.size, len(raw)))
        if address % 16 or len(raw) % 16:
            errors.append(f"Section {index} does not retain 16-byte section alignment")
        address += len(raw)
    if len(sections) != len(rom.sections):
        errors.append("Asset section count must stay unchanged")
    if address > padding_end:
        errors.append("Edited assets exceed the original ROM's available padding")
    return ExportReport(len(rom.data), original_end, address, padding_end - original_end,
                        tuple(budgets), assets, tuple(errors))
