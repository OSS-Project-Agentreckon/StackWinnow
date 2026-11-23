"""Verify that the distribution wheel installs and runs correctly in a clean environment.

Usage (from the repo root):
    python scripts/check_distribution.py [--dist-dir DIST_DIR]

The script:
  1. Builds a wheel (and sdist) using the ``build`` package.
  2. Installs the wheel into a temporary venv (no index, no deps reuse).
  3. Checks that ``stackwinnow --version`` exits 0 and prints a version string.
  4. Checks that the catalog data file is present in the installed package.
  5. Checks that the declared entry point resolves to the installed package tree.

Exit 0 on success; non-zero (with a summary of failures) otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(cmd: list[str], *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)


def build_wheel(source_root: Path, dist_dir: Path) -> Path:
    """Build a wheel using the ``build`` package; return the path to the .whl file."""
    result = _run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        cwd=source_root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"build failed:\n{result.stderr}")
    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError("No wheel produced by build.")
    return max(wheels, key=lambda p: p.stat().st_mtime)


def build_sdist(source_root: Path, dist_dir: Path) -> Path:
    """Build a source distribution; return the path to the .tar.gz file."""
    result = _run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(dist_dir)],
        cwd=source_root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sdist build failed:\n{result.stderr}")
    sdists = list(dist_dir.glob("*.tar.gz"))
    if not sdists:
        raise RuntimeError("No sdist produced by build.")
    return max(sdists, key=lambda p: p.stat().st_mtime)


def create_venv(venv_dir: Path) -> Path:
    """Create a fresh venv; return path to the Python executable."""
    venv.create(str(venv_dir), with_pip=True, clear=True)
    python = venv_dir / "bin" / "python"
    if not python.exists():
        python = venv_dir / "Scripts" / "python.exe"
    if not python.exists():
        raise RuntimeError(f"Cannot find Python executable in venv at {venv_dir}")
    return python


def install_wheel(python: Path, wheel: Path) -> None:
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip install failed:\n{result.stderr}")


def check_version(python: Path) -> str:
    result = subprocess.run(
        [str(python), "-m", "stackwinnow", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Also try via entry-point script
        sw = python.parent / "stackwinnow"
        if sw.exists():
            result = subprocess.run(
                [str(sw), "--version"],
                capture_output=True,
                text=True,
            )
    if result.returncode != 0:
        raise RuntimeError(f"stackwinnow --version failed:\n{result.stderr or result.stdout}")
    version_output = (result.stdout + result.stderr).strip()
    if not version_output:
        raise RuntimeError("stackwinnow --version printed nothing.")
    return version_output


def check_catalog(python: Path) -> None:
    """Confirm catalog data is accessible from the installed package."""
    result = subprocess.run(
        [
            str(python),
            "-c",
            (
                "from importlib.resources import files; "
                "data = files('stackwinnow').joinpath('data'); "
                "names = [r.name for r in data.iterdir()]; "
                "assert any(n.endswith('.json') for n in names), "
                f"f'No JSON in catalog data: {{names}}'"
            ),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"catalog data check failed:\n{result.stderr or result.stdout}")


def check_entry_point(python: Path) -> None:
    """Confirm the console_scripts entry point resolves inside the venv."""
    sw = python.parent / "stackwinnow"
    if not sw.exists():
        raise RuntimeError(
            f"Entry point 'stackwinnow' not found in {python.parent}.\n"
            "Check [project.scripts] in pyproject.toml."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        default=None,
        help="Output directory for built artifacts (default: a temporary directory).",
    )
    args = parser.parse_args(argv)

    source_root = Path(__file__).resolve().parent.parent
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="stackwinnow-dist-check-") as tmpdir:
        tmp = Path(tmpdir)
        dist_dir = Path(args.dist_dir) if args.dist_dir else tmp / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        venv_dir = tmp / "check-venv"

        print("Building wheel…")
        try:
            wheel = build_wheel(source_root, dist_dir)
            print(f"  wheel: {wheel.name}  sha256:{_sha256(wheel)[:16]}…")
        except RuntimeError as exc:
            failures.append(f"wheel build: {exc}")
            print(f"FAIL  {failures[-1]}")
            # Cannot continue without a wheel.
            _report(failures)
            return 1

        print("Building sdist…")
        try:
            sdist = build_sdist(source_root, dist_dir)
            print(f"  sdist: {sdist.name}  sha256:{_sha256(sdist)[:16]}…")
        except RuntimeError as exc:
            failures.append(f"sdist build: {exc}")
            print(f"FAIL  {failures[-1]}")

        print("Creating clean venv…")
        try:
            python = create_venv(venv_dir)
        except RuntimeError as exc:
            failures.append(f"venv creation: {exc}")
            print(f"FAIL  {failures[-1]}")
            _report(failures)
            return 1

        print("Installing wheel into clean venv…")
        try:
            install_wheel(python, wheel)
        except RuntimeError as exc:
            failures.append(f"wheel install: {exc}")
            print(f"FAIL  {failures[-1]}")
            _report(failures)
            return 1

        print("Checking entry point…")
        try:
            check_entry_point(python)
            print("  OK")
        except RuntimeError as exc:
            failures.append(f"entry point: {exc}")
            print(f"FAIL  {failures[-1]}")

        print("Checking --version…")
        try:
            version = check_version(python)
            print(f"  OK  ({version})")
        except RuntimeError as exc:
            failures.append(f"--version: {exc}")
            print(f"FAIL  {failures[-1]}")

        print("Checking catalog data…")
        try:
            check_catalog(python)
            print("  OK")
        except RuntimeError as exc:
            failures.append(f"catalog data: {exc}")
            print(f"FAIL  {failures[-1]}")

    return _report(failures)


def _report(failures: list[str]) -> int:
    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll distribution checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
