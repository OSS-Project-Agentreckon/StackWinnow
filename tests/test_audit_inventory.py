"""Offline regressions for the scope of CI vulnerability inventories."""

from types import SimpleNamespace

import pytest

from scripts import export_audit_requirements as audit


def test_environment_keeps_dependencies_and_build_tools_but_excludes_local_project():
    installed = [
        SimpleNamespace(metadata={"Name": name}, version=version)
        for name, version in (
            ("StackWinnow", "0.1.0.dev0"),
            ("pydantic_core", "2.0.0"),
            ("pip", "26.3"),
            ("setuptools", "84.2.1"),
        )
    ]
    assert audit.environment_requirements(installed).splitlines() == [
        "pip==26.3",
        "pydantic-core==2.0.0",
        "setuptools==84.2.1",
    ]


def test_conflicting_normalized_versions_block_inventory():
    with pytest.raises(ValueError, match="Conflicting installed versions"):
        audit.pinned_requirements([("Example_Package", "1.0"), ("example-package", "2.0")])


def test_new_registered_python_tool_is_audited_without_installing_it(monkeypatch):
    modes = [
        SimpleNamespace(tool_id="new-tool", mode="library", version="1.2.3"),
        SimpleNamespace(tool_id="promptfoo", mode="deterministic", version="1.0.0"),
    ]
    imports = []

    def import_adapter(name):
        imports.append(name)
        return SimpleNamespace(_PACKAGE_NAME="new-python-package", VERSION="1.2.3")

    monkeypatch.setattr(audit, "supported_modes", lambda: modes)
    monkeypatch.setattr(audit, "import_module", import_adapter)
    assert audit.tool_requirements() == "new-python-package==1.2.3\n"
    assert imports == ["stackwinnow.adapters.new_tool"]


def test_registry_and_recipe_version_mismatch_blocks_audit(monkeypatch):
    monkeypatch.setattr(
        audit,
        "supported_modes",
        lambda: [SimpleNamespace(tool_id="new-tool", mode="library", version="1.2.3")],
    )
    monkeypatch.setattr(
        audit,
        "import_module",
        lambda _: SimpleNamespace(_PACKAGE_NAME="new-python-package", VERSION="1.2.4"),
    )
    with pytest.raises(ValueError, match="audit target differs from its recipe"):
        audit.tool_requirements()
