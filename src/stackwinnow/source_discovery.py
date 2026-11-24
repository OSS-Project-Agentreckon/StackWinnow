"""Bounded offline source observations; source text and literal values stay private."""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import os
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field

from stackwinnow.contracts import Contract, Identifier, NonEmptyText

MAX_FILES = 500
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_DEPTH = 20
MAX_FINDINGS = 100
EXCLUDED = {
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    "venv",
    "env",
    "site-packages",
    "third_party",
    "third-party",
}
SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


class SourceLocation(Contract):
    path: str
    line: int = Field(ge=1)
    detail: NonEmptyText


class SourceFinding(Contract):
    rule_id: Identifier
    confidence: Literal["low", "medium", "high"]
    summary: NonEmptyText
    evidence: list[SourceLocation] = Field(min_length=1)
    question: NonEmptyText
    capabilities: list[NonEmptyText]
    caveats: list[NonEmptyText] = Field(default_factory=list)


class SourceFile(Contract):
    path: str
    status: Literal["scanned", "excluded", "unsupported", "error"]
    language: str | None = None
    bytes_read: int = 0
    model_calls: int = 0
    reason: str


class SourceDiscovery(Contract):
    version: Literal[1] = 1
    status: Literal["not-scanned", "complete", "partial"] = "not-scanned"
    files_scanned: int = 0
    bytes_scanned: int = 0
    files: list[SourceFile] = Field(default_factory=list)
    inventory_truncated: bool = False
    excluded_entries: int = 0
    unsupported_files: int = 0
    model_calls: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    findings: list[SourceFinding] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Static patterns identify review opportunities, not runtime cost, correctness, or savings.",
            "Only supported Python and JavaScript/TypeScript SDK patterns in the scanned files are visible; "
            "wrappers, dynamic dispatch, other languages and external evaluation services may be missed.",
            "Confidence describes evidence for the pattern, not confidence that another tool is needed.",
        ]
    )


@dataclass
class _Call:
    path: str
    line: int
    provider: str
    scope: str
    signature: str
    literal_model: bool = False
    context: bool = False
    loop: bool = False
    retry: bool = False
    mitigations: set[str] = field(default_factory=set)
    heuristic: bool = False

    def location(self, detail: str) -> SourceLocation:
        return SourceLocation(path=self.path, line=self.line, detail=detail)


_CONSTRUCTORS = {
    "openai.OpenAI": "openai",
    "openai.AsyncOpenAI": "openai",
    "openai.AzureOpenAI": "openai",
    "openai.AsyncAzureOpenAI": "openai",
    "anthropic.Anthropic": "anthropic",
    "anthropic.AsyncAnthropic": "anthropic",
    "google.genai.Client": "google",
    "google.generativeai.GenerativeModel": "google-legacy",
    "langchain_openai.ChatOpenAI": "langchain-openai",
    "langchain_openai.AzureChatOpenAI": "langchain-openai",
    "langchain_anthropic.ChatAnthropic": "langchain-anthropic",
    "langchain_google_genai.ChatGoogleGenerativeAI": "langchain-google",
}
_METHODS = {
    "openai": {
        "chat.completions.create",
        "chat.completions.parse",
        "chat.completions.stream",
        "responses.create",
        "responses.parse",
        "responses.stream",
        "completions.create",
    },
    "anthropic": {"messages.create", "messages.stream"},
    "google": {"models.generate_content", "aio.models.generate_content"},
    "google-legacy": {"generate_content", "generate_content_async"},
}
for _provider in ("langchain-openai", "langchain-anthropic", "langchain-google"):
    _METHODS[_provider] = {"invoke", "ainvoke", "stream", "astream", "batch", "abatch"}
