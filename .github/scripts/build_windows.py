"""Build the Windows release from tracked source, without a ROM or local assets."""
from __future__ import annotations

import argparse
import ast
from importlib.metadata import distribution
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "artifacts" / "windows-build"
RELEASE = ROOT / "artifacts" / "windows-release"
DEPENDENCIES = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
                "PyOpenGL", "numpy", "Pillow", "zstandard")


def release_version(root: Path, tag: str | None = None) -> str:
    """Refuse mismatched source/package versions or version tags before compiling."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Expected a three-part release version, got {version!r}")
    tree = ast.parse((root / "src" / "__init__.py").read_text(encoding="utf-8-sig"))
    versions = [ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__"
                        for target in node.targets)]
    if versions != [version]:
        raise ValueError("src.__version__ must match pyproject.toml before release")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Tag {tag!r} must match source version v{version}")
    return version


def prepare_notices(destination: Path, version: str) -> None:
    """Include installed wheel notices both beside the EXE and in its payload."""
    lines = [f"DKR Workshop {version} - bundled runtime dependencies", "",
             f"Python {sys.version.split()[0]}"]
    for name in DEPENDENCIES:
        package = distribution(name)
        lines.append(f"{package.metadata['Name']} {package.version}")
        for file in package.files or ():
            if ".dist-info" not in str(file) or not any(
                word in str(file).lower() for word in ("license", "copying", "notice")
            ):
                continue
            source = Path(package.locate_file(file))
            if source.is_file():
                # Retain relative paths so identically named notices cannot overwrite.
                relative = Path(*file.parts[1:])
                target = destination / "licenses" / name / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for name in ("LICENSE.txt", "LICENSE_PYTHON.txt"):
        source = Path(sys.base_prefix) / name
        if source.is_file():
            target = destination / "licenses" / "Python" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (destination / "THIRD_PARTY_NOTICES.txt").write_text(
        "\n".join(lines) + "\n\nBundled license notices are in licenses/.\n", encoding="utf-8")
    (destination / "README.txt").write_text(
        f"DKR Workshop {version} - Windows x64\n\n"
        "Double-click DKR Workshop.exe. Python and runtime dependencies are embedded.\n"
        "An OpenGL 3.3-capable graphics driver is required.\n"
        "Use File > Open ROM to open your own original Diddy Kong Racing USA Rev 1 ROM.\n"
        "No ROM or extracted game artwork is included in this build.\n"
        "Guides and source: https://github.com/kraekin/DKR-Workshop\n",
        encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    options = parser.parse_args()
    tag = os.environ.get("GITHUB_REF_NAME") if os.environ.get("GITHUB_REF_TYPE") == "tag" else None
    version = release_version(ROOT, tag)
    print(f"Building DKR Workshop {version}", flush=True)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"version={version}\n")
    if options.prepare_only:
        return
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("Release builds require 64-bit Windows CPython")
    if (BUILD.exists() and any(BUILD.iterdir())) or (RELEASE.exists() and any(RELEASE.iterdir())):
        raise RuntimeError("Release output already contains files; use a fresh checkout")
    BUILD.mkdir(parents=True, exist_ok=True)
    RELEASE.mkdir(parents=True, exist_ok=True)
    prepare_notices(RELEASE, version)
    entry = BUILD / "workshop.py"
    entry.write_text("from src.main import main\n\nif __name__ == '__main__':\n"
                     "    raise SystemExit(main())\n", encoding="utf-8")
    command = [sys.executable, "-B", "-X", "utf8", "-m", "nuitka",
               "--mode=onefile", "--onefile-no-dll", "--enable-plugin=pyside6",
               "--include-qt-plugins=sensible,styles", "--msvc=latest",
               f"--jobs={min(os.cpu_count() or 2, 4)}", "--windows-console-mode=attach",
               "--include-windows-runtime-dlls=yes", "--assume-yes-for-downloads",
               f"--output-dir={BUILD}", "--output-filename=DKR Workshop.exe",
               "--windows-icon-from-ico=src/ui/resources/workshop.ico",
               "--include-data-files=src/ui/resources/workshop.ico=src/ui/resources/workshop.ico",
               f"--include-data-dir={RELEASE / 'licenses'}=licenses",
               f"--include-data-files={RELEASE / 'README.txt'}=README.txt",
               f"--include-data-files={RELEASE / 'THIRD_PARTY_NOTICES.txt'}=THIRD_PARTY_NOTICES.txt",
               "--product-name=DKR Workshop", f"--product-version={version}",
               f"--file-version={version}.0", "--file-description=DKR Workshop",
               f"--report={BUILD / 'compilation-report.xml'}", str(entry)]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    shutil.copy2(BUILD / "DKR Workshop.exe", RELEASE / "DKR Workshop.exe")


if __name__ == "__main__":
    main()
