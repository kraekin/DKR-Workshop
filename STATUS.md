# Smoke validation and hashing review v0.28.0 — complete (2026-10-31)

Replaced all195 smoke asserts with explicit SmokeCheckError checks. Every original
condition is AST-verified unchanged; failure logging/screenshot, exit1 and cleanup
remain. Checks and side effects run under -O/-OO. Removed the standalone bush
experiment module, dedicated tests/guide and active command references. Retained
historical source/runtime evidence and the read-only runtime audit. Retired module
is no longer importable; documentation has no stale command links.

Reviewed all hashes:33 legacy SHA1 calls explicitly use usedforsecurity=False for
ROM/project/animation/source identifiers. Existing fingerprint bytes, field names
and schemas remain compatible; seven core modules differ only by this intent flag.
Non-legacy test file snapshots now use SHA256. Existing SHA256 fingerprints and
release checksums retained. No password/authentication/secret hashing found.
README links docs/HASHING_SAFETY.md with purpose-specific Sonar review notes;
no blanket suppressions or remote hotspot-status changes. Release notes updated.

Verified1,906 full-suite tests pass in637.23s, zero failures/errors/skips;60 focused
checks pass in20.18s. Native optimized smoke passes RTX4060 GL3.3,62.7FPS/4xMSAA
without a ROM.145 Python files parse; source, metadata and diff checks pass.
Ignored evidence: artifacts/sonar-*-tests.xml and sonar-smoke-native.png. Owned
temporary fixtures cleaned; user files, ROMs, builds and editor processes preserved.

Next: user reviews local v0.28.0 changes, pushes when ready and re-runs Sonar;
use the hashing review for any remaining Safe hotspot decisions. No push, release,
standalone rebuild, emulator or persistent gameplay/review ROM generated.
