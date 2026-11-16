"""Exercise the installed command outside the source checkout."""

import os
import subprocess
import sysconfig
from importlib.metadata import version
from pathlib import Path

import pytest


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = Path(sysconfig.get_path("scripts")) / (
        "stackwinnow.exe" if os.name == "nt" else "stackwinnow"
    )
    assert executable.is_file(), "Install the package before running CLI tests."
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [str(executable), *args],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("args", [(), ("--help",)])
def test_help_is_available_without_a_project(tmp_path: Path, args: tuple[str, ...]) -> None:
    result = run_cli(tmp_path, *args)

    assert result.returncode == 0
    assert "usage: stackwinnow" in result.stdout
    assert "--version" in result.stdout
    assert "only help and version are available" in result.stdout
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_version_matches_installed_distribution(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"stackwinnow {version('stackwinnow')}"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [("install", "headroom"), ("--unknown-option",)])
def test_unimplemented_commands_and_unknown_options_fail(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    result = run_cli(tmp_path, *args)

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []
