# Configuration lifecycle interfaces

This A01 foundation repair provides configuration cleanup primitives for the
later coordinated removal executor. It does not delete runtimes, write receipts,
or establish that Graphify or Headroom is connected or functional.

## Supported reconciliation

reconcile_config_patch reads JSON configuration and project-scoped Codex TOML
at .codex/config.toml. It reports clean, user-modified, user-removed and foreign
keys without including configuration values in diagnostics. An unrelated file
edit makes the whole-file state stale while individual owned keys can remain
clean. Malformed, linked, hard-linked, oversized or otherwise unsafe files are
unreadable and must be preserved. Other TOML paths remain unsupported.

## Preview and restoration

The public functions and models are exported by stackwinnow.configure:

| API | Meaning |
| --- | --- |
| plan_config_restore(ownership) | Read-only ConfigRestorePlan with current file snapshot, keys to restore, preserved key verdicts and a blocked flag |
| apply_config_restore(plan) | Revalidates the complete preview and atomically publishes only the selected restoration; returns ConfigRestoreResult |
| referenced_runtime_paths(ownership, runtime_paths) | Reads live configuration, including foreign registrations, and returns RuntimeReferenceReport with conservatively retained managed paths |

Pass ConfigPatch ownership from a successful or published-write receipt, never
an unexecuted preview just because its values match the current file. A patch
with no owned edits does not authorize removing a pre-existing registration.
The restoration plan carries the original ownership evidence. Preview data
can contain sensitive original values, just like the existing apply plan;
do not publish it or log the entire plan.

For JSON, only keys still equal to the manager-written values are restored to
their recorded originals or removed if originally absent. User modifications,
user removals and foreign keys survive. Only now-empty manager-created parent
objects are pruned. JSON is rendered using the existing strict formatting
rules; comments are unsupported by the JSON writer.

For Codex TOML, cleanup removes only the exact canonical server stanza appended
by the Playwright/Graphify writer. It verifies the resulting full document's
meaning and preserves every unrelated byte and comment. Modified tables are
retained. A semantically unchanged table that was reformatted or gained inserted
comments is blocked for manual inspection rather than reconstructed. Pre-existing
TOML replacements and arbitrary TOML editing are outside this supported subset.
Sequential cleanup of both managed tables works even when their shared parent
was originally implicit.

Empty files remain on disk, preserving file existence and permissions. Missing
files stay missing. Re-preview before repeating cleanup; an old saved plan is
rejected if the file's content, existence or mode changed.

## Lock and durable ownership contract

apply_config_restore follows the existing low-level configuration writer
convention: **the caller owns the project lock and durable journal**. It does
not acquire another lock internally. A coordinated lifecycle operation must:

1. Acquire the shared project_lock and load authoritative receipts.
2. Match each supplied ownership patch against those receipts, re-preview and
   persist the complete restore intent before changing configuration.
3. Call apply_config_restore while holding that same lock.
4. Persist the returned outcome. Its plan always retains the original ownership;
   published states whether a write occurred, even if temporary-file cleanup
   failed. Only released_keys may be removed from active ownership. Keep the
   intent and preserved ownership available for partial-failure recovery.
   restored_file carries the exact published digest/mode (or known missing
   state), allowing later removal attempts to distinguish a manager-restored
   file from a subsequent user edit.
5. Re-read references from every relevant known configuration file, including
   files recorded in configuration intents that skipped matching foreign entries.
6. Revalidate runtime ownership and the proposed deletion separately before
   releasing any runtime. Configuration cleanup alone never authorizes deletion.

The optional restorations argument projects the reviewed clean changes in
memory for removal previews. It grants no ownership or deletion permission.
Before deleting a runtime, call again without that argument to inspect the
actual file after durably recorded restoration.

RuntimeReferenceReport retains all supplied candidates when a configuration
file is unreadable or unsupported. Missing files retain none. Readable files
are scanned for absolute/project-relative managed paths, paths embedded in
arguments, and direct absolute or dot-relative filesystem aliases. Matches may
be conservative (for example a path mentioned in user text). This is not shell
evaluation, executable discovery, or a complete dependency graph; it must be
combined with adapter resource declarations and retained receipt ownership.

The restore writer holds directory descriptors, refuses symlinks/hard links,
uses bounded reads, rechecks file and parent identity, and atomically replaces
the file. StackWinnow's lock serializes cooperating operations; it cannot stop
an external editor from writing concurrently after the final filesystem check.

## Validation

Focused configuration coverage: 142 tests passed with warnings treated as errors.
Coverage includes JSON null restoration, partial cleanup, stale plans, parent
replacement, user comments, foreign matching entries, TOML dates, both Codex
tables, retained runtime aliases and failures before/after publication.
Full rebuilt-package validation is recorded in implementation-progress.md.
