# Simple runtime requirements v0.28.0 — complete (2026-10-31)

requirements.txt now contains one comment and the same eight exact runtime pins;
removed the long artifact-hash lists. Complete hashed pylock.toml and CI's direct
lock installation are unchanged. Updated install/regeneration commands, guides
and release notes. Runtime-to-lock test checks concise exact pins and version
alignment; the separate lock test still requires hashes on every artifact.
No dependency upgrades, environment modifications or application behavior changes.

Verified8 release/lock consistency checks pass in0.34s; diff checks pass. Ignored
JUnit: artifacts/simple-requirements-tests.xml. Owned pytest fixtures cleaned;
user files, ROMs/builds and running editors preserved. Version remains0.28.0.

Next: user reviews the short requirements file and pushes when ready. This
refinement stays local; no push, tag, build, emulator or ROM generation requested.
Previous published handoff60746f0 remains intact.
