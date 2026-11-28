# Quality gate validation — 24 November 2026

Local validation used macOS arm64 and CPython 3.11.15 in a disposable environment.
These results describe the modified working copy based on `b44cbf1`; hosted
GitHub Actions has not been run for these changes.

| Gate | Local result | Scope |
| --- | --- | --- |
| Pyright 1.1.414 | 0 errors, 0 warnings | Standard mode, all manager modules and the audit exporter; Python 3.11 target |
| Ruff lint / format | Passed | Repository Python files |
| pytest with coverage | 1,364 passed, 20 skipped; 82.35% line coverage | Default local suite; 80% coverage floor passed |
| pip check | Passed | Resolved validation environment |
| Distribution build | Passed | Source archive and wheel; source archive includes the audit exporter and its tests |
| Environment audit | Passed: 44 packages, no known advisories | Runtime, development, audit and packaging tools; local StackWinnow distribution excluded |
| Python tool audit | Failed: GPTCache 0.1.44 has one distinct advisory | 20 registered library-mode package pins; direct dependencies only |
| Graphify lock audit | Passed: 31 packages, no known advisories | Every package in the validated Graphify lock |

Skipped tests require explicit upstream integration, provider or packaging
opt-ins; they are not successful real-tool verification. The CI configuration
runs the checks on Ubuntu with Python 3.11 and 3.14, which still needs hosted
validation. Coverage is an aggregate line metric, not per-adapter proof.

## Open security finding

`pip-audit` reports GPTCache `0.1.44` as affected by
**[CVE-2026-10812](https://nvd.nist.gov/vuln/detail/CVE-2026-10812)** /
[GHSA-xfqj-4cr9-9gr5](https://github.com/advisories/GHSA-xfqj-4cr9-9gr5)
(`PYSEC-2026-3468`). The advisory concerns a weak hash in the image cache-key
handler; the published description says exploitation requires local access and
has high complexity. The queried advisory data lists **no fixed release**.

The service returned the same advisory twice; this is one distinct advisory,
not two different flaws. No ignore rule or automatic dependency change was
introduced. The tool audit intentionally returns a failing exit status while
this affected recipe remains registered. A clean gate requires replacing or
retiring the affected recipe, or reviewing a newly published fixed version.
The audit is a CI gate; it does not disable installations in existing releases.

The validation environment used pip `26.3` and setuptools `84.2.1`. CI upgrades
pip to at least `26.2` and setuptools to at least `84.1`, and the build backend
requires setuptools `>=84.1`, to avoid the packaging-tool advisories detected
in the original temporary environment.

See [testing and audit commands](../testing.md#quality-gates) for reproduction,
report artifacts, failure handling and coverage limits. A successful audit
means no known advisory was returned for the exact queried package versions;
it does not establish safety or cover npm packages and unresolved Python tool
dependencies.
