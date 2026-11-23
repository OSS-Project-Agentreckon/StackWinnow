"""Distribution packaging checks for B07 (plan step 26).

These tests build the wheel and install it in a clean venv to confirm:
- The CLI entry point is present and runnable.
- ``stackwinnow --version`` exits 0 and prints a version string.
- The catalog data files are accessible from the installed package.
- The installed package does not accidentally import from the developer's checkout.

All tests are skipped by default; run with ``--run-packaging`` to enable.
"""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent


def _build_wheel(dist_dir: Path) -> Path:
    """Build a wheel from SOURCE_ROOT; return the .whl path."""
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        capture_output=True,
        text=True,
        cwd=SOURCE_ROOT,
    )
    assert result.returncode == 0, f"build failed:\n{result.stderr}"
    wheels = list(dist_dir.glob("*.whl"))
    assert wheels, "No wheel produced."
    return max(wheels, key=lambda p: p.stat().st_mtime)


def _create_venv(venv_dir: Path) -> Path:
    """Create a fresh venv; return the Python executable path."""
    venv.create(str(venv_dir), with_pip=True, clear=True)
    python = venv_dir / "bin" / "python"
    if not python.exists():
        python = venv_dir / "Scripts" / "python.exe"
    assert python.exists(), f"No Python in venv at {venv_dir}"
    return python


def _install(python: Path, wheel: Path) -> None:
    result = subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"pip install failed:\n{result.stderr}"


# ---------------------------------------------------------------------------
# Session-scoped fixture: build once, share across tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def installed_venv(tmp_path_factory):
    """Build wheel + install into a clean venv once per test session."""
    tmp = tmp_path_factory.mktemp("dist-check")
    dist_dir = tmp / "dist"
    dist_dir.mkdir()
    venv_dir = tmp / "check-venv"

    wheel = _build_wheel(dist_dir)
    python = _create_venv(venv_dir)
    _install(python, wheel)
    return python


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.packaging
def test_entry_point_script_exists(installed_venv):
    """The ``stackwinnow`` console-scripts entry point must be present in the venv."""
    sw = installed_venv.parent / "stackwinnow"
    assert sw.exists(), (
        f"Entry point 'stackwinnow' not found in {installed_venv.parent}.\n"
        "Check [project.scripts] in pyproject.toml."
    )


@pytest.mark.packaging
def test_version_flag_exits_zero(installed_venv):
    """``stackwinnow --version`` must exit 0 and print a non-empty version string."""
    result = subprocess.run(
        [str(installed_venv), "-m", "stackwinnow", "--version"],
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    assert result.returncode == 0, f"--version exited {result.returncode}:\n{output}"
    assert output, "--version printed nothing"


@pytest.mark.packaging
def test_catalog_data_accessible(installed_venv):
    """The tool catalog must be loadable and non-empty from the installed package.

    Uses ``load_catalog()`` rather than a filename glob so that the check fails
    when catalog.json is absent even if other JSON data files remain.
    """
    result = subprocess.run(
        [
            str(installed_venv),
            "-c",
            (
                "from stackwinnow.catalog import load_catalog; "
                "cat = load_catalog(); "
                "assert cat.tools, 'Catalog has no tools'"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"catalog check failed:\n{result.stderr or result.stdout}"


@pytest.mark.packaging
def test_installed_package_does_not_import_from_checkout(installed_venv):
    """The installed package must not resolve to the developer's source checkout."""
    result = subprocess.run(
        [
            str(installed_venv),
            "-c",
            "import stackwinnow; print(stackwinnow.__file__)",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"import failed:\n{result.stderr}"
    installed_path = Path(result.stdout.strip())
    assert not installed_path.is_relative_to(SOURCE_ROOT), (
        f"Installed package resolves back to source checkout: {installed_path}\n"
        "The clean venv may have inherited PYTHONPATH pointing at the checkout."
    )


@pytest.mark.packaging
def test_version_string_matches_package_metadata(installed_venv):
    """The version printed by --version must match the installed package metadata."""
    result = subprocess.run(
        [str(installed_venv), "-m", "stackwinnow", "--version"],
        capture_output=True,
        text=True,
    )
    version_output = (result.stdout + result.stderr).strip()
    meta_result = subprocess.run(
        [
            str(installed_venv),
            "-c",
            "from importlib.metadata import version; print(version('stackwinnow'))",
        ],
        capture_output=True,
        text=True,
    )
    assert meta_result.returncode == 0, f"metadata query failed:\n{meta_result.stderr}"
    declared_version = meta_result.stdout.strip()
    assert declared_version in version_output, (
        f"--version output {version_output!r} does not contain metadata version {declared_version!r}"
    )
