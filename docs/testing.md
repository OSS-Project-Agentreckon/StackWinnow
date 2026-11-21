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
python -m pytest
```

Dependency installation needs package-index access. Default tests need no provider credentials or installed agent tools. One fixture test serves copied HTML on an ephemeral 127.0.0.1 port: loopback HTTP, not the Internet. CI runs these checks on Ubuntu/Python 3.11 and 3.14. This is a package/testing matrix, not an upstream integration compatibility claim.

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

Installed CLI tests run `check` outside the checkout and exercise structured
results, human output, and exit codes. See [verification](verification.md) for
the public contract and [implementation progress](implementation-progress.md) for
dated local results and the merged runner's remaining limitations.

## Baseline and evidence

Before this harness, main `6616b86` passed 52 tests on macOS/Python 3.14.0. Ruff reported an unused `pytest` import and import-block spacing in runtime tests. Step 3 includes that minimal test-only cleanup so initial CI can pass; production runtime behavior is unchanged.

Final validation and review references are recorded in [implementation-progress.md](implementation-progress.md). Local success does not mean hosted GitHub Actions has run.
