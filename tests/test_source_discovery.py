"""User-visible discovery outcomes; no SDK, network, or project execution required."""

import json
from pathlib import Path

import pytest

from stackwinnow import source_discovery as source
from stackwinnow.cli import main
from stackwinnow.detect import InspectionResult, inspect_project
from stackwinnow.recommend import recommend_tools
from stackwinnow.report import build_report

PYTHON_APP = """from openai import OpenAI
from anthropic import Anthropic
client = OpenAI()
other = Anthropic()
def answer(documents):
    context = "\\n".join(doc.page_content for doc in documents)
    for attempt in range(3):
        first = client.responses.create(model="private-model", input=context)
        second = client.responses.create(model="private-model", input=context)
    return other.messages.create(model="private-model", messages=[{"role": "user", "content": context}])
"""


def write(root: Path, text: str, path: str = "app.py") -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def findings(root: Path):
    return {f.rule_id: f for f in inspect_project(root).source_discovery.findings}


def test_source_alone_discovers_all_opportunities_with_locations(tmp_path):
    target = write(tmp_path, PYTHON_APP)
    result = inspect_project(tmp_path)
    assert result.complete
    assert result.profile.goals == []
    found = {f.rule_id: f for f in result.source_discovery.findings}
    assert set(found) == {
        "source-context-assembly",
        "source-repeated-input",
        "source-call-volume",
        "source-model-choice",
        "source-multiple-providers",
        "source-evaluation-coverage",
    }
    assert [e.line for e in found["source-repeated-input"].evidence] == [8, 9]
    assert all(f.question and f.confidence for f in found.values())
    assert "private-model" not in result.model_dump_json()
    assert result == InspectionResult.model_validate_json(result.model_dump_json())
    recommendations = recommend_tools(result)
    ids = {r.tool_id for r in recommendations.recommendations}
    assert {"headroom", "gptcache", "promptfoo", "litellm"} <= ids
    assert all(not r.selected for r in recommendations.recommendations)
    assert target.read_text() == PYTHON_APP
    goal_result = recommend_tools(inspect_project(tmp_path, goals=["Evaluate answers"]))
    assert any(r.kind == "source" for t in goal_result.recommendations for r in t.reasons)
    assert any(r.kind == "goal" for t in goal_result.recommendations for r in t.reasons)


@pytest.mark.parametrize(
    "code",
    [
        "import openai\n",
        '# client.responses.create(model="x", input="y")\n',
        'text = "client.responses.create(model=42, input=42)"\n',
        'class Client: pass\nclient = Client()\nclient.responses.create(model="x", input="y")',
        'from openai import OpenAI\nclient=OpenAI()\ndef f(client):\n client.responses.create(model="x", input="y")',
        'from openai import OpenAI\nclient=OpenAI()\nclient=object()\nclient.responses.create(model="x", input="y")',
    ],
)
def test_imports_comments_strings_and_unrelated_or_shadowed_clients_are_not_evidence(
    tmp_path, code
):
    write(tmp_path, code)
    assert not findings(tmp_path)


def test_short_prompt_not_compression_and_separate_functions_not_duplicate(tmp_path):
    write(
        tmp_path,
        """import openai as ai
client = ai.OpenAI()
def a():
    return client.responses.create(model=model, input="Hello")
def b():
    return client.responses.create(model=model, input="Hello")
""",
    )
    found = findings(tmp_path)
    assert set(found) == {"source-evaluation-coverage"}


def test_existing_optimization_and_evaluation_imports_are_acknowledged(tmp_path):
    write(tmp_path, "import headroom\nimport gptcache\nimport deepeval\n" + PYTHON_APP)
    found = findings(tmp_path)
    assert "source-evaluation-coverage" not in found
    assert any("Existing compression" in c for c in found["source-context-assembly"].caveats)
    assert any("Existing caching" in c for c in found["source-repeated-input"].caveats)


def test_async_retry_and_comprehension(tmp_path):
    write(
        tmp_path,
        """from openai import AsyncOpenAI as AI
from tenacity import retry
client = AI()
@retry(stop=limit)
async def run():
    return await client.responses.create(model=model, input=prompt)
async def many():
    return [await client.responses.create(model=model, input=p) for p in prompts]
""",
    )
    result = inspect_project(tmp_path)
    assert (
        len([f for f in result.source_discovery.findings if f.rule_id == "source-call-volume"]) == 2
    )


def test_javascript_multiline_calls_comments_and_strings(tmp_path):
    write(
        tmp_path,
        """import OpenAI from "openai";
const client = new OpenAI();
const context = documents.map(doc => doc.text).join("\\n");
for (const attempt of attempts) {
  const first = await client.responses.create({
    model: "private-model", input: context
  });
  const second = await client.responses.create({model: "private-model", input: context});
}
// client.responses.create({model: "not-code", input: context});
const example = "client.responses.create({model: 'not-code', input: context})";
""",
        "src/app.ts",
    )
    found = findings(tmp_path)
    assert {"source-context-assembly", "source-repeated-input", "source-call-volume"} <= set(found)
    assert [e.line for e in found["source-repeated-input"].evidence] == [5, 8]
    assert all(f.confidence == "low" for f in found.values())
    assert "private-model" not in inspect_project(tmp_path).model_dump_json()


