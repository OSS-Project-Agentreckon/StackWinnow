"""Verify that the distribution wheel installs and runs correctly in a clean environment.

Usage (from the repo root):
    python scripts/check_distribution.py [--dist-dir DIST_DIR]
    python scripts/check_distribution.py --verify-only DIST_DIR

Build mode (default): builds a fresh wheel + sdist from source, installs into a
clean venv with declared dependencies, and runs smoke checks.

Verify-only mode (--verify-only): takes an existing dist directory that already
contains a wheel, sdist, and sha256sums.txt (produced by build_release.py).
Checks the recorded hashes, then installs the existing wheel and runs the same
smoke checks. Use this after ``build_release.py`` to validate release artifacts
without rebuilding or overwriting them.

Exit 0 on success; non-zero (with a summary of failures) otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
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
    """Install the wheel and its declared runtime dependencies from PyPI."""
    result = subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip install failed:\n{result.stderr}")
    # Confirm all declared requirements resolve correctly.
    check = subprocess.run(
        [str(python), "-m", "pip", "check"],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        raise RuntimeError(f"pip check failed after install:\n{check.stdout}{check.stderr}")


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
    """Load and validate the tool catalog from the installed package.

    Exercises ``stackwinnow.catalog.load_catalog`` directly so that a missing
    or empty catalog.json causes a failure, even when other JSON data files
    (e.g. graphify-lock.json) are present.
    """
    result = subprocess.run(
        [
            str(python),
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
    if result.returncode != 0:
        raise RuntimeError(f"catalog check failed:\n{result.stderr or result.stdout}")


def check_entry_point(python: Path) -> None:
    """Confirm the console_scripts entry point resolves inside the venv."""
    sw = python.parent / "stackwinnow"
    if not sw.exists():
        raise RuntimeError(
            f"Entry point 'stackwinnow' not found in {python.parent}.\n"
            "Check [project.scripts] in pyproject.toml."
        )


def verify_existing_checksums(dist_dir: Path) -> Path:
    """Verify existing artifacts against sha256sums.txt; return the wheel path.

    Reads sha256sums.txt from dist_dir, confirms each listed artifact exists and
    matches its recorded digest, then returns the wheel path for further checks.
    """
    checksums_file = dist_dir / "sha256sums.txt"
    if not checksums_file.exists():
        raise RuntimeError(f"sha256sums.txt not found in {dist_dir}")
    wheel: Path | None = None
    for line in checksums_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise RuntimeError(f"Unexpected sha256sums.txt line: {line!r}")
        expected_digest, name = parts
        artifact = dist_dir / name
        if not artifact.exists():
            raise RuntimeError(f"Artifact {name!r} listed in sha256sums.txt is missing.")
        actual = _sha256(artifact)
        if actual != expected_digest:
            raise RuntimeError(
                f"Checksum mismatch for {name!r}:\n"
                f"  expected: {expected_digest}\n"
                f"  actual:   {actual}"
            )
        print(f"  OK  sha256:{actual[:16]}…  {name}")
        if name.endswith(".whl"):
            wheel = artifact
    if wheel is None:
        raise RuntimeError("No wheel (.whl) found in sha256sums.txt.")
    return wheel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dist-dir",
        default=None,
        help="Output directory for built artifacts (default: a temporary directory).",
    )
    parser.add_argument(
        "--verify-only",
        metavar="DIST_DIR",
        default=None,
        help=(
            "Verify existing artifacts in DIST_DIR against sha256sums.txt, "
            "then install the wheel and run smoke checks. Does not rebuild."
        ),
    )
    args = parser.parse_args(argv)

    source_root = Path(__file__).resolve().parent.parent
    failures: list[str] = []

    if args.verify_only:
        # Verify-only mode: check existing artifacts, then run smoke checks.
        dist_dir = Path(args.verify_only)
        with tempfile.TemporaryDirectory(prefix="stackwinnow-dist-verify-") as tmpdir:
            venv_dir = Path(tmpdir) / "verify-venv"
            print("Verifying checksums…")
            try:
                wheel = verify_existing_checksums(dist_dir)
            except RuntimeError as exc:
                failures.append(f"checksum verification: {exc}")
                print(f"FAIL  {failures[-1]}")
                return _report(failures)

            print("Creating clean venv…")
            try:
                python = create_venv(venv_dir)
            except RuntimeError as exc:
                failures.append(f"venv creation: {exc}")
                print(f"FAIL  {failures[-1]}")
                return _report(failures)

            print("Installing verified wheel with dependencies…")
            try:
                install_wheel(python, wheel)
            except RuntimeError as exc:
                failures.append(f"wheel install: {exc}")
                print(f"FAIL  {failures[-1]}")
                return _report(failures)

            _run_smoke_checks(python, failures)
        return _report(failures)

    # Build mode: build fresh artifacts, install, run smoke checks.
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

        print("Installing wheel with dependencies…")
        try:
            install_wheel(python, wheel)
        except RuntimeError as exc:
            failures.append(f"wheel install: {exc}")
            print(f"FAIL  {failures[-1]}")
            _report(failures)
            return 1

        _run_smoke_checks(python, failures)

    return _report(failures)


def _run_smoke_checks(python: Path, failures: list[str]) -> None:
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

    print("Checking catalog…")
    try:
        check_catalog(python)
        print("  OK")
    except RuntimeError as exc:
        failures.append(f"catalog: {exc}")
        print(f"FAIL  {failures[-1]}")


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
