"""Project-local configuration previews and owned edits."""

from stackwinnow.configure.conflicts import reconcile_config_patch
from stackwinnow.configure.patches import (
    ConfigurationConflict,
    ConfigurationError,
    apply_json_edits,
    plan_json_edits,
)
from stackwinnow.configure.restore import (
    ConfigRestorePlan,
    ConfigRestoreResult,
    RuntimeReferenceReport,
    apply_config_restore,
    plan_config_restore,
    referenced_runtime_paths,
)
from stackwinnow.contracts import (
    ConfigReconcileReport,
    ConflictKind,
    FileState,
    KeyConflict,
)

__all__ = [
    "ConfigReconcileReport",
    "ConfigRestorePlan",
    "ConfigRestoreResult",
    "ConflictKind",
    "ConfigurationConflict",
    "ConfigurationError",
    "FileState",
    "KeyConflict",
    "RuntimeReferenceReport",
    "apply_config_restore",
    "apply_json_edits",
    "plan_json_edits",
    "plan_config_restore",
    "reconcile_config_patch",
    "referenced_runtime_paths",
]
