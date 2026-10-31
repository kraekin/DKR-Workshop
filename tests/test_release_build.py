"""Release labels must describe the compiled source; no ROM or GUI required."""
from __future__ import annotations

from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]
release_version = runpy.run_path(str(ROOT / ".github/scripts/build_windows.py"))["release_version"]


def test_current_release_metadata_agrees() -> None:
    version = release_version(ROOT)
    assert release_version(ROOT, f"v{version}") == version


@pytest.mark.parametrize("tag", ["v0.26.0", "0.27.1", "v0.27.1-extra"])
def test_release_rejects_incorrect_tag(tag: str) -> None:
    with pytest.raises(ValueError, match="must match source version"):
        release_version(ROOT, tag)


def test_release_rejects_disagreeing_source_version(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/__init__.py").write_text('__version__ = "1.2.4"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="must match pyproject"):
        release_version(tmp_path)


def test_release_rejects_non_windows_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3rc1"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="three-part release version"):
        release_version(tmp_path)
