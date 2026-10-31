# GitHub publishing and hosted Windows builds — in progress (2026-10-30)

User explicitly authorized pushing the completed v0.27.1 changes to
kraekin/DKR-Workshop and setting up GitHub-hosted Nuitka builds. Preserve local
ROMs, research, personal assets and existing editor processes; upload source
and build configuration only. No binary formats or application behavior change.

Confirmed origin/main history retained, local main has four completed commits,
GitHub authentication permits pushes/workflows, and Actions is enabled. Existing
v0.26.0 release used Nuitka onefile, PySide6, embedded icon and dependency notices.
The v0.27.1 application already passed all 1,853 tests and native placement checks.

Implemented pinned CPython3.12/MSVC/Nuitka Windows onefile CI: manual builds,
matching version tags, draft release attachments and published-release builds.
Explicit artifact paths contain only the EXE, notices/readme and checksum.
Public README retains all four existing screenshot URLs.

Preflight: actionlint1.7.12 passes with no findings; all12 ROM-free camera/release
checks pass; source --help starts; application/build Python syntax passes; diff
whitespace check passes. Tracked-file audit finds no ROMs, exports or binaries.

All five local commits pushed to origin/main through ed3780f. GitHub registered
the workflow; first manual run: https://github.com/kraekin/DKR-Workshop/actions/runs/41158499075
The first hosted preflight found a fresh-checkout issue: pytest's configured
artifacts/pytest base needs its parent directory created before tests. Workflow
now creates artifacts explicitly. Next: verify a fresh source copy, push the fix,
rerun the hosted build and verify its downloaded EXE. No ROM/emulator CI or tag.
