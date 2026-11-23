"""Reusable local fixtures and explicit opt-ins for real upstream checks."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from stackwinnow import runtime

pytest_plugins = ["pytester"]
FIXTURES = Path(__file__).parent / "fixtures"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("stackwinnow")
    group.addoption("--run-integration", action="store_true", help="Run real upstream checks.")
    group.addoption(
        "--run-provider", action="store_true", help="Also allow checks using a model provider."
    )
    group.addoption(
        "--run-packaging", action="store_true", help="Run distribution packaging checks (slow)."
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: requires an actual upstream tool/client")
    config.addinivalue_line("markers", "requires_provider: requires model-provider access")
    config.addinivalue_line(
        "markers",
        "packaging: builds and installs the distribution (slow; requires --run-packaging)",
    )
    if config.getoption("--run-provider") and not config.getoption("--run-integration"):
        raise pytest.UsageError("--run-provider also requires --run-integration")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        provider = item.get_closest_marker("requires_provider") is not None
        integration = provider or item.get_closest_marker("integration") is not None
        packaging = item.get_closest_marker("packaging") is not None
        if integration and not config.getoption("--run-integration"):
            item.add_marker(pytest.mark.skip(reason="real tool checks require --run-integration"))
        elif provider and not config.getoption("--run-provider"):
            item.add_marker(pytest.mark.skip(reason="model-provider checks require --run-provider"))
        elif packaging and not config.getoption("--run-packaging"):
            item.add_marker(pytest.mark.skip(reason="packaging checks require --run-packaging"))


@pytest.fixture(autouse=True)
def test_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect in-process home discovery without changing the parent's environment."""
    home_dir = tmp_path_factory.mktemp("test home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    return home_dir


@pytest.fixture(autouse=True)
def no_host_tool_discovery(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests declare available executables instead of depending on the laptop."""
    if request.node.get_closest_marker("integration") or request.node.get_closest_marker(
        "requires_provider"
    ):
        return
    monkeypatch.setattr(runtime.shutil, "which", lambda *args, **kwargs: None)


def subprocess_environment(home_dir: Path) -> dict[str, str]:
    """Build a child's environment; never replace HOME or credentials in the parent."""
    inherited = ("PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "LANG")
    environment = {name: os.environ[name] for name in inherited if name in os.environ}
    directories = {
        "HOME": home_dir,
        "USERPROFILE": home_dir,
        "XDG_CONFIG_HOME": home_dir / ".config",
        "XDG_DATA_HOME": home_dir / ".local" / "share",
        "XDG_CACHE_HOME": home_dir / ".cache",
        "XDG_STATE_HOME": home_dir / ".local" / "state",
        "APPDATA": home_dir / "AppData" / "Roaming",
        "LOCALAPPDATA": home_dir / "AppData" / "Local",
        "TMPDIR": home_dir / "tmp",
        "TMP": home_dir / "tmp",
        "TEMP": home_dir / "tmp",
    }
    for name, path in directories.items():
        path.mkdir(parents=True, exist_ok=True)
        environment[name] = str(path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


@pytest.fixture
def subprocess_env(test_home: Path) -> dict[str, str]:
    return subprocess_environment(test_home)


@dataclass(frozen=True)
class FixtureProject:
    root: Path

    @property
    def settings(self) -> Path:
        return self.root / "assistant-settings.json"

    @property
    def page(self) -> Path:
        return self.root / "web" / "index.html"


@pytest.fixture
def project_factory(tmp_path: Path) -> Callable[[], FixtureProject]:
    count = 0

    def create() -> FixtureProject:
        nonlocal count
        count += 1
        root = tmp_path / f"fixture project {count}"
        shutil.copytree(FIXTURES / "project", root)
        shutil.copyfile(FIXTURES / "assistant-settings.json", root / "assistant-settings.json")
        return FixtureProject(root)

    return create


@pytest.fixture
def fixture_project(project_factory: Callable[[], FixtureProject]) -> FixtureProject:
    return project_factory()


@pytest.fixture
def browser_fixture_url(fixture_project: FixtureProject) -> Iterator[str]:
    """Serve only the copied fixture's web directory on an ephemeral loopback port."""

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

    handler = partial(QuietHandler, directory=str(fixture_project.page.parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "Fixture HTTP server did not stop."
