"""Check the self-contained EXE away from the checkout and Python environment."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    release = ROOT / "artifacts" / "windows-release"
    executable = release / "DKR Workshop.exe"
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("Release is not a Windows executable")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(6) != b"PE\0\0\x64\x86":
            raise RuntimeError("Release is not an x64 PE executable")
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("PYTHON", "CONDA", "QT_", "PYSIDE"))
                   and key.upper() not in ("VIRTUAL_ENV", "_OLD_VIRTUAL_PATH")}
    environment["PATH"] = str(Path(environment["SYSTEMROOT"]) / "System32")
    with tempfile.TemporaryDirectory(prefix="workshop-release-") as temporary:
        folder = Path(temporary)
        isolated = folder / executable.name
        shutil.copy2(executable, isolated)
        result = subprocess.run([str(isolated), "--help"], cwd=folder, env=environment,
                                capture_output=True, text=True, timeout=180)
        log = result.stdout + result.stderr
        (ROOT / "artifacts" / "windows-build" / "packaged-help.log").write_text(log, encoding="utf-8")
        if result.returncode != 0 or "usage:" not in result.stdout or "--rom" not in result.stdout:
            raise RuntimeError(f"Packaged EXE startup failed ({result.returncode}):\n{log}")
        if set(folder.iterdir()) != {isolated}:
            raise RuntimeError("Onefile startup left unexpected sidecar files")
    with executable.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (release / "SHA256SUMS.txt").write_text(f"{digest}  {executable.name}\n", encoding="utf-8")
    print(f"Isolated x64 EXE startup passed: {executable.stat().st_size:,} bytes\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
