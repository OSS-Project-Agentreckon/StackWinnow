"""Export exact versions for vulnerability lookup without installing AI tools."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from importlib import import_module
from importlib.metadata import Distribution, distributions
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from stackwinnow.adapters.graphify_plan import load_graphify_lock
from stackwinnow.supported import supported_modes


def pinned_requirements(packages: Iterable[tuple[str, str]]) -> str:
    """Reject conflicting versions instead of silently losing an audit target."""
    versions: dict[str, str] = {}
    for name, version in packages:
        requirement = Requirement(f"{name}=={version}")
        key = canonicalize_name(requirement.name)
        if key in versions and versions[key] != version:
            raise ValueError(f"Conflicting installed versions for {key}.")
        versions[key] = version
    return "".join(f"{name}=={version}\n" for name, version in sorted(versions.items()))


def environment_requirements(installed: Iterable[Distribution] | None = None) -> str:
    """Include runtime, development, audit, pip and build dependencies."""
    packages = []
    for distribution in distributions() if installed is None else installed:
        name = distribution.metadata["Name"]
        if not name:
            raise ValueError("Installed distribution is missing its package name.")
        # The unpublished local project has no upstream PyPI advisory record.
        # Its dependencies remain in the inventory and are all audited.
        if canonicalize_name(name) != "stackwinnow":
            packages.append((name, distribution.version))
    return pinned_requirements(packages)


def tool_requirements() -> str:
    """Audit direct Python library pins; this does not resolve their dependencies."""
    packages = []
    for mode in supported_modes():
        if mode.mode != "library":
            continue
        adapter = import_module("stackwinnow.adapters." + mode.tool_id.replace("-", "_"))
        name = adapter._PACKAGE_NAME
        if not isinstance(name, str) or adapter.VERSION != mode.version:
            raise ValueError(f"The {mode.tool_id} audit target differs from its recipe.")
        packages.append((name, mode.version))
    return pinned_requirements(packages)


def export_requirements(output_dir: Path) -> dict[str, int]:
    lock = load_graphify_lock()
    inventories = {
        "environment": environment_requirements(),
        "python-tools": tool_requirements(),
        "graphify-lock": pinned_requirements((p.name, p.version) for p in lock.packages),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for scope, requirements in inventories.items():
        (output_dir / f"{scope}.txt").write_text(requirements, encoding="utf-8")
    return {scope: len(requirements.splitlines()) for scope, requirements in inventories.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for scope, count in export_requirements(args.output_dir).items():
        print(f"{scope}: {count} exact package versions")


if __name__ == "__main__":
    main()
