# A02 unified workflow validation

The unified flow is tested independently of catalog eligibility and preserves
all narrow adapter APIs. The exact public contracts and support limits are in
[the workflow guide](../unified-workflow.md). All validation uses the contributor's
existing identity; no merge, release or assignment submission is implied.

## Offline and package checks

The workflow regression suite covers pure planning/dry-run/cancellation, exact
supported selection, duplicate/unsupported inputs, forged leaf recipes, stale
source/configuration/executable/receipt state, early prerequisite failures,
partial installation, intentional healthy reapply and replay rejection. It
composes real adapter implementations and filesystem ownership records with
command doubles. Combined Graphify + promptfoo sources and Graphify + Playwright
Codex settings are verified through actual configuration/index adapters.

A separate production Graphify verifier-path test doubles only the client process;
it emits genuine verifier receipts. An additional concurrent narrow verifier is
rejected as an unexpected transition. The owned Codex path uses a passive local
baseline and produces its dynamic client receipt; it does not first emit a local
relationship-verification receipt.

Terminal tests reject changed/deleted selected ownership, unexpected new installer
receipts, runtime damage observed by the final passive checker, and a receipt
change made during that passive inspection. The accepted verifier record is bound
through the final locked journal write. Unchanged configuration no-op receipts are
accepted only for reviewed empty patches; fresh install/function steps still need
success. A real npm version probe also exposed and corrected two config roles
pointing at the same file; preflight now uses distinct isolated paths.

At engineering commit e7959c0 (guard commit fc39092), the final rebuilt installed
package passed **1,182 tests / 14 explicit opt-in skips in 97.80 seconds**, with
warnings treated as errors. This includes the clean-wheel packaging checks.
The focused source suite on Python 3.14 passed **40 tests in 4.83 seconds**.
Ruff lint, product formatting, dependency compatibility and whitespace checks
passed. Both actual installed CLI workflow smokes passed **2 tests in 190.08
seconds**, with seven CLI subprocess commands: promptfoo five commands / 95.02
seconds and Graphify two commands / 94.94 seconds. Each fresh report and functional
evidence file was checked by the actual integration harness.

The standalone real acceptance commands use an installed wheel, not the source
checkout. Package build still reports the inherited setuptools data-directory
warning; resources are included and A06 owns its cleanup. Unrelated untracked
local planning files are excluded from the product formatting check and preserved.

## Actual workflow evidence

The actual smoke harness invokes the installed manager in separate processes,
uses isolated homes and fixture projects, and saves plans/output outside the
project. The promptfoo case exercises inspection, explicit selection, plan,
dry-run, apply with fresh evaluation and passive status. The Graphify case
exercises plan, locked installation, source indexing, owned Codex settings and
an actual Codex relationship query. Both preserve the distinction between fresh
verification and passive status. Neither uses a paid model provider.

The [sanitized command record](unified-workflow.json) contains command kinds,
exit codes, durations, phase statuses and functional evidence hashes without
machine paths or user configuration contents. Tests assert each verification
dimension and, for Graphify, the actual query_relationship tool-call evidence.

These are two actual unified workflow smokes, not the complete final combination,
portable-profile, removal/reinstall or assignment-demo acceptance. The foundation
already has actual narrow lifecycle evidence; A05 must exercise the final unified
and portable-profile combinations after A03/A04. No measured cost benefit is
claimed from these checks.

## Reproduce

Build and install the current wheel into a separate environment with development
dependencies. Put working Node 24 and Codex CLI 0.169.0 on PATH. Graphify requires
CPython 3.11.5–3.11.x on macOS 14+ arm64.

~~~sh
python -m build
/path/to/test-env/bin/python -m pip install 'dist/stackwinnow-0.1.0.dev0-py3-none-any.whl[dev]'
/path/to/test-env/bin/python -W error -m pytest --run-packaging -q
/path/to/test-env/bin/python -W error -m pytest tests/integration/test_workflow_cli.py --run-integration -q
~~~

The final command creates temporary managed runtimes and downloads packages;
retain its temporary evidence if needed for audit. Do not run it on user projects.
