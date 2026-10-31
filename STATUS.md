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

GitHub handoff explicitly authorized by the user on2026-10-31: push the completed
requirements cleanup e495ffe to origin/main. Fresh remote preflight confirms
main60746f0 is an ancestor, with no conflicting remote or application edits.
Next: user reviews GitHub main after the handoff. No tag, manual build, release,
emulator or ROM generation requested. Future work remains local unless authorized.
