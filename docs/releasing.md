# Releasing StackWinnow

This document describes the repeatable process for building and publishing a versioned StackWinnow release.

---

## Prerequisites

- Python 3.11 on macOS 14+ (arm64) — the declared supported build platform.
- Dev dependencies installed: `pip install -e ".[dev]"` (includes `build>=1.2`).
- A clean working tree on the commit that will become the release (`git status` shows nothing staged or unstaged).
- All CI checks green on the target commit.

---

## 1. Update the version

Edit `src/stackwinnow/__init__.py`:

```python
__version__ = "0.1.0"   # remove any .dev0 / .rcN / .aN suffix
```

Commit the version bump:

```sh
git commit -m "build(release): bump version to 0.1.0"
```

---

## 2. Build artifacts

Run the release script from the repo root:

```sh
python scripts/build_release.py
```

This produces three files in `dist/` (excluded from version control):

| File | Description |
|------|-------------|
| `stackwinnow-0.1.0-py3-none-any.whl` | Built distribution (wheel) |
| `stackwinnow-0.1.0.tar.gz` | Source distribution (sdist) |
| `sha256sums.txt` | sha256 checksums for the two artifacts |

The script refuses to run if `__version__` contains a dev, alpha, beta, rc, or post suffix.

---

## 3. Verify the wheel

Verify the exact artifacts produced in step 2, checking their sha256 digests and
running smoke checks (entry point, `--version`, catalog). Use `--verify-only` so
that the release artifacts and `sha256sums.txt` are **not** overwritten:

```sh
python scripts/check_distribution.py --verify-only dist
```

Do not use `--dist-dir dist` here: that mode rebuilds from source, overwrites both
artifacts, and invalidates the recorded checksums.

You can also run the packaging test suite (session-scoped venv, built once):

```sh
python -m pytest tests/packaging/ --run-packaging -v
```

Expected: all checks pass, `stackwinnow --version` prints `stackwinnow 0.1.0`.

---

## 4. Inspect the checksums

```sh
cat dist/sha256sums.txt
```

Record or publish these digests alongside the release artifacts so users can verify integrity independently. Byte-for-byte reproducibility is not currently guaranteed (setuptools embeds a build timestamp); re-running the build will produce files with different digests.

---

## 5. Create the release tag

Only create the tag after the build and verification steps pass:

```sh
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

Do not create the tag before the artifacts are verified.

---

## 6. Publish to PyPI (when ready)

```sh
python -m twine upload dist/stackwinnow-0.1.0*
```

`twine` is not a declared dev dependency; install it separately before uploading.

---

## Artifact locations

Built artifacts live in `dist/`, which is listed in `.gitignore` and never committed. Each build run may overwrite prior artifacts. If you need to retain multiple versions, copy them out before rebuilding.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `build_release.py` refuses with "pre-release" | `__version__` still has `.dev0` or similar suffix |
| `check_distribution.py` fails "entry point not found" | `[project.scripts]` entry in `pyproject.toml` missing or misspelled |
| `stackwinnow --version` prints wrong version | Editable install shadows the wheel; use a fresh venv |
| Catalog data not found | `[tool.setuptools.package-data]` missing the `data/*.json` glob |
