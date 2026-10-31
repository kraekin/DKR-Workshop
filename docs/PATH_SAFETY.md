# Local file paths and JSON loading

`main.py` accepts `--rom` and `--project` as explicit user file selections, just
like the Open dialogs. Files can live outside the current directory. These
arguments are not advertised as paths within a sandbox, and the application
does not interpret them as shell commands. `--project` reaches `read_json()`;
`--rom` reads binary ROM data rather than JSON.

## Selected files

`read_json()` resolves the selected path and requires a regular file before
reading UTF-8 JSON. It accepts only a JSON object. Project loading then checks
the project format/version, field types, asset identities and editable data.
The project's base ROM may live in another directory, as existing saved projects
require; it must pass the original ROM size and revision checks before use.
An already-selected base ROM can override that stored location.

An explicit top-level file selection is intentionally allowed in any directory.
Rejecting every absolute path or `..` component would break legitimate file
selection without establishing a useful security boundary.

## Extracted-asset references

Filenames inside an extracted manifest have a different contract: they must stay
within the selected asset directory. `DecompAssets` pins its canonical root and
routes extracted JSON reads through `read_json(..., root=...)`. The reader checks
the resolved target against that root before reading. This includes:

- The initial `assets.meta.json`, which previously lacked this check.
- Section manifests and raw-asset metadata.
- Level/name, object/glTF, texture/sprite and special-art JSON metadata.

Resolved targets outside the root are rejected, including parent traversal,
absolute outside paths, sibling directories with a matching name prefix and
symlink/directory-junction escapes. Existing binary/image path containment in
`DecompAssets._path()` remains in place.

Regression tests cover these boundaries, including an actual directory junction
on Windows (directory symlink on other platforms), a simulated file-symlink
target for the initial manifest, and legitimate user-selected files outside the
working directory. The reader is not an OS sandbox against a process concurrently
replacing filesystem entries. External automation, including an LLM tool runner,
must enforce its own allowed file-access policy when choosing CLI arguments.

## Reviewing the reported finding

A trace from an explicitly selected `--project` file to a JSON read does not by
itself demonstrate path traversal. Identify the intended restricted root before
classifying the finding. For manifest-supplied paths, the root check above is
required and is now performed at the JSON reader boundary. No blanket analyzer
suppression is used; this local change does not alter SonarCloud review statuses.

References: [CWE-22](https://cwe.mitre.org/data/definitions/22.html),
[Python path resolution](https://docs.python.org/3/library/pathlib.html#pathlib.Path.resolve).
