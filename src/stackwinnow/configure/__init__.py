"""Project-local configuration previews and owned edits."""

from stackwinnow.configure.conflicts import reconcile_config_patch
from stackwinnow.configure.patches import (
    ConfigurationConflict,
    ConfigurationError,
    apply_json_edits,
    plan_json_edits,
)
from stackwinnow.contracts import (
    ConfigReconcileReport,
    ConflictKind,
    FileState,
    KeyConflict,
)

__all__ = [
    "ConfigReconcileReport",
    "ConflictKind",
    "ConfigurationConflict",
    "ConfigurationError",
    "FileState",
    "KeyConflict",
    "apply_json_edits",
    "plan_json_edits",
    "reconcile_config_patch",
]
