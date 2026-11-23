# Headroom library integration

StackWinnow installs `headroom-ai==0.44.0` (Apache-2.0) in a project-local
Python environment. The supported request path is local Python library
compression on macOS arm64. It does not configure an assistant proxy or send
requests to a model provider.

Upstream: <https://github.com/headroomlabs-ai/headroom>

## Install and verify

```sh
stackwinnow headroom plan /path/to/project --json > /tmp/headroom-plan.json
stackwinnow headroom apply /tmp/headroom-plan.json --dry-run
stackwinnow headroom apply /tmp/headroom-plan.json
stackwinnow check /path/to/project --tool headroom
stackwinnow check /path/to/project --tool headroom --run-functional --json
```

Planning and dry-run do not download packages, start subprocesses, or create
project files. Review and apply the serialized plan. To run the complete
adapter again, create a new plan: a previously attempted plan cannot be replayed.
A current owned environment is reused without reinstalling it.

The shared passive check validates current installation receipts, import health
record and the entire immutable runtime inventory. It reports installed and
configured separately. Connected is `not_applicable` for standalone library
mode. Functionality is `not_run` until explicitly requested; old successful
reports do not establish current readiness.

`--run-functional` runs fresh compression under the shared project lock,
revalidates the runtime afterward, and saves a unique report bound to the run,
installation digest, fixture digest, model target and tokenizer. It never
installs missing packages. `--scenario fail` runs the same fresh command, then
deliberately rejects its result as a deterministic negative validation control;
it does not simulate an upstream failure or claim token savings.

## What the fixture proves

The reviewed call is:

```python
from headroom import compress

result = compress(messages, model="gpt-4o", kompress_model="disabled")
```

`gpt-4o` selects the `o200k_base` tokenizer; it does not make a GPT API request.
The fixture includes a system instruction and a user message with repetitive
passing tests and a critical timeout failure. Success requires the exact system
instruction and full timeout/expected/actual failure text to survive. Reports
include actual upstream `tokens_before`, `tokens_after`, `tokens_saved` and
message counts. Boolean, string, negative, inconsistent or stale measurements
are rejected. Zero savings is valid. This narrow fixture demonstrates execution
and preservation of required content; it does not establish cost reduction for
arbitrary projects or provider bills.

## Isolation and ownership

Python 3.11+ with `venv`/`ensurepip` is required. First installation needs access
to PyPI; the first tokenizer use may download its vocabulary from Azure CDN.
The adapter supplies private HOME, XDG and temporary directories, an explicit
PyPI index and disabled user pip configuration. Python runs in isolated mode;
health and compression also disable bytecode writes with `-B`, so imports do
not alter the runtime inventory. Kompress model downloading is disabled.

| Managed path | Purpose and removal policy |
| --- | --- |
| `.stackwinnow/envs/headroom/python/` | Copied interpreter, packages and immutable inventory; eligible for runtime removal only with valid exclusive ownership |
| `.stackwinnow/headroom/cache/tiktoken/` | Mutable tokenizer vocabulary; retained project data |
| `.stackwinnow/headroom/reports/` | Fresh success/failure evidence; retained project data |
| `.stackwinnow/headroom/home/`, `tmp/` | Private runtime state beneath the retained Headroom data root |
| `.stackwinnow/receipts.json` | Shared operation journal; retained |
| `.stackwinnow/operation.lock` | Shared lock during execution; released afterward |

Every newly created root is journaled immediately. Failed or interrupted installs
remain available for inspection. Existing unowned roots, missing runtime files,
unsafe aliases, changed inventory and old metadata-only installations block
reuse; the adapter does not silently adopt or overwrite them. The removal
planner retains the whole `.stackwinnow/headroom` data root, including a cache
that has no report yet. Coordinated deletion/reinstallation after removal is a
separate lifecycle milestone.

The upstream version is pinned, but transitive dependencies currently resolve
at installation time. The manifest records the actual installed versions and
file hashes. This is current-environment validation, not a claim of a locked
cross-machine dependency resolution. Dependency license closure belongs to the
release audit.

## Acceptance evidence

Run the opt-in real check with:

```sh
python -m pytest tests/integration/test_headroom.py --run-integration -q
```

It exercises missing installation, dry-run, installation, passive inspection,
fresh shared verification, negative control, repeat setup and replay rejection
while preserving a user file. See [Headroom evidence](../evidence/headroom-library.md)
for the measured environment and results. Offline tests exercise state
corruption, command failures, unsafe cache aliases, locking and strict reports;
they do not substitute for the real upstream acceptance run.
