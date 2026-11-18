"""Project-local configuration previews and owned edits."""

from stackwinnow.configure.patches import (
    ConfigurationConflict,
    ConfigurationError,
    apply_json_edits,
    plan_json_edits,
)

__all__ = [
    "ConfigurationConflict",
    "ConfigurationError",
    "apply_json_edits",
    "plan_json_edits",
]
