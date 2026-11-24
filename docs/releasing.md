# Preparing manager distributions

Current version: **0.1.0.dev0**, an unreleased development package. Final acceptance,
version/tag selection, publication and faculty submission remain pending. The
release tooling builds only an exact Git commit; local changes are excluded even
when the checkout is dirty. Commit intended changes first and record the chosen SHA.

    python3 -m pip install '.[dev]'
    python3 scripts/build_release.py --source-ref HEAD --dist-dir /tmp/stackwinnow-release
    python3 scripts/build_release.py --source-ref HEAD --dist-dir /tmp/stackwinnow-release --verify-only

Use a new empty output directory. With already installed build dependencies,
--no-isolation avoids fetching an isolated build environment. The script derives
version from committed source, builds sdist then wheel, requires the exact named
pair, checks package identity and committed Python/resource bytes, rejects unexpected
archive contents, and writes SHA256SUMS plus release-manifest.json containing
source SHA, per-artifact hashes and every member's hash. Verification requires the
same source ref. Keep hashes with the artifacts; they provide integrity and source
traceability, not a cryptographic signature or bit-for-bit reproducible build claim.

The allowlisted snapshot excludes unrelated planning docs, private state, downloaded
runtimes and caches. stackwinnow.data is an explicit package. The sdist includes
selected reference notices; the wheel contains original code/data and root notices.
Review [third-party scope](../THIRD_PARTY_NOTICES.md) before changing that boundary.

Optional checks prepared for later (network access and extra time required):

    python3 scripts/build_release.py --source-ref HEAD --dist-dir /tmp/stackwinnow-release --verify-only --install-check

This installs each archive in its own clean venv outside the checkout, checks
pip requirements, module/console entrypoints, catalog, version and all source/data
hashes using isolated imports. scripts/check_distribution.py retains a convenient
build-plus-install entry point; it now builds committed source rather than local
uncommitted edits. CI runs packaging checks automatically. Manual macOS integration
is explicit opt-in and has not been triggered for this milestone.

Before any future public release: finish deferred A05 profile/combined lifecycle
acceptance and dependency refresh, inspect hosted CI, reconcile support claims,
choose/commit the release version, build that exact commit, retain manifest/hashes,
and obtain any publication/submission authorization still required. No workflow
automatically creates tags, GitHub releases or uploads to PyPI.

Earlier release preparation by komalnandiniakam in [PR #28](https://github.com/OSS-Project-Agentreckon/StackWinnow/pull/28)
contributed the build/checksum and release-guide approach. This implementation
replaces installed-version and modification-time artifact selection with strict
committed-source and archive-pair checks; existing attribution/history is retained.
