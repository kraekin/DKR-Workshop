# Nuitka toolchain update v0.28.0 — verified (2026-10-31)

Official Nuitka download page and PyPI confirm stable4.3.3. Updated the exact
compiler input4.2.1 ->4.3.3 and regenerated pylock.toml from PyPI. AST/TOML review:
only the Nuitka package/version/artifact hash changes; runtime requirements and
all19 other locked packages are unchanged. Updated build guide/release notes.
App version remains0.28.0; existing environments and user files/builds preserved.

A fresh isolated environment installed all20 locked packages successfully.
Nuitka --version reports4.3.3; existing onefile/PySide6/MSVC options accepted.
14 release/lock/camera checks pass in0.47s, pip check passes, build --prepare-only
and app --help pass. No local EXE compilation performed. Ignored JUnit:
artifacts/nuitka433-tests.xml. Owned validation environment/test fixtures cleaned;
download cache retained. No ROM export, emulator or user editor interruption.

Publish this related hosted-toolchain update under existing CI/GitHub scope.
Next hosted builds from updated main will use4.3.3. Prior run41253183235 used
4.2.1; GitHub now reports it cancelled. No cancellation was performed here.
Check for other active runs before dispatching one fresh4.3.3 build. User owns
full-build download/testing; no tag/release requested.
