# CLI JSON path finding v0.28.0 — complete (2026-10-31)

Traced main.py --project through project_io to rom.read_json. Explicit CLI/UI
file selections may intentionally live anywhere; no cwd sandbox was promised.
--rom reads binary ROM data, not JSON. Do not reject legitimate cross-directory
project/base-ROM locations or claim this CLI trace alone proves traversal.

Added resolved-root containment to read_json for extracted references and routed
all extracted JSON readers through DecompAssets.read_json. Initial assets.meta.json
now receives the check too. Canonical targets must remain in the selected root;
reject outside absolute/parent/sibling/link targets before reading. Pin canonical
roots even on direct DecompAssets construction. Selected JSON must be a regular
file; resolution loops become normal AssetError load failures. No binary/project
format changes. README links docs/PATH_SAFETY.md with exact boundaries, limitations
and Sonar review rationale; release notes updated. No blanket suppressions.

Verified98 path/ROM/project tests pass in7.04s and434 affected-loader regressions
pass in29.03s (zero failures/errors/skips). Tests include an actual Windows junction
and a simulated canonical file-link escape for the initial manifest. Native CLI
startup opens a temporary project and original ROM in different directories at
level5, RTX4060 GL3.3/4xMSAA; original ROM unchanged and no ROM export.146 Python
files parse; diff checks pass. Ignored evidence: artifacts/json-*-tests.xml,
json-loader-regressions.xml and verify_json_cli.py. Owned fixtures cleaned.

Next: user re-scans/reviews Sonar using the path-safety notes. Work remains local;
no push, release, rebuild, emulator or persistent gameplay/review ROM. Preserve
user files and existing editor processes. Prior checkpoint e5c6175 retained.