def test_ignore_rules_links_and_vendor_code_are_excluded(tmp_path):
    write(tmp_path, "ignored/\nsecret.py\n", ".gitignore")
    for path in [
        "ignored/app.py",
        "secret.py",
        "node_modules/app.py",
        ".hidden/app.py",
        "vendor/app.py",
    ]:
        write(tmp_path, PYTHON_APP, path)
    outside = tmp_path.parent / (tmp_path.name + "-outside.py")
    outside.write_text(PYTHON_APP)
    (tmp_path / "linked.py").symlink_to(outside)
    result = inspect_project(tmp_path)
    assert result.source_discovery.files_scanned == 0
    assert not result.source_discovery.findings


def test_partial_source_keeps_valid_findings_and_sanitizes_parse_errors(tmp_path, monkeypatch):
    write(tmp_path, PYTHON_APP)
    write(tmp_path, 'synthetic_secret = "unterminated', "broken.py")
    result = inspect_project(tmp_path)
    assert not result.complete
    assert result.source_discovery.status == "partial"
    assert result.source_discovery.findings
    assert "synthetic_secret" not in result.model_dump_json()
    monkeypatch.setattr(source, "MAX_FILES", 1)
    limited = inspect_project(tmp_path)
    assert limited.source_discovery.status == "partial"
    assert limited.source_discovery.files_scanned == 1


def test_large_file_and_hardlink_are_not_read(tmp_path, monkeypatch):
    write(tmp_path, PYTHON_APP)
    (tmp_path / "hard.py").hardlink_to(tmp_path / "app.py")
    monkeypatch.setattr(source, "MAX_FILE_BYTES", 20)
    result = inspect_project(tmp_path)
    assert result.source_discovery.status == "partial"
    assert not result.source_discovery.findings


def test_test_only_calls_do_not_imply_missing_production_evaluations(tmp_path):
    write(tmp_path, PYTHON_APP, "tests/test_ai.py")
    found = findings(tmp_path)
    assert "source-evaluation-coverage" not in found
    assert all(f.confidence == "low" for f in found.values())


def test_cli_report_and_opt_out(tmp_path, capsys):
    write(tmp_path, PYTHON_APP)
    assert main(["recommend", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(r["kind"] == "source" for t in payload["recommendations"] for r in t["reasons"])
    assert main(["inspect", str(tmp_path)]) == 0
    assert "app.py:8" in capsys.readouterr().out
    report = build_report(tmp_path).to_markdown()
    assert "app.py:8" in report
    assert "Question:" in report
    assert main(["inspect", str(tmp_path), "--no-source", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_discovery"]["status"] == "not-scanned"
    assert not payload["source_discovery"]["findings"]


@pytest.mark.parametrize(
    "body",
    [
        'function example(client) { client.responses.create({model: "x", input: "y"}); }',
        'const example = (client) => { client.responses.create({model: "x", input: "y"}); };',
        'const pattern = /client.responses.create({model: "x", input: "y"})/;',
        'client = unrelated; client.responses.create({model: "x", input: "y"});',
    ],
)
def test_javascript_shadowing_and_regex_are_not_model_calls(tmp_path, body):
    write(tmp_path, 'import OpenAI from "openai"; const client = new OpenAI();\n' + body, "app.js")
    assert not findings(tmp_path)


def test_context_manager_and_sdk_response_wrappers(tmp_path):
    write(
        tmp_path,
        """from openai import OpenAI
with OpenAI() as client:
    result = client.chat.completions.with_raw_response.create(model="x", messages=[])
    stream = client.responses.stream(model="x", input="hello")
""",
    )
    found = inspect_project(tmp_path).source_discovery.findings
    assert len([f for f in found if f.rule_id == "source-model-choice"]) == 2


def test_class_held_client_and_local_history_are_recognized(tmp_path):
    write(
        tmp_path,
        """from openai import OpenAI
class Agent:
    def __init__(self):
        self.client = OpenAI()
        self.history = []
    def answer(self, text):
        self.history.append({"role": "user", "content": text})
        return self.client.responses.create(model="example", input=self.history)
""",
    )
    found = findings(tmp_path)
    assert "source-context-assembly" in found
    assert found["source-model-choice"].evidence[0].line == 8


def test_langchain_invocation_is_source_evidence_without_manifest(tmp_path):
    write(
        tmp_path,
        """from langchain_openai import ChatOpenAI
model = ChatOpenAI()
def answer(documents):
    context = "\\n".join(documents)
    for _ in range(2):
        model.invoke(context)
""",
    )
    found = findings(tmp_path)
    assert {"source-context-assembly", "source-call-volume", "source-evaluation-coverage"} <= set(
        found
    )


def test_client_attribute_is_not_shared_with_another_class(tmp_path):
    write(
        tmp_path,
        """from openai import OpenAI
class First:
    def __init__(self):
        self.client = OpenAI()
class Second:
    def call(self):
        return self.client.responses.create(model="example", input="hello")
""",
    )
    assert not findings(tmp_path)
