# Dependency locking and animation randomness v0.28.0 — complete (2026-10-31)

Generated pylock.toml (PEP751) for the verified Windows x64/CPython3.12 toolchain:
20 pinned runtime/test/build packages with artifact SHA256 hashes. CI installs
the lock directly via pinned uv0.11.14; isolated build dependencies are version-
constrained too. Runtime requirements.txt now pins transitive versions and hashes;
source setup uses --require-hashes/--only-binary. Input/toolchain versions remain
deliberate. Updated source/build/release guides and lock-regeneration instructions.
Two CI release checks prevent input/lock/runtime drift or missing artifact hashes.

About balloons now use SystemRandom (OS-backed entropy). This is decorative
animation, not credentials/security decisions. Position/speed/phase/variant/scale
ranges and animation timing unchanged; deterministic test PRNG fixtures retained.
Release notes updated; app version remains0.28.0.

Verified a fresh isolated environment installed all20 locked packages, pip check
passes and repeat uv sync dry-run reports no changes.25 release/camera/artwork
checks pass in0.62s using locked pytest8.4.2; app --help imports and Windows build
--prepare-only pass. Native About artwork/animation/pop check passes with the
locked runtime; original ROM unchanged.146 Python files parse and diff checks
pass. Existing project environment, user files, builds and editors preserved.
Ignored evidence: artifacts/final-sonar-lock-tests.xml, sonar-about-random.png,
verify_about_random.py. Owned validation environment/pytest fixtures cleaned;
download cache retained. No standalone EXE compile or gameplay ROM generated.

GitHub handoff authorized by the user on2026-10-31: push the completed fixes
304b3d0 to origin/main. Fresh remote preflight confirms main at9e02ca5 is an
ancestor, with no conflicting remote changes or uncommitted application edits.
Next: user reviews GitHub main and refreshed Sonar analysis after this handoff.
No version tag, manual build or release requested. Future work remains local
unless separately authorized.
