# Contributing

Discuss a concrete bug or improvement in [GitHub issues](https://github.com/OSS-Project-Agentreckon/StackWinnow/issues).
Include expected behavior, reproducible commands, manager/tool versions and
OS/architecture. Remove credentials, private project paths and proprietary content.

Use Python >=3.11 in a local virtual environment and install development extras:

    python3 -m venv .venv
    .venv/bin/python -m pip install -e '.[dev]'
    .venv/bin/python -m ruff check .
    .venv/bin/python -m ruff format --check .
    .venv/bin/python -m pytest

Real upstream and packaging checks are opt-in; see docs/releasing.md and the
support matrix. Linux unit success does not establish macOS integration support.
Do not put downloaded environments, browser binaries, credentials or personal
planning documents in commits. New adapters need explicit supported behavior,
reviewable changes, ownership/recovery handling and appropriate regression coverage.

Use a small branch and meaningful commits under your own verified Git identity.
Open a PR describing the trigger, resulting behavior, verification actually run,
limitations and linked issue. Preserve genuine authorship; role labels in historical
assignment plans do not authorize commits under someone else's identity. Disclose
material AI assistance and understand any submitted code. Changes are offered under
the repository MIT license; retain upstream attribution and separate license scopes.

Treat contributors respectfully, critique code and avoid harassment or sharing
private information. Report conduct concerns to repository maintainers through
an existing GitHub contact channel; keep sensitive details out of public issues.
Maintainers may moderate disruptive issue/PR participation. No separate governance
body, response-time guarantee or private contact address is implied.
