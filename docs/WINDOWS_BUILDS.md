# Automated Windows builds

[Windows Nuitka build](https://github.com/kraekin/DKR-Workshop/actions/workflows/windows-build.yml)
compiles a self-contained Windows x64 EXE on GitHub's Windows runners. No local
Nuitka compile, ROM, extracted assets, signing certificate or personal token is
needed. The build uses CPython 3.12, MSVC, the PySide6 plugin, the existing icon
and the hashed transitive dependency lock in `pylock.toml`.

## Build the current code without making a release

Open **Actions → Windows Nuitka build → Run workflow**, select `main`, then
**Run workflow**. Download `DKR-Workshop-VERSION-windows-x64` from the completed
run's **Artifacts**. Unzip it and run `DKR Workshop.exe`.

An ordinary commit/push to `main` does not trigger the long compile. Manual
branch builds upload artifacts and do not create releases. Artifacts are kept
for 30 days; release attachments remain available with their release.

## Make a versioned release

1. Update `src/__init__.py` and `pyproject.toml` to the same three-part version,
   update release notes, and commit/push the source.
2. Tag that commit with the matching version and push that tag, for example:

   ```powershell
   git tag v0.27.1
   git push origin v0.27.1
   ```

3. GitHub compiles and checks the EXE, then creates a **draft release** with the
   EXE, a ZIP containing notices, and `SHA256SUMS.txt` attached. Review the draft
   notes and publish when ready. Tag/source version mismatches fail early.

Alternatively, create and publish a GitHub release for a matching version tag
using GitHub's **Releases → Draft a new release** page. A published release
without an EXE triggers the same build and receives attachments when it finishes.
Publishing a draft that already contains the built EXE avoids rebuilding it.
Rerunning a tag build replaces that tag's generated attachments.

## Checks and limits

The workflow checks dependency consistency, source imports, ROM-free camera and
release-version tests, the x64 executable format, and `--help` startup from an
isolated folder with Python/Conda/Qt paths removed. It writes a SHA-256 checksum
and keeps compilation/test diagnostics for 14 days. Only the explicit release
output is uploaded; local research, ROMs, projects and editor exports are excluded.

Hosted checks do not exercise the OpenGL viewport or gameplay. Continue local
native graphics checks and the full parser/export suite with your own ROM before
releasing application changes. The EXE requires a desktop OpenGL 3.3 driver.
The release is unsigned, matching the existing release process.

For a local rebuild, use a fresh 64-bit Windows CPython 3.12 environment:

```powershell
python -m pip install uv==0.11.14
python -m uv pip sync --python python --build-constraints .github/requirements-build.txt pylock.toml
python .github/scripts/build_windows.py
python .github/scripts/verify_windows.py
```

Outputs go to ignored `artifacts/windows-build/` and `artifacts/windows-release/`.
The builder refuses to overwrite nonempty output folders. Existing local
`build/nuitka/` releases and running editors are unaffected.

## Dependency locks

`pylock.toml` is a generated PEP 751 lock for 64-bit Windows / CPython 3.12. It
pins the complete runtime, pytest and Nuitka toolchain, including transitive
packages and artifact SHA-256 hashes. CI installs this file directly. The
bootstrap uv version is pinned too, and isolated source-build dependencies are
constrained by `.github/requirements-build.txt`.

For runtime-only source installation, `requirements.txt` contains matching pinned
runtime versions and artifact hashes; use `pip install --require-hashes
--only-binary=:all: -r requirements.txt`. These wheels avoid implicit source builds.
The full toolchain lock targets the supported release environment; regenerate
and verify an appropriate lock before changing its Python/platform target.

To install the full development/build environment, activate a fresh CPython 3.12
virtual environment and use the two install commands above. `uv pip sync` makes
that environment match the lock, so use a dedicated environment. It is not needed
to launch the downloaded EXE.

To update dependencies deliberately, edit `.github/requirements-build.txt`, keep
runtime choices within `pyproject.toml`, then regenerate both files with uv 0.11.14:

```powershell
uv --no-config pip compile pyproject.toml .github/requirements-build.txt --extra dev --python .venv/Scripts/python.exe --python-version 3.12 --python-platform x86_64-pc-windows-msvc --default-index https://pypi.org/simple --format pylock.toml --output-file pylock.toml
uv --no-config pip compile pyproject.toml --constraint .github/requirements-build.txt --python .venv/Scripts/python.exe --python-version 3.12 --python-platform x86_64-pc-windows-msvc --default-index https://pypi.org/simple --generate-hashes --output-file requirements.txt
```

Review package/version/hash changes, install into a fresh environment, run the
ROM-free build checks and native app checks, and commit both generated files with
their inputs. `tests/test_release_build.py` checks lock/input/runtime consistency.
