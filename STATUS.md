# Hosted uv install fix v0.28.0 — verified (2026-10-31)

Corrected the Windows workflow's locked-install command to pass --system. GitHub
setup-python supplies standalone CPython, not a virtual environment; uv rejected
--python python without the explicit system target. Local setup instructions
continue to use dedicated virtual environments. Lock/packages/app version unchanged.
Documented the hosted/local distinction in docs/WINDOWS_BUILDS.md.

Verified read-only uv dry-run against non-virtual CPython3.12.11 accepts the exact
corrected flags and reaches package planning; no local packages were installed
or removed.8 release/lock checks pass in0.13s; diff checks pass. Ignored JUnit:
artifacts/ci-uv-system-tests.xml. Existing environments, ROMs, builds and editors
preserved; owned pytest fixtures cleaned.

Publish this related CI repair under the user's existing hosted-build/fix
and GitHub authorization, then start a fresh workflow from updated main. Retrying
the old run would retain its old workflow revision. Next: inspect the fresh run's
install step; user downloads/tests when compilation finishes. No need to wait
through the full compile. No tag/release, local EXE build or gameplay ROM output.
