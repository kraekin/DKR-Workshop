"""Release labels must describe the compiled source; no ROM or GUI required."""
from __future__ import annotations

from pathlib import Path
import re
import runpy
import tomllib

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


def _package_name(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def test_build_lock_pins_inputs_and_hashes_every_artifact() -> None:
    lock = tomllib.loads((ROOT / 'pylock.toml').read_text(encoding='utf-8'))
    assert lock['lock-version'] == '1.0'
    packages = {_package_name(p['name']): p for p in lock['packages']}
    assert len(packages) == len(lock['packages'])
    for line in (ROOT / '.github/requirements-build.txt').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, version = line.split('==')
        assert packages[_package_name(name)]['version'] == version
    for package in packages.values():
        artifacts = package.get('wheels', []) + ([package['sdist']] if 'sdist' in package else [])
        assert artifacts, package['name']
        for artifact in artifacts:
            assert artifact['url'].startswith('https://files.pythonhosted.org/')
            assert re.fullmatch(r'[0-9a-f]{64}', artifact['hashes']['sha256'])


def test_hashed_runtime_requirements_match_build_lock() -> None:
    lock = tomllib.loads((ROOT / 'pylock.toml').read_text(encoding='utf-8'))
    packages = {_package_name(p['name']): p for p in lock['packages']}
    text = (ROOT / 'requirements.txt').read_text().replace('\\\n', ' ')
    runtime: set[str] = set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        name, version = line.split()[0].split('==')
        name = _package_name(name)
        package = packages[name]
        assert version == package['version']
        hashes = set(re.findall(r'--hash=sha256:([0-9a-f]{64})', line))
        assert hashes, name
        artifacts = package.get('wheels', []) + ([package['sdist']] if 'sdist' in package else [])
        assert {a['hashes']['sha256'] for a in artifacts} <= hashes
        runtime.add(name)
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    required = {_package_name(re.split(r'[<>=!~\[]', d)[0]) for d in project['project']['dependencies']}
    assert required <= runtime
