# A03 portable-profile evidence

Implementation: core `9539895`, CLI `73e06e894b53eeb3f4f3c165516cd6ee708de50d`,
on `feat/a03-portable-profiles`, based on unified-workflow PR #37. Later
documentation changes do not alter the tested production code.

The version 1 allowlist exports only supported selections, requirements, assistant,
explanation preference and portable Graphify relationships. A source plan can
already have been applied or its project moved. Import creates new destination
plans and validates the destination's own state. Existing healthy Graphify
installations retain their destination-specific immutable recipe.

## Validation performed

| Check | Result |
| --- | --- |
| Rebuilt installed-package default suite and clean-wheel packaging, warnings as errors | 1,245 passed / 14 explicit opt-in skips, 58.80 seconds |
| Profile and workflow tests on Python 3.11 | 100 passed, 6.93 seconds |
| Profile and workflow tests on Python 3.14 | 100 passed, 3.73 seconds |
| Real installed CLI pure profile round-trips | Four profiles, 20 successful subprocess commands |
| Ruff lint, product formatting, dependency compatibility, whitespace checks | Passed |

The 63 new tests cover moved-source export, fresh destination IDs/input hashes,
explicit later apply using production adapters with command doubles, destination
ownership reuse, malformed schemas, duplicate/unsupported selections, conflicts,
host/Python incompatibility, private/Windows/traversal/excluded paths, nested
secret-like fields, safe CLI diagnostics and all four example profiles. These
tests do not establish real upstream execution through profiles.

The [sanitized CLI trace](portable-profiles.json) records the installed manager
version, Python/host, command roles, exits and durations. For each mode, the actual
CLI generated a source workflow plan, exported selections, imported them into a
different copied project, dry-ran the destination plan and re-exported it. The
two portable profiles matched. Every destination had a fresh workflow ID and no
transferred receipts. All source/destination file bytes and modification times
remained unchanged; no managed-state directory was created.

This used the built wheel from a separate environment, with commands launched
outside the source checkout and isolated homes. It installed/executed no upstream
tool and used no model provider. Command durations are an execution trace, not a
human-time study or a cost-saving claim. Actual final profile apply/removal and
combination acceptance remain A05 after A04 recommendation/CLI acceptance.

Wheel and source archive builds succeeded. The inherited setuptools
`stackwinnow.data` discovery warning remains assigned to A06; the clean-wheel
resource checks passed. Public source examples are not claims that every runtime
or external dependency is included in the manager distribution.

## Reproduce

Install the current wheel with development dependencies into a separate
environment, then run from the checkout:

~~~sh
/path/to/test-env/bin/python -W error -m pytest --run-packaging -q
/path/to/test-env/bin/python -W error -m pytest tests/test_profile_portability.py tests/test_profile_cli.py tests/test_workflow.py -q
~~~

Follow the [profile guide](../portable-profiles.md) to repeat the CLI round-trip
with copied fixtures and saved plans outside the projects. The four examples are
in [examples/profiles](../../examples/profiles/README.md). Import and dry-run
do not require a real installation or external prerequisite-version execution.
