# Hashing safety review — v0.28.0

Reviewed application code, tests and release scripts for Sonar's “Make sure that
hashing data is safe here” security hotspots. Hashes in Workshop identify local
content or detect changes. None hash passwords, generate credentials, authorize
users, authenticate messages or verify digital signatures. A matching project
fingerprint does not establish that a project is trusted: loading still performs
the existing type, size, reference and binary-layout validation.

## Legacy SHA-1 fingerprints

These calls explicitly set `usedforsecurity=False`. Their values are retained for
compatibility, rather than silently changing an existing on-disk format:

| Files | Purpose and review decision |
| --- | --- |
| `src/core/rom.py`, `editing.py`, `runtime_audit.py` | Match the local decompilation's published USA Rev 1 SHA-1 identifier. This selects the supported game revision and rejects accidental modifications; it is not a cryptographic authenticity guarantee. |
| `src/core/project_io.py`, `object_structure.py` | Existing project base-map, asset, entry and template fingerprints detect mismatched local data. Keep serialized SHA-1 field names, values and project versions unchanged. These comparisons do not replace structural validation or authorize file access. |
| `src/core/model_editing.py` | The existing animation exchange format's `mapping_sha1` checks its vertex mapping. The importer also checks format, version, group/frame counts and replacement bounds. |
| `src/core/structure.py` | Stable identifiers for local research-draft source entries. These are not secrets, capability tokens or permissions. |
| Tests containing SHA-1 | Check the published ROM identifier or legacy project/exchange fingerprints. They use the same explicit non-security flag. Unchanged-file snapshots that need no legacy format now use SHA-256. |

SHA-1 is collision-weakened and must not be reused for new security features.
The non-security flag documents intent; it does not make SHA-1 stronger. New
fingerprints should use SHA-256. Any future authentication or signature feature
needs a separate security design rather than these compatibility fingerprints.

## SHA-256 fingerprints and checksums

| Files | Purpose and review decision |
| --- | --- |
| `src/core/editing.py` | In-memory dirty-state/change detection; no authentication decision. |
| `src/core/exporter.py` | Content-based texture output directories and a short safe-filename suffix. The shortened suffix is only a filename discriminator; it does not authenticate content or contain filesystem paths. |
| `src/core/image_batch.py` | Original pixel fingerprints detect stale batch-image packages before staging edits. Asset IDs, dimensions, formats and bounded imports are validated independently. |
| `src/core/runtime_audit.py` | Capture/RDRAM/core fingerprints for deduplication and diagnostic provenance. Captures are parsed with their existing size/format bounds; a digest does not grant trust. |
| `src/core/structure.py`, `track_rebuild.py` | Source/raw/runtime reconstruction fingerprints for diagnostics and stale-data checks. Existing binary validation remains required. |
| `.github/scripts/verify_windows.py` | SHA-256 checksum of the built executable, written to `SHA256SUMS.txt`. This is a download-integrity checksum, not code signing or proof of publisher identity. |
| Tests containing SHA-256 | Compare source files, in-memory exports and expected diagnostic digests. |

No MD5, SHA-1 password hashing, dynamic algorithm selection, secret-derived
filename hashes or hash-based authentication was found in the reviewed code.

## Sonar review notes

There are no blanket `NOSONAR` suppressions or hashing-rule exclusions. Re-run
Sonar after updating the source. Some analyzer versions may still report the
legacy SHA-1 calls despite the explicit flag. For such remaining hotspots, use
the file-specific rationale above when recording a **Safe** review; do not claim
the algorithm itself is cryptographically secure. This local review does not
change hotspot statuses in SonarCloud.

References: [Python hashlib and `usedforsecurity`](https://docs.python.org/3/library/hashlib.html),
[Sonar's non-security hashing discussion](https://community.sonarsource.com/t/s4790-support-usedforsecurity-false-in-python/119453),
[Sonar security-hotspot review](https://docs.sonarsource.com/sonarqube-server/9.8/user-guide/security-hotspots).
