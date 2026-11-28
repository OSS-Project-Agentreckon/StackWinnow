# Testing StackWinnow

The default suite checks the implemented contracts/CLI/runtime, JSON configuration API, promptfoo adapter and verification with command doubles, receipt handoff, preflight, recommendations, and reusable fixtures. It installs no Graphify, Headroom, promptfoo, Playwright, or browser; calls no model provider; and does not establish assistant integration support.

## Run local checks

Use Python 3.11+ in a project virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m pyright
python -m pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html
```

Dependency installation needs package-index access. Default tests need no provider credentials or installed agent tools. One fixture test serves copied HTML on an ephemeral 127.0.0.1 port: loopback HTTP, not the Internet. CI runs these checks on Ubuntu/Python 3.11 and 3.14. This is a package/testing matrix, not an upstream integration compatibility claim.

## Quality gates

The pull-request and main-branch CI runs on Python 3.11 and 3.14. Each matrix
entry checks dependency compatibility, Ruff, Pyright and the offline fixture
suite. An independent audit job queries known Python vulnerabilities.

| Check | What fails CI | Report |
| --- | --- | --- |
| Pyright | Type errors in every manager module and the audit exporter | CI log |
| pytest-cov | A failing test or less than 80% total line coverage | Terminal, `coverage.xml`, `htmlcov/` |
| pip-audit | Known vulnerabilities, an unauditable package, or lookup failure | Exact-version inventories and JSON reports |

Pyright uses **standard mode**, targeting the minimum Python 3.11 API. Its version
is pinned in the development extra so checker upgrades are reviewed. It checks
argument/return types, `Literal` values, optional member access and annotated
model fields. This catches misuse such as treating an `installation: object`
field as an `InstallPlan`. It is not `mypy --strict`: unannotated legacy helpers
and dynamically loaded adapter dispatch still have weaker typing. Runtime
Pydantic validation and round-trip tests remain necessary. The optional web UI
and test fixtures are outside this initial static-check scope.

Coverage includes **all manager Python modules**, including adapters that are
never imported by a test; it does not exclude installation or verification code
to improve the number. `pyproject.toml` sets `fail_under = 80`, which applies
whenever coverage is requested. Plain `python -m pytest` remains available for a
quick test-only run. The floor is an aggregate regression gate, not a guarantee
that every new adapter has adequate tests. Reviews must still require relevant
adapter tests, and coverage does not prove actual upstream integration.

The coverage table also appears in the GitHub Actions workflow summary.
Coverage XML/HTML and audit inventories/JSON are uploaded even after a failing
check, when those files exist. GitHub Actions retains them for 14 days. A network
error fails the audit instead of reporting a clean result. No advisories are
silently ignored and the audit never applies dependency fixes automatically.

### Run vulnerability checks locally

Use the project virtual environment, rather than a global Python installation:

```sh
python -m pip install --upgrade 'pip>=26.2' 'setuptools>=84.1'
python -m pip install -e ".[dev,audit]"
python -m pip check
python scripts/export_audit_requirements.py --output-dir audit-results
python -m pip_audit -r audit-results/environment.txt --no-deps --disable-pip --strict --format json --output audit-results/environment.json
python -m pip_audit -r audit-results/python-tools.txt --no-deps --disable-pip --strict --format json --output audit-results/python-tools.json
python -m pip_audit -r audit-results/graphify-lock.txt --no-deps --disable-pip --strict --format json --output audit-results/graphify-lock.json
```

These commands need access to PyPI's advisory data, but install no AI tools.
The exporter writes three exact-version inventories:

- **Environment:** every installed distribution, including transitive runtime,
  development and audit dependencies, plus pip and setuptools. Only StackWinnow's
  own unpublished distribution is excluded; its dependencies remain audited.
- **Python tools:** direct pins from every registered library-mode recipe. New
  library adapters enter this inventory through the mode registry. Their
  separately resolved transitive dependencies are not included here.
- **Graphify lock:** every package in the validated, hash-pinned Graphify lock.
  Versions are queried without downloading its macOS wheels onto the CI host.

`--no-deps --disable-pip` performs advisory lookups for those exact inventories
without creating tool environments. The environment inventory is already fully
resolved; the Python tool inventory is intentionally limited to direct pins.
These text inventories are audit inputs, not installable release locks.

`pip-audit` finds **known published advisories**. A clean result does not prove
that a tool is safe, and advisory applicability sometimes needs review. It does
not audit npm tools (promptfoo/Playwright MCP), frontend JavaScript dependencies,
tool binaries, model providers, or the unresolved dependencies of Python library
tools. Audit actual managed Python environments and use `npm audit` on resolved
Node environments when extending installation coverage.

## Reusable fixtures

| Fixture/helper | Purpose |
| --- | --- |
| `test_home` (automatic) | A temporary home for in-process `Path.home()` discovery; the parent shell environment is unchanged. |
| `no_host_tool_discovery` (automatic for local tests) | Runtime executable discovery finds no tools unless explicitly mocked, making tests independent of laptop installations. |
| `subprocess_env` | A separate child-process environment with temporary home/config/cache/temp paths; no inherited provider credentials or `PYTHONPATH`. |
| `project_factory` | Independent copies of synthetic project files and generic MCP-shaped settings. |
| `fixture_project` | One copied project with spaces in its root path, exposed through `root`, `settings`, and `page`. |
| `browser_fixture_url` | Loopback HTTP serving only the copied web directory; server/thread cleanup happens during teardown. |

The settings seed has an unrelated theme and existing server entry. Its command is fictional and must not be executed. This is a generic configuration shape, not a validated real-assistant setup.

The Python fixture has a known edge: `sample_app.greetings.greet` calls `sample_app.names.normalize_name`. Calling `greet("  ada   lovelace ")` yields `Hello, Ada Lovelace!`. Future Graphify checks can use this oracle. The current fixture test checks the Python result and data, not Graphify itself.

The browser page has a **Complete check** button (`complete-check`). A browser click should update `result` to `StackWinnow fixture passed`. This commit checks HTTP delivery and isolation only; browser/JavaScript execution belongs in the later Playwright adapter.

Operate on copies, not `tests/fixtures/` seeds or personal projects. In-process home redirection covers only `Path.home()`; other configuration APIs must receive explicit temporary paths. Child-process tests must pass `env=subprocess_env` and a fixture working directory. These helpers are test-isolation tools, not a security sandbox for untrusted programs.

## Configuration checks

The configuration tests in `tests/test_configuration_patches.py` are local
filesystem tests, not tool integrations. They preview/apply only in copied
projects, exercise preservation and ownership, and inject failures around
staging/publication. POSIX mode, symlink, directory-descriptor, and atomic-link
checks run on macOS/Linux; this module is skipped on Windows, where the
configuration writer is not implemented. Core CLI/catalog/contract tests
remain separate. See [configuration](configuration.md) for the API boundary.

## Real tool and provider checks

Use `integration` for tests needing actual upstream tools/clients. `requires_provider` indicates model-provider access and also implies integration.

| Invocation | Local tests | Tool integration | Provider tests |
| --- | --- | --- | --- |
| `python -m pytest` | Run | Skip with reason | Skip with reason |
| `python -m pytest --run-integration` | Run | Run | Skip with reason |
| `python -m pytest --run-integration --run-provider` | Run | Run | Run |
| `python -m pytest --run-provider` | Usage error | Usage error | Usage error |

`tests/integration/test_promptfoo.py` contains real onboarding and verification
acceptance plus a separately gated OpenAI test. Both require the shared runner
and the declared macOS arm64/Node 24 environment. The runner is now merged.
Missing runtime/platform prerequisites are reported as skips, not successful
verification. The main test runs positive, negative, and repeat onboarding, then
read-only verification and three fresh checks (pass/fail/pass). It verifies one
installation, twelve receipts, six distinct reports, unchanged owned config,
preserved unrelated files, and no model tokens or shared reports.

```sh
python -m pytest tests/integration/test_promptfoo.py --run-integration -rA
# The following additionally permits provider usage and possible charges:
python -m pytest tests/integration/test_promptfoo.py --run-integration --run-provider -rA
```

The hosted test requires explicitly set `STACKWINNOW_PROMPTFOO_MODEL` and
`OPENAI_API_KEY`; neither is given a default credential/model. The regular real
test uses the local fixture provider only. It installs from npm into a temporary
project and needs registry access. See [promptfoo](integrations/promptfoo.md)
for exact artifact, environment, file, and output expectations.

Marker-policy tests also execute a synthetic nested pytest suite to verify
gating; those dummy cases are not upstream evidence. Default CI intentionally
does not opt into registry installations or paid providers.

Flags do not install Node/npm prerequisites or automatically expose credentials.
After explicit opt-in, the hosted evaluation receives only its required API key;
install/version commands never receive it. Adapter command-double tests verify
this routing with synthetic values. They are not evidence of hosted model access.

Strict markers/configuration catch misspelled markers and unknown pytest settings. Behavior changes should include their own relevant tests.

## Verification regression coverage

`tests/test_verification_states.py` covers missing/changed/unowned setup, read-only
preservation, fresh pass/fail/repeat outcomes, missing prerequisites, malformed
receipts, dry-run ownership, operation locks, changes during checks, and invalid
or stale evidence. It verifies that installation/preflight success cannot imply
connection or functionality. Unsupported selected tools prevent overall readiness.
Synthetic hosted cases cover missing opt-in/credentials and distinguish provider
responses from correct assertions. `tests/promptfoo_fakes.py` supplies the shared
offline command double; none of its results are real provider evidence.

Receipt regressions exercise direct evaluation, changes while acquiring the
operation lock, and changes during the CLI version probe. For both local and
synthetic hosted profiles, they assert zero additional evaluation calls when
installation, runtime-state, or configuration ownership is dry-run-only, or
when step IDs are duplicated. Direct invalid requests run no commands; invalid
state acquired under the lock permits only the earlier Node preflight probe.
Positive coverage preserves real ownership after configuration cleanup fails
and keeps dry-run history alongside valid ownership receipts.

Installed CLI tests run `check` outside the checkout and exercise structured
results, human output, and exit codes. See [verification](verification.md) for
the public contract and [implementation progress](implementation-progress.md) for
dated local results and the merged runner's remaining limitations.

## Baseline and evidence

The initial quality-gate validation and the open GPTCache advisory are recorded
in [quality-check evidence](evidence/quality-checks.md).

Before this harness, main `6616b86` passed 52 tests on macOS/Python 3.14.0. Ruff reported an unused `pytest` import and import-block spacing in runtime tests. Step 3 includes that minimal test-only cleanup so initial CI can pass; production runtime behavior is unchanged.

Final validation and review references are recorded in [implementation-progress.md](implementation-progress.md). Local success does not mean hosted GitHub Actions has run.

## Playwright MCP acceptance

The default suite includes TOML ownership/preservation, stale plans, invalid
receipts, runtime blocks and actual-client-event parsing tests. The opt-in
real test requires macOS arm64, Node 24, npm and Codex CLI 0.169.0:

    python -m pytest tests/integration/test_playwright_mcp.py --run-integration -q -W error

It downloads pinned npm/browser artifacts, runs the real Codex/MCP/browser
path with a local scripted provider, verifies a fresh DOM result, checks a
negative fixture and repeats without reinstalling. No API key is used. It
preserves unrelated project settings and runs the client in private temporary
HOME/CODEX_HOME directories. See [integration details](integrations/playwright-mcp.md).
