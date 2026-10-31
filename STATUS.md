# Nuitka toolchain update v0.28.0 — complete (2026-10-31)

Official Nuitka download page and PyPI confirm stable4.3.3. Updated the exact
compiler input4.2.1 ->4.3.3 and regenerated pylock.toml from PyPI. TOML comparison:
only the Nuitka package/version/artifact hash changes; runtime requirements and
all19 other locked packages are unchanged. Updated build guide/release notes.
App version remains0.28.0; existing environments and user files/builds preserved.

A fresh isolated environment installed all20 locked packages successfully.
Nuitka --version reports4.3.3; existing onefile/PySide6/MSVC options accepted.
14 release/lock/camera checks pass in0.47s, pip check passes, build --prepare-only
and app --help pass. No local EXE compilation performed. Ignored JUnit:
artifacts/nuitka433-tests.xml. Owned validation environment/test fixtures cleaned;
download cache retained. No ROM export, emulator or user editor interruption.

Published compiler update2aaae9a under existing hosted-toolchain/GitHub scope.
Prior4.2.1 run41253183235 was already cancelled; no other run was active.
Started one fresh4.3.3 build from the updated commit:
https://github.com/kraekin/DKR-Workshop/actions/runs/41253564511
Verified its head and active locked-install step. Next: user downloads/tests when
it finishes; no full-compile wait, duplicate build, tag or release requested.
