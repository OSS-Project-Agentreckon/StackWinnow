"""Build versioned wheel and sdist artifacts and write sha256 checksums.

Usage (from the repo root):
    python scripts/build_release.py [--dist-dir DIST_DIR]

The script:
  1. Verifies the package version via importlib.metadata (must not be a dev/pre-release).
  2. Builds both a wheel and a source distribution.
  3. Writes a ``sha256sums.txt`` file in the output directory listing each artifact.
  4. Prints a summary of produced artifacts and their digests.

The output directory is ``dist/`` by default and is excluded from version control
(see .gitignore). Do not tag the release before this script passes.

Exit 0 on success; 1 on any failure.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=SOURCE_ROOT)


def _check_version() -> str:
    """Return the declared version; raise if it looks like a dev/pre-release."""
    result = _run([sys.executable, "-c", "from stackwinnow import __version__; print(__version__)"])
    if result.returncode != 0:
        raise RuntimeError(f"Cannot read version: {result.stderr.strip()}")
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("Empty version string.")
    lower = version.lower()
    if any(tag in lower for tag in ("dev", "alpha", "beta", "rc", "post")):
        raise RuntimeError(
            f"Version {version!r} looks like a pre-release or dev version.\n"
            "Update __version__ in src/stackwinnow/__init__.py before building a release."
        )
    return version


def _build(dist_dir: Path) -> tuple[Path, Path]:
    """Build wheel and sdist; return (wheel_path, sdist_path)."""
    result = _run([sys.executable, "-m", "build", "--outdir", str(dist_dir)])
    if result.returncode != 0:
        raise RuntimeError(f"build failed:\n{result.stderr}")
    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))
    if not wheels:
        raise RuntimeError("No wheel produced.")
    if not sdists:
        raise RuntimeError("No sdist produced.")
    wheel = max(wheels, key=lambda p: p.stat().st_mtime)
    sdist = max(sdists, key=lambda p: p.stat().st_mtime)
    return wheel, sdist


def _write_checksums(dist_dir: Path, artifacts: list[Path]) -> Path:
    """Write sha256sums.txt; return its path."""
    lines = [f"{_sha256(p)}  {p.name}" for p in sorted(artifacts, key=lambda p: p.name)]
    out = dist_dir / "sha256sums.txt"
    out.write_text("\n".join(lines) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        default=str(SOURCE_ROOT / "dist"),
        help="Output directory for built artifacts (default: dist/).",
    )
    args = parser.parse_args(argv)
    dist_dir = Path(args.dist_dir)

    try:
        print("Checking version…")
        version = _check_version()
        print(f"  version: {version}")

        dist_dir.mkdir(parents=True, exist_ok=True)

        print("Building wheel and sdist…")
        wheel, sdist = _build(dist_dir)
        print(f"  wheel:  {wheel.name}")
        print(f"  sdist:  {sdist.name}")

        print("Writing checksums…")
        checksums = _write_checksums(dist_dir, [wheel, sdist])
        print(f"  checksums: {checksums}")
        print()
        for artifact in sorted([wheel, sdist]):
            print(f"  sha256:{_sha256(artifact)}  {artifact.name}")
        print()
        print(f"Release artifacts ready in {dist_dir}")
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
