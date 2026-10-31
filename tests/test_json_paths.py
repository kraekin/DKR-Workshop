"""User-selected JSON paths and constrained extracted-asset references."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.rom import AssetError, DecompAssets, read_json


def test_explicit_selected_file_can_live_outside_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / 'work'
    work.mkdir()
    selected = tmp_path / 'selected.json'
    selected.write_text('\ufeff{"selected": true}', encoding='utf-8')
    original = selected.read_bytes()
    monkeypatch.chdir(work)
    assert read_json(Path('../selected.json')) == {'selected': True}
    assert read_json(selected) == {'selected': True}
    assert selected.read_bytes() == original


@pytest.mark.parametrize('relative', [False, True])
def test_asset_json_escape_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: bool,
) -> None:
    root = tmp_path / 'assets'
    root.mkdir()
    sibling = tmp_path / 'assets-other'
    sibling.mkdir()
    target = sibling / 'outside.json'
    target.write_text('{"outside": true}', encoding='utf-8')
    path = root / '../assets-other/outside.json' if relative else target

    def unexpected_read(*args: object, **kwargs: object) -> str:
        pytest.fail('Out-of-root JSON was opened')

    monkeypatch.setattr(Path, 'read_text', unexpected_read)
    with pytest.raises(AssetError, match='outside'):
        read_json(path, root=root)


def test_asset_json_normalizes_valid_internal_path(tmp_path: Path) -> None:
    root = tmp_path / 'assets'
    (root / 'nested').mkdir(parents=True)
    (root / 'metadata.json').write_text('{"inside": true}', encoding='utf-8')
    assert read_json(root / 'nested/../metadata.json', root=root) == {'inside': True}


def test_directory_is_not_accepted_as_json(tmp_path: Path) -> None:
    with pytest.raises(AssetError, match='regular JSON file'):
        read_json(tmp_path)


def test_resolution_loop_becomes_a_normal_load_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def loop(self: Path, strict: bool = False) -> Path:
        raise RuntimeError('Symlink loop')

    monkeypatch.setattr(Path, 'resolve', loop)
    with pytest.raises(AssetError, match='Cannot resolve JSON'):
        read_json(tmp_path / 'loop.json')


@pytest.mark.parametrize('text', ['[]', '{broken', '\udcff'])
def test_invalid_json_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / 'invalid.json'
    path.write_bytes(text.encode('utf-8', errors='surrogateescape'))
    with pytest.raises(AssetError):
        read_json(path)


def test_directory_link_cannot_escape_json_root(tmp_path: Path) -> None:
    root, outside = tmp_path / 'assets', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (outside / 'metadata.json').write_text('{"outside": true}', encoding='utf-8')
    link = root / 'linked'
    if os.name == 'nt':
        # Directory junctions need no Windows file-symlink privilege.
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    else:
        link.symlink_to(outside, target_is_directory=True)
    assert link.resolve() == outside.resolve()
    with pytest.raises(AssetError, match='outside'):
        read_json(link / 'metadata.json', root=root)


def test_root_manifest_canonical_escape_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / 'assets'
    root.mkdir()
    manifest = root / 'assets.meta.json'
    manifest.write_text('{"@dkr-version":"us.v80"}', encoding='utf-8')
    outside = tmp_path / 'outside.json'
    outside.write_bytes(manifest.read_bytes())
    resolve = Path.resolve

    def redirected_resolve(self: Path, strict: bool = False) -> Path:
        # Simulate a file symlink's canonical target even where Windows denies
        # file-symlink creation. The separate test exercises real directory links.
        return outside if self == manifest else resolve(self, strict=strict)

    monkeypatch.setattr(Path, 'resolve', redirected_resolve)
    with pytest.raises(AssetError, match='outside'):
        DecompAssets.from_directory(root)


def test_direct_decomp_construction_pins_relative_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / 'assets'
    root.mkdir()
    (root / 'metadata.json').write_text('{"inside": true}', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    source = DecompAssets(Path('assets'), {})
    assert source.root == root
    assert source.read_json(root / 'metadata.json') == {'inside': True}
    (tmp_path / 'outside.json').write_text('{}', encoding='utf-8')
    with pytest.raises(AssetError, match='outside'):
        source.read_json(tmp_path / 'outside.json')
