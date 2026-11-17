# Owned JSON configuration edits

Step 6 adds a Python API for previewing and applying edits to one project-local
JSON file. It preserves unrelated values and records exactly which keys changed.
The initial format is strict UTF-8 JSON, matching the existing fixture. The file
operations use POSIX APIs for macOS/Linux; Windows configuration writing is not
implemented. This is a configuration primitive, not an installed tool adapter or
a validated real-assistant connection.

## API and example

`plan_json_edits(project_root, relative_path, *, tool_id, edits)` reads a file
and returns a serializable `ConfigPatch`. It creates no files or directories.
`apply_json_edits(patch)` checks the preview against current state and returns
a `ConfigApplyResult` containing an `OperationResult` and any actual ownership.
The public functions and exceptions are exported by `stackwinnow.configure`;
the data models are in `stackwinnow.contracts`.

This complete example uses a temporary project and a fictional command. The
command is only JSON data and is never executed:

```python
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from stackwinnow.configure import apply_json_edits, plan_json_edits
from stackwinnow.contracts import ConfigPatch, JsonConfigEdit

with TemporaryDirectory(prefix="stackwinnow-config-example-") as directory:
    root = Path(directory)
    settings = root / "assistant-settings.json"
    settings.write_text('{"theme": "keep", "mcpServers": {}}', encoding="utf-8")
    patch = plan_json_edits(
        root,
        settings.name,
        tool_id="example-tool",
        edits=[
            JsonConfigEdit(
                key_path=("mcpServers", "example-tool"),
                value={"command": "fixture-only-do-not-execute", "args": []},
            )
        ],
    )
    # The executor can persist this intent before any mutation.
    serialized_intent = patch.model_dump_json()
    reviewed = ConfigPatch.model_validate_json(serialized_intent)
    outcome = apply_json_edits(reviewed)
    assert outcome.result.status == "succeeded"
    assert outcome.ownership is not None
    assert json.loads(settings.read_text(encoding="utf-8"))["theme"] == "keep"
    print(outcome.result.message)
```

There is no configuration CLI command yet. The later executor/adapter work
will choose the actual client path, obtain the user's reviewed selection, and
persist execution receipts. This API performs no catalog eligibility checks,
installation, assistant discovery, or provider calls.

## Edit rules

- A `key_path` is a nonempty tuple of literal JSON object keys. Slashes, dots,
  spaces, and empty strings inside a key remain literal. Array indexing and
  whole-document replacement are unsupported.
- A missing parent object is created and its path is recorded. An existing
  scalar, array, or null parent is a conflict. File-system parent directories
  must already exist; the caller is responsible for their lifecycle.
- A new value may be inserted. Replacing a different existing value requires
  `replace_existing=True` in the request. Select leaf paths when changing one
  field of an existing server so its other fields remain untouched. A selected
  array or object value is replaced as one unit, not implicitly merged.
- Identical values cause no write and acquire no ownership. Mixed requests
  own only the values that actually changed. Missing keys, JSON null, booleans,
  and numbers remain distinguishable.
- Duplicate or overlapping paths are rejected. One patch concerns one file
  and one tool; multiple files are separate operations for the executor.

An actual write serializes the resulting complete JSON object with two-space
indentation and a final newline. Unrelated keys and values are retained; source
whitespace is normalized. A no-op keeps the original bytes and modification
time. Comments, trailing commas, duplicate keys, a non-object root, malformed
UTF-8, and non-finite numbers are rejected without a write. Decimal literals
that would lose precision through Python's JSON encoder are also rejected.
TOML, YAML, and JSON with comments need separate implementations.

## Preview, ownership, and executor handoff

| Contract / field | Meaning |
| --- | --- |
| `JsonConfigEdit` | Requested key path, JSON value, and explicit replacement option. |
| `ConfigPatch` | Schema-versioned preview: canonical project root, relative file path, tool ID, expected/written file state, changed keys, and created object paths. |
| `ConfigFileState` | File existence, SHA-256 of exact bytes, and POSIX permission bits. An absent file has no digest or mode. |
| `OwnedConfigEdit.original` | `ConfigValue(exists, value)` distinguishes a missing key from a present null. |
| `OwnedConfigEdit.written` | The exact JSON value selected for that key. |
| `ConfigPatch.created_objects` | Ancestor objects created to reach the selected keys; their later contents are not all automatically owned. |
| `ConfigApplyResult.ownership` | The patch if publication occurred; otherwise `None`. |

A preview is intent, not evidence that a write happened. Person B's step-8
executor should persist the reviewed patch as planned state before calling
apply, then record the returned result and ownership. It must retain ownership
even if a post-publication cleanup error returns `failed`. Re-previewing an
already configured value returns `skipped`; preserve earlier receipts instead
of replacing their ownership with that no-op result.

Preview/ownership data can contain the selected original and written values.
Store it as local private state, use environment references instead of literal
credentials where supported, and keep raw values out of routine logs. The API's
conflict diagnostics do not echo configuration contents.

Later removal should compare each current owned value with its recorded write
before restoring/removing it. Only prune created ancestor objects when they
are empty. File-creation evidence alone does not authorize deleting a file
that now contains user changes. Complete removal and durable receipt recovery
are later planned work.

## Apply behavior and limits

Apply validates a detached copy of the patch, checks the expected file bytes,
existence, and mode, and reconstructs the proposed changes. Inconsistent
original values, ownership metadata, or output digests are conflicts. Caller
changes to nested preview data cannot silently change the planned output. This
consistency check does not authenticate an untrusted supplied plan; the caller
must still approve the intended project and changes.

Writes are staged in the same directory with a private temporary file. Its
contents are flushed and fsynced, original permission bits are preserved, and
new files use mode `0600`. Expected state is checked again immediately before
publication. Existing files use atomic replacement. New files use atomic link
creation, which cannot overwrite a destination created by another writer.
Temporary files are removed on normal success and handled pre-publication
failures. An exceptional cleanup failure is reported accurately.

Project-relative paths cannot escape through `..` or absolute paths. A chosen
project root is resolved during planning. Changed symlink ancestors, symlink
file/parent paths, multiply linked files, and special files are rejected.
Directory descriptors keep staging and publication anchored to the opened
parent; its current path is checked before publication.

| Apply status | Configuration outcome |
| --- | --- |
| `succeeded` | Previewed edits were published; ownership is returned. |
| `skipped` | No values changed; no new ownership was acquired. |
| `blocked` | A stale/invalid preview, unsupported file, or conflict prevented publication. |
| `failed`, no ownership | An IO failure prevented publication. |
| `failed`, with ownership | Publication completed, but temporary-file cleanup failed; retain the ownership record. |

Planning raises `ConfigurationConflict` for unsupported contents or conflicting
edits, `ConfigurationError` for IO failures, and Pydantic `ValidationError` for
invalid request contracts. Apply reports these supported failure conditions
through its result.

Atomic publication prevents partially written JSON; it is not a general
compare-and-swap or multi-file transaction. An external writer can still race
an existing file between the final check and replacement. The executor must
serialize StackWinnow operations and coordinate editing; broader concurrency
and recovery belong to later steps. Permission bits are retained, but this
primitive does not copy extended attributes/ACLs or promise crash-durable
directory entries.

## Verification

`tests/test_configuration_patches.py` uses copied fixture projects, including
paths with spaces. It covers preservation, explicit replacement, ownership
round trips, missing/null values, no-op behavior, malformed input, stale plans,
IO failures, publication races, symlinks/special files, and cleanup failures.
All tool command values are inert fixture data. See [testing](testing.md) and
[implementation progress](implementation-progress.md) for recorded checks.
