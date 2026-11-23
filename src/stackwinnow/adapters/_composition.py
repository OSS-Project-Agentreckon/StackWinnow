"""Read-only guards for composing adapters without nesting project locks."""

from collections.abc import Callable


def validate_and_guard(validate: Callable[[], object], guard: Callable[[], None] | None) -> None:
    """Keep leaf validation authoritative, then check the caller's expected state."""
    validate()
    if guard is not None:
        guard()
