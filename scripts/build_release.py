"""Build/check manager archives from an exact Git commit, never the working tree."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = {"pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "MANIFEST.in"}
DOC_FILES = {"docs/releasing.md", "docs/support-matrix.md"}
PREFIXES = ("src/stackwinnow/", "scripts/", "tests/", "licenses/", "examples/profiles/")


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(f"Command failed: {command!r}\n{result.stdout}\n{result.stderr}")
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.stdout


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive name: {name}")


def source_snapshot(ref: str) -> tuple[str, dict[str, bytes]]:
    commit = run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], ROOT).strip()
    raw = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=ROOT)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            name = member.name
            if name not in ROOT_FILES | DOC_FILES and not name.startswith(PREFIXES):
                continue
            safe_name(name)
            if set(PurePosixPath(name).parts) & {
                "node_modules",
                ".stackwinnow",
                ".venv",
                "venv",
                "__pycache__",
                ".env",
            } or name.endswith((".pyc", ".pyo")):
                raise ValueError(f"Private/runtime/cache file in release source: {name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"Release source must contain regular files: {name}")
            files[name] = archive.extractfile(member).read()
    return commit, files


def source_version(files: dict[str, bytes]) -> str:
    tree = ast.parse(files["src/stackwinnow/__init__.py"])
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and value and all(c.isalnum() or c == "." for c in value):
                return value
    raise ValueError("Missing literal release version in source")


def archive_files(path: Path) -> dict[str, bytes]:
    contents = {}
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                safe_name(item.filename)
                if item.is_dir():
                    continue
                if item.filename in contents or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Duplicate or symlink wheel member")
                contents[item.filename] = archive.read(item)
    else:
        with tarfile.open(path) as archive:
            for item in archive.getmembers():
                safe_name(item.name)
                if item.isdir():
                    continue
                if not item.isfile() or item.name in contents:
                    raise ValueError("Duplicate or non-regular source archive member")
                contents[item.name] = archive.extractfile(item).read()
    return contents


def inspect(dist: Path, commit: str, files: dict[str, bytes]) -> dict:
    version = source_version(files)
    names = {f"stackwinnow-{version}-py3-none-any.whl", f"stackwinnow-{version}.tar.gz"}
    actual = {
        p.name for p in dist.iterdir() if p.name not in {"release-manifest.json", "SHA256SUMS"}
    }
    if actual != names:
        raise ValueError(f"Expected exactly {sorted(names)}; found {sorted(actual)}")
    artifacts = {}
    for name in sorted(names):
        path = dist / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Not a regular artifact: {name}")
        members = archive_files(path)
        wheel = name.endswith(".whl")
        prefix = "" if wheel else f"stackwinnow-{version}/"
        metadata_name = (
            f"stackwinnow-{version}.dist-info/METADATA" if wheel else prefix + "PKG-INFO"
        )
        metadata = BytesParser().parsebytes(members[metadata_name])
        if metadata["Name"] != "stackwinnow" or metadata["Version"] != version:
            raise ValueError(f"Incorrect package identity: {name}")
        required = {}
        for source, data in files.items():
            if source.startswith("src/stackwinnow/"):
                required[(source.removeprefix("src/") if wheel else prefix + source)] = data
        if wheel:
            for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                required[f"stackwinnow-{version}.dist-info/licenses/{notice}"] = files[notice]
        else:
            for source, data in files.items():
                if (
                    source in ROOT_FILES | DOC_FILES
                    or source.startswith(("licenses/", "examples/profiles/", "tests/"))
                    or source in {"scripts/build_release.py", "scripts/check_distribution.py"}
                ):
                    required[prefix + source] = data
        for member, data in required.items():
            if members.get(member) != data:
                raise ValueError(f"Missing/modified committed source or resource: {member}")
        for member, data in members.items():
            if wheel:
                if member in required:
                    continue
                info = f"stackwinnow-{version}.dist-info/"
                allowed = {
                    info + p
                    for p in ("METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt")
                }
                notices = {
                    info + "licenses/" + p: files[p] for p in ("LICENSE", "THIRD_PARTY_NOTICES.md")
                }
                if member in notices and data == notices[member]:
                    continue
                if member not in allowed:
                    raise ValueError(f"Unexpected wheel member: {member}")
            else:
                if not member.startswith(prefix):
                    raise ValueError(f"Unexpected sdist root: {member}")
                relative = member.removeprefix(prefix)
                if relative in files:
                    if data != files[relative]:
                        raise ValueError(f"Modified committed source: {relative}")
                elif relative not in {"PKG-INFO", "setup.cfg"} and not relative.startswith(
                    "src/stackwinnow.egg-info/"
                ):
                    raise ValueError(f"Unexpected sdist member: {member}")
        artifacts[name] = {
            "sha256": digest(path.read_bytes()),
            "files": {n: digest(d) for n, d in sorted(members.items())},
        }
    return {
        "schema_version": 1,
        "version": version,
        "source_commit": commit,
        "artifacts": artifacts,
    }


def install_check(dist: Path, manifest: dict) -> None:
    """Optional networked wheel AND sdist installs, outside source with isolated imports."""
    for name, artifact in manifest["artifacts"].items():
        with tempfile.TemporaryDirectory(prefix="stackwinnow-install-") as temp:
            directory = Path(temp)
            venv.create(directory / "venv", with_pip=True)
            python = (
                directory / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            )
            run([str(python), "-I", "-m", "pip", "install", str(dist / name)], directory)
            run([str(python), "-I", "-m", "pip", "check"], directory)
            package_files = {}
            prefix = "" if name.endswith(".whl") else f"stackwinnow-{manifest['version']}/src/"
            for member, checksum in artifact["files"].items():
                relative = member.removeprefix(prefix)
                if relative.startswith("stackwinnow/"):
                    package_files[relative.removeprefix("stackwinnow/")] = checksum
            code = (
                "import hashlib, importlib.metadata as m, pathlib, sys, stackwinnow; "
                "from stackwinnow.catalog import load_catalog; "
                "root=pathlib.Path(stackwinnow.__file__).parent; "
                "assert root.is_relative_to(pathlib.Path(sys.prefix)); "
                f"assert stackwinnow.__version__ == m.version('stackwinnow') == {manifest['version']!r}; "
                "assert load_catalog().tools; "
                f"assert all(hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p,h in {package_files!r}.items())"
            )
            run([str(python), "-I", "-c", code], directory)
            run([str(python), "-I", "-m", "stackwinnow", "--version"], directory)
            entry = python.parent / ("stackwinnow.exe" if os.name == "nt" else "stackwinnow")
            run([str(entry), "--version"], directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-ref", default="HEAD", help="Exact committed source; working changes excluded"
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument(
        "--no-isolation", action="store_true", help="Use preinstalled build dependencies"
    )
    parser.add_argument(
        "--verify-only", action="store_true", help="Compare existing manifest/artifacts to source"
    )
    parser.add_argument(
        "--install-check", action="store_true", help="Also install each artifact in fresh venvs"
    )
    args = parser.parse_args(argv)
    try:
        commit, files = source_snapshot(args.source_ref)
        dist = args.dist_dir.resolve()
        if not args.verify_only:
            if dist.exists() and any(dist.iterdir()):
                raise ValueError("Build output directory must be empty")
            dist.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="stackwinnow-source-") as temp:
                source = Path(temp)
                for name, data in files.items():
                    destination = source / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                command = [sys.executable, "-m", "build", "--outdir", str(dist)]
                if args.no_isolation:
                    command.append("--no-isolation")
                print(run(command, source))
        manifest = inspect(dist, commit, files)
        checksums = "".join(
            f"{entry['sha256']}  {name}\n" for name, entry in manifest["artifacts"].items()
        )
        if args.verify_only:
            if json.loads((dist / "release-manifest.json").read_text()) != manifest:
                raise ValueError("Release manifest does not match artifacts and committed source")
            if (dist / "SHA256SUMS").read_text() != checksums:
                raise ValueError("Checksum file mismatch")
        else:
            (dist / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            (dist / "SHA256SUMS").write_text(checksums)
        if args.install_check:
            install_check(dist, manifest)
        print(f"Verified manager archives for {manifest['version']} at {commit}")
        return 0
    except (
        ValueError,
        OSError,
        KeyError,
        tarfile.TarError,
        zipfile.BadZipFile,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Release check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
