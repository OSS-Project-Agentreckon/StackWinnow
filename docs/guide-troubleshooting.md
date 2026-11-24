# Troubleshooting guide

## Python version error

**Symptom:** `stackwinnow: command not found` after install, or an import error
mentioning an unsupported Python version.

**Fix:** The package requires Python >=3.11. Confirm the interpreter used to
create the virtual environment:

```sh
python3 --version
# If older than 3.11, install a newer interpreter and re-create the venv:
python3.11 -m venv .venv
```

## Entry point not found

**Symptom:** `stackwinnow: command not found` even though `pip install` succeeded.

**Fix:** The virtual environment's `bin/` directory is not on `PATH`. Either
activate the environment:

```sh
source .venv/bin/activate
stackwinnow --help
```

or use the full path:

```sh
.venv/bin/stackwinnow --help
```

## Catalog loading errors

**Symptom:** `error: Failed to load catalog` or a JSON validation error.

**Fix:** The catalog file ships with the package. If the error persists after a
clean install (`pip install .`), the wheel may be incomplete. Rebuild and reinstall:

```sh
python -m pip install --force-reinstall .
```

## Tool prerequisite errors during workflow planning

**Symptom:** `stackwinnow workflow plan` reports a missing prerequisite
(e.g., Node not found, Codex version mismatch).

**Fix:** Install the required upstream tool. The required versions are pinned in
[docs/support-matrix.md](support-matrix.md). Use `--platform` and `--assistant`
flags only on commands that expose them. Workflow planning detects the actual
host and derives assistant requirements from selected modes. For Graphify,
supply a reviewed relationship expectation (see [unified-workflow.md](unified-workflow.md)):

```sh
stackwinnow workflow plan ./my-project --tool graphify \
    --expectation relationship.json
```

Planning validates host/selection compatibility; executable prerequisites are
checked during explicit apply. A plan does not prove prerequisites are installed.

## Stale installed-version after editable source change

**Symptom:** `stackwinnow --version` prints an older version after editing
`src/stackwinnow/__init__.py`.

**Fix:** Re-run the editable install to sync distribution metadata:

```sh
python -m pip install -e '.[dev]'
```

## `pip check` fails after tool integration

**Symptom:** `stackwinnow check` reports a dependency conflict.

**Fix:** The integration adapters install pinned upstream packages in isolated
venvs. Conflicts in the manager's own environment are separate from tool
environments. Run:

```sh
python -m pip check
python -m pip install --upgrade '.[dev]'
```

For damaged managed environments, inspect passive status and follow the reviewed
[removal/reinstall procedure](coordinated-removal.md). An attempted plan cannot
be replayed; apply does not overwrite foreign or damaged state automatically.

## Ruff lint errors after editing

**Symptom:** CI or local `ruff check .` reports import order or style errors.

**Fix:**

```sh
ruff check --fix .
ruff format .
```

## Filing an issue

Before opening a GitHub issue, collect:

- Operating system and architecture (`uname -srm` on POSIX, `ver` on Windows)
- Python version (`python --version`)
- Installed manager version (`stackwinnow --version`)
- Full error message (remove credentials and private paths)
- Steps to reproduce

Open an issue at <https://github.com/OSS-Project-Agentreckon/StackWinnow/issues>.
