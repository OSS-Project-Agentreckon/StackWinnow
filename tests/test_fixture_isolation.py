"""Exercise fixture isolation, deterministic data, and local transport."""

import ast
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

import pytest
from conftest import FIXTURES, FixtureProject, subprocess_environment

from stackwinnow.runtime import inspect_environment


def test_fixture_copies_do_not_change_seeds_or_other_projects(
    project_factory: Callable[[], FixtureProject],
) -> None:
    first, second = project_factory(), project_factory()
    seed = FIXTURES / "assistant-settings.json"
    original = seed.read_bytes()

    first.settings.write_text('{"changed": true}\n', encoding="utf-8")
    (first.root / "sample_app" / "names.py").unlink()

    assert second.settings.read_bytes() == original
    assert (second.root / "sample_app" / "names.py").is_file()
    assert seed.read_bytes() == original
    assert " " in first.root.name


def test_fixture_has_known_project_config_and_call_relationship(
    fixture_project: FixtureProject,
) -> None:
    metadata = tomllib.loads((fixture_project.root / "pyproject.toml").read_text())
    settings = json.loads(fixture_project.settings.read_text())
    code = ast.parse((fixture_project.root / "sample_app" / "greetings.py").read_text())
    greeting = next(node for node in code.body if isinstance(node, ast.FunctionDef))
    calls = [node.func.id for node in ast.walk(greeting) if isinstance(node, ast.Call)]

    assert metadata["project"]["dependencies"] == []
    assert settings["theme"] == "keep-existing-theme"
    assert "existing-fixture-server" in settings["mcpServers"]
    assert greeting.name == "greet"
    assert "normalize_name" in calls


def test_known_result_runs_only_in_copied_project(
    fixture_project: FixtureProject, subprocess_env: dict[str, str]
) -> None:
    original_settings = fixture_project.settings.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sample_app.greetings import greet; print(greet('  ada   lovelace '))",
        ],
        cwd=fixture_project.root,
        env=subprocess_env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Hello, Ada Lovelace!\n"
    assert fixture_project.settings.read_bytes() == original_settings
    assert not list(fixture_project.root.rglob("__pycache__"))


def test_child_environment_excludes_credentials_and_keeps_parent_unchanged(
    test_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXAMPLE_PROVIDER_API_KEY", "synthetic-do-not-forward")
    monkeypatch.setenv("PYTHONPATH", "/synthetic/do-not-inherit")
    original = dict(os.environ)

    child = subprocess_environment(test_home)

    assert dict(os.environ) == original
    assert "EXAMPLE_PROVIDER_API_KEY" not in child
    assert "PYTHONPATH" not in child
    assert Path(child["HOME"]) == test_home
    assert Path.home() == test_home
    assert Path(child["XDG_CONFIG_HOME"]).is_relative_to(test_home)
    assert Path(child["TMPDIR"]).is_relative_to(test_home)


def test_default_runtime_inspection_uses_no_host_tools(fixture_project: FixtureProject) -> None:
    original = fixture_project.settings.read_bytes()

    profile, results = inspect_environment(str(fixture_project.root))

    assert profile.assistant is None
    assert "node_version" not in profile.facts
    assert "package_managers" not in profile.facts
    assert any(result.status == "blocked" for result in results)
    assert fixture_project.settings.read_bytes() == original


def test_browser_fixture_serves_copied_page_only(
    browser_fixture_url: str, fixture_project: FixtureProject
) -> None:
    opener = build_opener(ProxyHandler({}))
    with opener.open(browser_fixture_url, timeout=5) as response:
        assert response.status == 200
        assert response.headers.get_content_type() == "text/html"
        assert response.read() == fixture_project.page.read_bytes()

    with pytest.raises(HTTPError) as error:
        opener.open(browser_fixture_url.replace("index.html", "assistant-settings.json"), timeout=5)
    with error.value as response:
        assert response.code == 404
        response.read()


@pytest.mark.parametrize(
    ("options", "passed", "skipped"),
    [([], 1, 2), (["--run-integration"], 2, 1), (["--run-integration", "--run-provider"], 3, 0)],
)
def test_external_checks_require_explicit_opt_in(
    pytester: pytest.Pytester, options: list[str], passed: int, skipped: int
) -> None:
    pytester.makeconftest((Path(__file__).parent / "conftest.py").read_text())
    pytester.makepyfile(
        """
        import pytest
        def test_local(): pass
        @pytest.mark.integration
        def test_tool(): pass
        @pytest.mark.requires_provider
        def test_provider(): pass
        """
    )
    result = pytester.runpytest_subprocess("--strict-markers", "-q", *options, timeout=30)
    result.assert_outcomes(passed=passed, skipped=skipped)


def test_provider_option_cannot_accidentally_enable_integration(pytester: pytest.Pytester) -> None:
    pytester.makeconftest((Path(__file__).parent / "conftest.py").read_text())
    pytester.makepyfile("def test_local(): pass")
    result = pytester.runpytest_subprocess("--run-provider", "-q", timeout=30)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--run-provider also requires --run-integration*"])
