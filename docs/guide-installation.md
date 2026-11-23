# Installation guide

## Prerequisites

- **Python 3.11 or newer.** Check with `python3 --version`.
- **pip** (bundled with Python 3.11+).
- An internet connection the first time, to download declared dependencies.

Supported integration targets additionally require Node 24 and Codex CLI 0.169.0
(macOS arm64 only). Catalog discovery and project inspection work offline and need
no assistant or external service.

## Install from source

Clone the repository and create a virtual environment:

```sh
git clone https://github.com/OSS-Project-Agentreckon/StackWinnow.git
cd StackWinnow
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install .
```

For development extras (linting, packaging, tests):

```sh
python -m pip install -e '.[dev]'
```

## Verify the installation

```sh
stackwinnow --version
stackwinnow --help
stackwinnow catalog list
```

A clean install prints a version string, top-level help, and a table of the 30
catalog entries. Exit status 0 means the package is functioning; exit status 2
means an argument or catalog error — see the message for details.

## Install from a release wheel

If a release wheel is available (`.whl` file):

```sh
python -m pip install stackwinnow-<version>-py3-none-any.whl
stackwinnow --version
```

Always use the wheel that matches the manager version you intend to run. The
released wheel was verified against committed source hashes; see
[releasing.md](releasing.md) for reproduction steps.

## Install from an editable checkout (development)

Editable installs re-read source from the checkout on every import, which is
useful when modifying the package:

```sh
python -m pip install -e '.[dev]'
```

After pulling new commits or switching branches, re-run the install command to
update distribution metadata (version, entry points).

## Upgrading

Pull the new commits, then re-install to sync the entry-point version:

```sh
git pull
python -m pip install -e '.[dev]'   # development
# or
python -m pip install .              # regular install
```

## Uninstalling

```sh
python -m pip uninstall stackwinnow
```

This removes the manager package from the environment. Tool integrations managed
through the CLI (Graphify, Headroom, promptfoo, Playwright MCP) are removed
separately via `stackwinnow remove plan` and `stackwinnow remove apply`.
