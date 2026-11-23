# B01/B02 local validation — 23 November 2026

Base main: 8466c8c9fad0207a825fd5599df8e4d18c4e0859.
Working branch: fix/b-foundation-baseline-removal.
Validation below was performed on the working implementation before its
publication. Baseline cleanup is commit 9c80b11; removal classification and
this evidence are the following commit on the same branch. No hosted CI
result is claimed here.

## What changed

- Closed Headroom's saved-plan file deterministically with UTF-8 decoding.
- Removed unused imports and applied repository lint/format rules.
- Rejected traversal and unsafe aliases in removal candidates; unresolved
  ownership blocks planning with InstallerError.
- Preserved declared graph/result/cache locations and their candidate ancestors,
  including outputs without a separate evidence entry or child receipt.
- Kept installation manifests from permanently retaining an owned runtime.
- Preserved overlapping retained/failed ownership and parents of retained aliases.

## Environment observed

| Component | Version |
| --- | --- |
| Host | macOS 27.2.1, arm64 |
| Python | CPython 3.11.14 |
| Node | v22.18.0 |
| Codex CLI | 0.171.0 |
| pytest in rebuilt-package validation | 9.2.0 |
| Ruff | 0.17.6 |
| Pydantic | 2.14.4 |

These are the local validation versions, not evidence that all real adapters
support this combination. The existing platform/client support restrictions
remain; this slice makes no new real-client or provider acceptance claim.

## Checks performed

The 16 initially added removal/install cases gave 12 failures and 4 passes
before the classifier fix. A further retained-alias/parent regression was
added during review. The final focused selection covering removal, Graphify
installation and Headroom CLI passed 86 tests with warnings treated as errors.

Copied the current tracked working files into a temporary source snapshot,
built a wheel and installed it into a separate temporary environment. Ran
python -m pytest -q -W error --tb=short against that snapshot and installed
package, with localhost access for the HTTP fixtures:

- 993 passed, 12 skipped, no failures or errors.
- Seven real integration/provider cases skipped; five opt-in distribution
  cases skipped. Skips are not counted as integration passes.
- Ruff check and format --check passed for src, tests and scripts.
- git diff --check and pip check passed.
- Installed --version and --help exited 0; an unknown command exited 2.
- Installed Headroom plan/JSON -> saved plan -> apply --dry-run/JSON passed
  and left the selected project empty.

The Graphify installation test uses the existing injected command fixture;
it verifies ownership/classification, not a fresh upstream package install.
Removal remains read-only. Configuration-reference reconciliation, actual
deletion, Graphify freshness/client execution and shared verifiers are still
separate B03–B08 work in the central checkpoint.
