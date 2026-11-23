# Managed Graphify indexing evidence — 23 November 2026

Branch: feat/a01-graphify-freshness, based on configuration PR #31 at 8cc3972.
Implementation and validation were AI-assisted; contributor identity is unchanged.

- Focused Graphify and shared-verification suite: 151 passed with warnings as errors.
- Default suite against a wheel rebuilt and reinstalled from a temporary snapshot:
  1042 passed, 12 opt-in checks skipped, 36.85 seconds, warnings as errors.
- Ruff lint and formatting, dependency compatibility and diff checks passed.
- Real pinned managed Graphify lifecycle fixture: 1 passed, 76.66 seconds,
  CPython 3.11.14 on macOS arm64. It downloaded and installed the reviewed locked
  wheels in a temporary project, extracted copied source inputs, queried the
  expected relationship with upstream Graphify, reused unchanged evidence,
  reused the installed runtime, performed a fresh shared functional check,
  rejected stale source evidence, and deliberately reindexed revised sources.
  The same test checked a changed runtime and controlled download failure.

Commands used for the real fixture and default suite:

    PYTHONPATH=src /private/tmp/stackwinnow-review-build-env/bin/python -m pytest -q tests/integration/test_graphify_install.py --run-integration -W error --tb=short
    /private/tmp/stackwinnow-review-build-env/bin/python -m pytest -q -W error --tb=short

The second command ran in an isolated source/test snapshot after building and
installing its wheel; it did not use PYTHONPATH. CLI tests therefore used the
rebuilt installed distribution. Unrelated local docs/superpowers files were
excluded from the snapshot and commits.

No model/provider was called. The managed commands used code-only extraction
and the pinned upstream path query. No Codex connection, complete lifecycle
removal, hosted CI result, merge or full B-to-A handoff is established here.
The earlier standalone recursive fixture remains separate evidence; this real
managed case exercises the cross-file relationship.
