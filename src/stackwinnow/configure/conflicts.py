"""Read-only reconciliation of a recorded ConfigPatch against the current file.

This module never writes, never follows a symlink, and never adopts a value.
It reuses the hardened read/parse primitives in :mod:`stackwinnow.configure.patches`
and reports collisions as structured, value-free verdicts.
"""

from __future__ import annotations

from collections.abc import Sequence

from stackwinnow.contracts import ConfigPatch, ConfigReconcileReport, JsonConfigEdit


def reconcile_config_patch(
    patch: ConfigPatch,
    *,
    intended_edits: Sequence[JsonConfigEdit] | None = None,
) -> ConfigReconcileReport:
    """Classify a recorded owned patch against the file on disk now.

    Read-only. File-state problems are reported, never raised; only an invalid
    patch contract raises. ``intended_edits``, when supplied, lets the inspector
    flag a pre-existing registration the manager meant to own but never wrote.
    """
    raise NotImplementedError