_CONTEXT = re.compile(
    r"(?:^|_)(?:documents?|docs|chunks?|context|history|messages|retrieved)(?:_|$)", re.I
)
_MITIGATIONS = {
    "headroom": "compression",
    "llmlingua": "compression",
    "gptcache": "caching",
    "litellm": "routing",
    "promptfoo": "evaluation",
    "deepeval": "evaluation",
    "ragas": "evaluation",
    "inspect_ai": "evaluation",
    "trulens": "evaluation",
}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Python(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.symbols: dict[str, str] = {}
        self.context_names: set[str] = set()
        self.calls: list[_Call] = []
        self.mitigations: set[str] = set()
        self.scope = "module"
        self.loop = 0
        self.retry = 0

    def resolve(self, node: ast.AST) -> str:
        name = _dotted(node)
        parts = name.split(".")
        for length in range(len(parts), 0, -1):
            prefix = ".".join(parts[:length])
            if prefix in self.symbols:
                return self.symbols[prefix] + name[len(prefix) :]
        return ""

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.symbols[alias.asname or alias.name.split(".")[0]] = (
                alias.name if alias.asname else alias.name.split(".")[0]
            )
            self.mitigations.update(
                value for key, value in _MITIGATIONS.items() if alias.name.split(".")[0] == key
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or not node.module:
            return
        for alias in node.names:
            self.symbols[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        if node.module.split(".")[0] in _MITIGATIONS:
            self.mitigations.add(_MITIGATIONS[node.module.split(".")[0]])

    def has_context(self, node: ast.AST) -> bool:
        """Trace local assembly, not a variable named messages alone."""
        for child in ast.walk(node):
            if (
                isinstance(child, (ast.Name, ast.Attribute))
                and _dotted(child) in self.context_names
            ):
                return True
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if len(child.value) >= 4000:
                    return True
            if isinstance(child, (ast.ListComp, ast.JoinedStr, ast.BinOp, ast.Call)):
                names = [
                    _dotted(n) for n in ast.walk(child) if isinstance(n, (ast.Name, ast.Attribute))
                ]
                if any(_CONTEXT.search(name.replace(".", "_")) for name in names):
                    if not isinstance(child, ast.Call) or (
                        isinstance(child.func, ast.Attribute)
                        and child.func.attr in {"join", "format", "dumps", "append", "extend"}
                    ):
                        return True
        return False

    def assign(self, target: ast.AST, value: ast.AST | None) -> None:
        if not isinstance(target, ast.Name) and not (
            isinstance(target, ast.Attribute) and _dotted(target).startswith("self.")
        ):
            return
        name = _dotted(target)
        resolved = (
            self.resolve(value.func if isinstance(value, ast.Call) else value) if value else ""
        )
        context = value is not None and self.has_context(value)
        self.symbols.pop(name, None)
        self.context_names.discard(name)
        if isinstance(value, ast.Call) and resolved in _CONSTRUCTORS:
            self.symbols[name] = "@" + _CONSTRUCTORS[resolved]
        elif isinstance(value, (ast.Name, ast.Attribute)) and resolved:
            self.symbols[name] = resolved
        if context:
            self.context_names.add(name)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self.assign(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value:
            self.visit(node.value)
        self.assign(node.target, node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.generic_visit(node)
        if isinstance(node.target, ast.Name):
            if self.has_context(node.value) or _CONTEXT.search(node.target.id):
                self.context_names.add(node.target.id)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.symbols.pop(node.name, None)
        self.context_names.discard(node.name)
        saved = self.symbols, self.context_names, self.scope, self.loop, self.retry
        self.symbols, self.context_names = dict(self.symbols), set(self.context_names)
        self.scope = f"{self.scope}/{node.lineno}"
        self.loop = 0
        self.retry = int(
            any(
                self.resolve(d.func if isinstance(d, ast.Call) else d).startswith(
                    ("tenacity.retry", "backoff.")
                )
                for d in node.decorator_list
            )
        )
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        args += [a for a in (node.args.vararg, node.args.kwarg) if a]
        locals_ = {a.arg for a in args}
        for stmt in node.body:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    locals_.add(child.id)
        for name in locals_:
            self.symbols.pop(name, None)
            self.context_names.discard(name)
        for stmt in node.body:
            self.visit(stmt)
        self.symbols, self.context_names, self.scope, self.loop, self.retry = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self.assign(item.optional_vars, item.context_expr)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncWith = visit_With

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.pop(node.name, None)
        self.context_names.discard(node.name)
        saved = self.symbols, self.context_names, self.scope
        self.symbols, self.context_names = dict(self.symbols), set(self.context_names)
        self.scope = f"{self.scope}/class{node.lineno}"
        # Common client attributes initialized directly in __init__ are visible to methods.
        # Keep them inside this class; do not infer arbitrary cross-file object types.
        for method in node.body:
            if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                for stmt in method.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Attribute) and _dotted(target).startswith(
                                "self."
                            ):
                                self.assign(target, stmt.value)
                    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Attribute):
                        self.assign(stmt.target, stmt.value)
        for stmt in node.body:
            self.visit(stmt)
        self.symbols, self.context_names, self.scope = saved

    def visit_For(self, node: ast.AST) -> None:
        if isinstance(node, (ast.For, ast.AsyncFor)):
            for target in ast.walk(node.target):
                if isinstance(target, ast.Name):
                    self.symbols.pop(target.id, None)
                    self.context_names.discard(target.id)
        self.loop += 1
        self.generic_visit(node)
        self.loop -= 1

    visit_AsyncFor = visit_For
    visit_While = visit_For
    visit_ListComp = visit_For
    visit_SetComp = visit_For
    visit_DictComp = visit_For
    visit_GeneratorExp = visit_For

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.retry += 1
        self.generic_visit(node)
        self.retry -= 1

    def visit_Call(self, node: ast.Call) -> None:
        resolved = self.resolve(node.func)
        provider, _, method = resolved.lstrip("@").partition(".")
        method = ".".join(
            part
            for part in method.split(".")
            if part not in {"with_raw_response", "with_streaming_response"}
        )
        is_model = (resolved.startswith("@") or provider == "openai") and method in _METHODS.get(
            provider, set()
        )
        if resolved in {"litellm.completion", "litellm.acompletion"}:
            provider, is_model = "litellm", True
        if is_model:
            inputs = [
                kw.value
                for kw in node.keywords
                if kw.arg in {"messages", "input", "prompt", "contents"}
            ]
            if provider.startswith("langchain-") or provider == "google-legacy":
                inputs += node.args[:1]
            provider = provider.removeprefix("langchain-").removesuffix("-legacy")
            self.calls.append(
                _Call(
                    self.path,
                    node.lineno,
                    provider,
                    self.scope,
                    _hash(ast.dump(node, include_attributes=False)) if inputs else "",
                    literal_model=any(
                        kw.arg == "model"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                        for kw in node.keywords
                    ),
                    context=any(self.has_context(value) for value in inputs),
                    loop=bool(self.loop),
                    retry=bool(self.retry),
                )
            )
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "extend"}:
            name = _dotted(node.func.value)
            if name and _CONTEXT.search(name.replace(".", "_")):
                self.context_names.add(name)
        self.generic_visit(node)


def _python(path: str, raw: str) -> tuple[list[_Call], set[str]]:
    visitor = _Python(path)
    visitor.visit(ast.parse(raw))
    for call in visitor.calls:
        call.mitigations = visitor.mitigations.copy()
    return visitor.calls, visitor.mitigations


def _ignored(path: str, rules: list[tuple[str, str]]) -> bool:
    ignored = False
    for base, pattern in rules:
        if base and not path.startswith(base + "/"):
            continue
        local = path[len(base) + 1 :] if base else path
        negate = pattern.startswith("!")
        pattern = pattern.lstrip("!").rstrip("/")
        anchored = pattern.startswith("/") or "/" in pattern
        pattern = pattern.lstrip("/")
        matches = (
            fnmatch.fnmatchcase(local, pattern)
            if anchored
            else any(fnmatch.fnmatchcase(part, pattern) for part in local.split("/"))
        )
        if matches:
            ignored = not negate
    return ignored


def discover_source(root: Path, *, read: Callable) -> SourceDiscovery:
    result = SourceDiscovery(status="complete")
    calls: list[_Call] = []
    mitigations: set[str] = set()
    entries = 0
    attempted = 0

    def inventory(path: str, status: str, reason: str, **details) -> None:
        if status == "excluded":
            result.excluded_entries += 1
        elif status == "unsupported":
            result.unsupported_files += 1
        if len(result.files) < 2000:
            result.files.append(SourceFile(path=path, status=status, reason=reason, **details))
        else:
            result.inventory_truncated = True

    def diagnostic(message: str) -> None:
        result.status = "partial"
        if len(result.diagnostics) < 30 and message not in result.diagnostics:
            result.diagnostics.append(message)

    def walk(directory: str, descriptor: int, rules: list[tuple[str, str]], depth: int) -> None:
        nonlocal entries, attempted
        if depth > MAX_DEPTH:
            diagnostic("Directory depth limit reached; source coverage is partial.")
            return
        rules = rules.copy()
        for filename in (".gitignore", ".stackwinnowignore"):
            relative = f"{directory}/{filename}" if directory else filename
            try:
                content = read(root, relative, max_bytes=32768).decode("utf-8")
                rules += [
                    (directory, line.strip())
                    for line in content.splitlines()
                    if line.strip() and not line.startswith("#")
                ]
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                diagnostic(f"{relative}: ignore file could not be read; directory skipped.")
                return
        try:
            with os.scandir(descriptor) as iterator:
                children = []
                for entry in iterator:
                    entries += 1
                    if entries > MAX_ENTRIES:
                        diagnostic("Directory entry limit reached; source coverage is partial.")
                        return
                    children.append(entry)
            for entry in sorted(children, key=lambda item: item.name):
                relative = f"{directory}/{entry.name}" if directory else entry.name
                if not relative.isprintable():
                    diagnostic("A non-printable source path was skipped.")
                    continue
                if (
                    entry.name.startswith(".")
                    or entry.name in EXCLUDED
                    or _ignored(relative, rules)
                ):
                    inventory(
                        relative,
                        "excluded",
                        "Hidden, dependency/build path, or ignore rule; directories are not traversed.",
                    )
                    continue
                if entry.is_symlink():
                    inventory(relative, "excluded", "Symbolic links are not followed.")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if attempted >= MAX_FILES or result.bytes_scanned >= MAX_TOTAL_BYTES:
                        diagnostic("Source file/byte limit reached; source coverage is partial.")
                        return
                    child = os.open(
                        entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                    try:
                        walk(relative, child, rules, depth + 1)
                    finally:
                        os.close(child)
                    continue
                if Path(relative).suffix not in SUFFIXES or relative.endswith(".d.ts"):
                    inventory(
                        relative,
                        "unsupported",
                        "No source analyzer for this file type; declarations are inspected separately.",
                    )
                    continue
                if attempted >= MAX_FILES or result.bytes_scanned >= MAX_TOTAL_BYTES:
                    diagnostic("Source file/byte limit reached; source coverage is partial.")
                    return
                attempted += 1
                try:
                    raw = read(
                        root,
                        relative,
                        max_bytes=min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - result.bytes_scanned),
                    )
                    result.bytes_scanned += len(raw)
                    source_calls, source_mitigations = (
                        _python(relative, raw.decode("utf-8-sig"))
                        if relative.endswith(".py")
                        else _javascript(relative, raw.decode("utf-8-sig"))
                    )
                    result.files_scanned += 1
                    language = (
                        "Python"
                        if relative.endswith(".py")
                        else (
                            "TypeScript"
                            if Path(relative).suffix in {".ts", ".tsx"}
                            else "JavaScript"
                        )
                    )
                    result.languages[language] = result.languages.get(language, 0) + 1
                    result.model_calls += len(source_calls)
                    inventory(
                        relative,
                        "scanned",
                        "Parsed for supported model-call and context patterns.",
                        language=language,
                        bytes_read=len(raw),
                        model_calls=len(source_calls),
                    )
                    mitigations.update(source_mitigations)
                    for call in source_calls:
                        if any(
                            part in {"test", "tests", "examples", "fixtures", "__tests__"}
                            for part in Path(relative).parts
                        ) or Path(relative).name.startswith("test_"):
                            call.mitigations.add("non-production")
                    calls.extend(source_calls)
                except (OSError, ValueError, SyntaxError, RecursionError):
                    inventory(relative, "error", "Unreadable, oversized, or unsupported syntax.")
                    diagnostic(
                        f"{relative}: unreadable, oversized, or unsupported source; skipped."
                    )
        except OSError:
            diagnostic("A source directory could not be read; source coverage is partial.")

    if os.name != "posix":
        diagnostic("Source discovery requires macOS or Linux.")
        return result
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            walk("", descriptor, [], 0)
        finally:
            os.close(descriptor)
    except OSError:
        diagnostic("Source directory could not be read.")
    result.findings = _findings(calls, mitigations)
    if len(result.findings) > MAX_FINDINGS:
        result.findings = result.findings[:MAX_FINDINGS]
        diagnostic("Finding limit reached; remaining findings omitted.")
    return result


def _findings(calls: list[_Call], mitigations: set[str]) -> list[SourceFinding]:
    findings: list[SourceFinding] = []

    def add(
        rule: str,
        group: list[_Call],
        summary: str,
        question: str,
        capabilities: list[str],
        confidence: str = "medium",
        mitigation: str = "",
    ) -> None:
        caveats = []
        if any(c.heuristic for c in group):
            confidence = "low"
            caveats.append(
                "JavaScript/TypeScript evidence uses token patterns, not type or dataflow analysis."
            )
        if any("non-production" in c.mitigations for c in group):
            confidence = "low"
            caveats.append(
                "Includes test/example source; confirm whether this pattern occurs in production."
            )
        if mitigation and mitigation in mitigations:
            confidence = "low"
            caveats.append(
                f"Existing {mitigation} tooling is imported in scanned source; check its coverage before adding another tool."
            )
        findings.append(
            SourceFinding(
                rule_id=rule,
                confidence=confidence,
                summary=summary,
                evidence=[
                    c.location("Recognized model call supporting this pattern.") for c in group[:8]
                ],
                question=question,
                capabilities=capabilities,
                caveats=caveats,
            )
        )

    for call in calls:
        if call.context:
            add(
                "source-context-assembly",
                [call],
                "A model input includes assembled context/history or a large literal.",
                "How large is this input at runtime, and is it already truncated or compressed?",
                ["context-compression", "prompt-compression", "token-optimization"],
                mitigation="compression",
            )
        if call.loop or call.retry:
            add(
                "source-call-volume",
                [call],
                "A model call appears inside a loop, comprehension, retry decorator, or exception handler.",
                "What bounds the call count, and can batching or retry limits preserve the required behavior?",
                ["spend-tracking", "response-caching"],
                mitigation="caching",
            )
        if call.literal_model:
            add(
                "source-model-choice",
                [call],
                "A model call uses a literal model choice.",
                "Should this model be configurable, or could a routing policy meet quality and latency requirements?",
                ["model-routing", "provider-gateway"],
                confidence="low",
                mitigation="routing",
            )
    repeated: dict[tuple[str, str, str], list[_Call]] = defaultdict(list)
    for call in calls:
        if call.signature:
            repeated[call.path, call.scope, call.signature].append(call)
    for group in repeated.values():
        if len(group) > 1:
            add(
                "source-repeated-input",
                group,
                "Multiple model calls in one lexical scope have the same input expressions and options.",
                "Are these inputs equal at runtime, and is reusing an earlier response valid for freshness and sampling?",
                ["response-caching", "semantic-caching"],
                confidence="low",
                mitigation="caching",
            )
    providers: dict[str, _Call] = {}
    for call in calls:
        providers.setdefault(call.provider, call)
    if len(providers) > 1:
        add(
            "source-multiple-providers",
            list(providers.values()),
            "Model calls use multiple recognized provider SDKs in the scanned source.",
            "Are provider policies shared, and would a gateway simplify routing, retries, and observability?",
            ["model-routing", "provider-gateway"],
            mitigation="routing",
        )
    production_calls = [c for c in calls if "non-production" not in c.mitigations]
    if production_calls and "evaluation" not in mitigations:
        add(
            "source-evaluation-coverage",
            production_calls[:8],
            "Model calls are visible, but no recognized evaluation-tool imports were found in scanned source.",
            "Where are these outputs evaluated for quality and regressions, including external or custom tests?",
            ["prompt-evaluation", "llm-evaluation", "model-evaluation"],
            confidence="low",
        )
    return sorted(findings, key=lambda f: (f.rule_id, f.evidence[0].path, f.evidence[0].line))


# Keep comments and string literals opaque so examples in comments/strings are not calls.
_JS_TOKEN = re.compile(
    r"(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)"
    r'|(?P<string>"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|\x60(?:\\.|[^\x60\\])*\x60)'
    r"|(?P<regex>/(?:\\.|[^/\\\n])+/[gimsuy]*)"
    r"|(?P<word>[A-Za-z_$][\w$]*)|(?P<punct>\?\.|=>|[^\s])"
)


def _javascript(path: str, raw: str) -> tuple[list[_Call], set[str]]:
    tokens = []
    line, position = 1, 0
    for match in _JS_TOKEN.finditer(raw):
        line += raw.count("\n", position, match.start())
        if match.lastgroup not in {"comment", "regex"}:
            tokens.append((match.group(), match.lastgroup, line))
        line += match.group().count("\n")
        position = match.end()
    # Tokenization is intentionally limited; balanced delimiters gate this heuristic pass.
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for i, (value, kind, _) in enumerate(tokens):
        if kind == "string":
            continue
        if value in {"(", "[", "{"}:
            stack.append(i)
        elif value in {")", "]", "}"}:
            if not stack or tokens[stack[-1]][0] != {")": "(", "]": "[", "}": "{"}[value]:
                raise ValueError("Unsupported JavaScript delimiters")
            start = stack.pop()
            pairs[start] = i
    if stack:
        raise ValueError("Unclosed JavaScript delimiters")
    closing = {end: start for start, end in pairs.items()}
    words = [t[0] for t in tokens]
    constructors: dict[str, str] = {}
    mitigations: set[str] = set()
    for i, (value, kind, _) in enumerate(tokens):
        if kind != "string":
            continue
        package = value[1:-1]
        if i and words[i - 1] == "from":
            start = i - 2
            while start >= 0 and words[start] not in {"import", ";"}:
                start -= 1
            if start < 0 or words[start] != "import":
                continue
            imported = words[start + 1 : i - 1]
            if package in _MITIGATIONS:
                mitigations.add(_MITIGATIONS[package])
            provider = {
                "openai": "openai",
                "@anthropic-ai/sdk": "anthropic",
                "@google/genai": "google",
            }.get(package)
            if provider:
                if imported and imported[0] not in {"{", "*"}:
                    constructors[imported[0]] = provider
                for name in ("OpenAI", "AzureOpenAI", "Anthropic", "GoogleGenAI"):
                    if name in imported:
                        pos = imported.index(name)
                        alias = imported[pos + 2] if imported[pos + 1 : pos + 2] == ["as"] else name
                        constructors[alias] = provider
        elif i >= 2 and words[i - 2 : i] == ["require", "("]:
            if package in _MITIGATIONS:
                mitigations.add(_MITIGATIONS[package])
            provider = {
                "openai": "openai",
                "@anthropic-ai/sdk": "anthropic",
                "@google/genai": "google",
            }.get(package)
            if provider and i >= 4 and words[i - 3] == "=":
                constructors[words[i - 4]] = provider
        elif i and words[i - 1] == "import" and package in _MITIGATIONS:
            mitigations.add(_MITIGATIONS[package])
    clients: dict[str, str] = {}
    contexts: set[str] = set()
    scopes: list[tuple[int, dict[str, str], set[str], bool, bool, dict[str, str]]] = []
    calls: list[_Call] = []
    for i, (value, kind, line) in enumerate(tokens):
        if value == "{" and kind != "string":
            # Track enclosing control blocks; low-confidence lexical evidence only.
            control = ""
            if i and words[i - 1] == ")":
                start = closing.get(i - 1, i)
                control = words[start - 1] if start else ""
            loop = (
                control in {"for", "while"}
                or (i > 0 and words[i - 1] == "do")
                or any(s[3] for s in scopes)
            )
            retry = control == "catch" or any(s[4] for s in scopes)
            scopes.append((i, clients.copy(), contexts.copy(), loop, retry, constructors.copy()))
            parameter_end = i - 2 if i > 1 and words[i - 1] == "=>" else i - 1
            if parameter_end in closing and control not in {"for", "while", "if", "switch"}:
                parameter_start = closing[parameter_end]
                for parameter in words[parameter_start + 1 : parameter_end]:
                    clients.pop(parameter, None)
                    contexts.discard(parameter)
                    constructors.pop(parameter, None)
            elif i > 1 and words[i - 1] == "=>":
                clients.pop(words[i - 2], None)
                constructors.pop(words[i - 2], None)
        elif value == "}" and kind != "string" and scopes:
            _, clients, contexts, _, _, constructors = scopes.pop()
        if kind != "word":
            continue
        if words[i + 1 : i + 2] == ["="]:
            clients.pop(value, None)
            contexts.discard(value)
            if words[i + 2 : i + 3] != ["require"]:
                constructors.pop(value, None)
            if words[i + 2 : i + 3] == ["new"] and i + 3 < len(words):
                if words[i + 3] in constructors:
                    clients[value] = constructors[words[i + 3]]
            end = i + 2
            while end < len(words) and words[end] not in {";", "\n"} and end < i + 150:
                # Don't consume a subsequent assignment on a new line in semicolon-free code.
                if (
                    end > i + 2
                    and tokens[end][2] > line
                    and words[end] in {"const", "let", "var", "return"}
                ):
                    break
                end += 1
            expression = words[i + 2 : end]
            if any(_CONTEXT.search(w) for w in expression) and any(
                w in {".", "+", "..."} for w in expression
            ):
                contexts.add(value)
        provider = clients.get(value)
        if not provider:
            continue
        j = i + 1
        method = []
        while j + 1 < len(words) and words[j] in {".", "?."} and tokens[j + 1][1] == "word":
            method.append(words[j + 1])
            j += 2
        allowed = _METHODS[provider] | (
            {"models.generateContent"} if provider == "google" else set()
        )
        if ".".join(method) not in allowed or j not in pairs or words[j] != "(":
            continue
        end = pairs[j]
        arguments = tokens[j + 1 : end]
        arg_words = [t[0] for t in arguments]
        has_input = any(w in {"messages", "input", "prompt", "contents"} for w in arg_words)
        literal_model = any(
            t[0] == "model"
            and k + 2 < len(arguments)
            and arguments[k + 1][0] == ":"
            and arguments[k + 2][1] == "string"
            for k, t in enumerate(arguments)
        )
        context = any(w in contexts for w in arg_words) or any(
            kind == "string" and len(w) >= 4002 for w, kind, _ in arguments
        )
        if any(_CONTEXT.search(w) for w in arg_words) and "join" in arg_words:
            context = True
        calls.append(
            _Call(
                path,
                line,
                provider,
                "/".join(str(s[0]) for s in scopes),
                _hash(" ".join(words[i : end + 1])) if has_input else "",
                literal_model=literal_model,
                context=context,
                loop=any(s[3] for s in scopes),
                retry=any(s[4] for s in scopes),
                mitigations=mitigations.copy(),
                heuristic=True,
            )
        )
    return calls, mitigations
