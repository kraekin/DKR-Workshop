# GitHub publishing and hosted Windows builds — configured (2026-10-30)

User authorized publishing the completed v0.27.1 updates and GitHub-hosted
Nuitka builds. All application changes and CI configuration are on origin/main.
Build source commit: 8d6c571. No ROMs, extracted assets, editor projects or build
binaries were committed. Existing editors and local research remain untouched.

Windows CI uses pinned CPython3.12/MSVC/Nuitka/PySide6 dependencies, embeds the
existing icon and dependency notices, and uploads explicit release files only.
Manual branch builds upload Actions artifacts; matching version tags build a
Windows x64 EXE/checksum and attach them to a draft release. Publishing a release
without an EXE also triggers a build. Ordinary main pushes do not compile.
Guide: docs/WINDOWS_BUILDS.md. Public README retains its four screenshot URLs.

Verification: actionlint passes; all12 ROM-free checks and source --help pass
locally, in a fresh source copy, and on the corrected hosted run. First run
41158499075 failed because artifacts/pytest lacked its parent directory; fixed
by creating artifacts before tests. Prior application gate: all1,853 tests pass.
No binary formats or application behavior changed during this milestone.

Current build: https://github.com/kraekin/DKR-Workshop/actions/runs/41158679071
Last observed: preflight passed, Nuitka compilation in progress. User explicitly
requested no further waiting/testing and will download/test or report a failure.
Next: user reviews the completed build. Do not claim compilation, packaged EXE
startup or hosted graphics verification passed; those were not yet observed.
No new version tag or public release was created during setup.
