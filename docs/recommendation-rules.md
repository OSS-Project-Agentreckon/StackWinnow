# Explainable recommendations

The recommendation command reads the supported project declarations and matches
explicit goals to catalog capabilities. It runs offline, makes no model calls,
and performs no installation. Implementation and tests were AI-assisted.

```sh
stackwinnow recommend . --goal "Understand relationships across source files"
stackwinnow recommend . --goal "Evaluate answers" --tool promptfoo --json
stackwinnow recommend . --goal "Reduce context tokens" --model-preference local
stackwinnow recommend . --goal "Build agent workflows" --platform macos --assistant codex
```

The command accepts the same intent and configuration flags as
[`inspect`](project-inspection.md), plus `--platform macos|linux|windows`.
The platform is a user-declared target; this command does not inspect the host.

## Matches and ordering

Three sources can explain a tool:

1. **Explicit selection:** `--tool` retains a catalog entry even without a goal
   match. Selections appear first, in the user's order, with duplicates removed
   from the candidate list. Nothing is installed or selected automatically.
2. **Declared dependency:** an exact package-name alias matches a catalog entry.
   These candidates appear next, to favor reuse of existing framework choices.
   A declaration, including an optional/dev dependency or conditional Python
   requirement, does not establish that the package is installed or active.
3. **Goal phrase:** supported phrases match catalog capability tags. Within the
   declared and goal-only groups, tools matching more distinct goal rules come
   first; ties use tool ID. Repeating a phrase does not increase its weight.

Each reason includes its rule ID and either the matched goals or the fact key
and package names. Goal reasons also include sorted `matched_capabilities` from
the tool's catalog entry; selection/dependency reasons leave this list empty.
For example, Headroom matches `context-compression` and `token-optimization`,
while Langfuse matches `spend-tracking` for a monitoring goal.
The accompanying inspection retains source-file evidence and
diagnostics. No arbitrary confidence percentages or estimated savings are used.

## Goal rules (version 1)

| Rule | Recognized phrases | Catalog capability tags |
| --- | --- | --- |
| Code navigation | code navigation; navigate code; understand codebase; understand the codebase; code relationships; relationships across source files; code indexing; refactoring | code-navigation, symbol-search, code-relationships |
| Evaluation | evaluation; evaluate answers; evaluate prompts; evaluate models; evaluate outputs; evaluate model outputs; model comparison; prompt testing | prompt-evaluation, llm-evaluation, model-evaluation, agent-evaluation |
| Retrieval evaluation | rag evaluation; evaluate retrieval; evaluate rag | rag-evaluation |
| Broad cost optimization | reduce cost; reduce costs; lower cost; lower costs; cost optimization/optimisation | token-optimization, context-compression, response-caching, model-routing, spend-tracking |
| Context compression | reduce tokens; reduce token usage; reduce context tokens; token optimization/optimisation; context compression; compress context; prompt compression; compress prompts | token-optimization, context-compression, prompt-compression |
| Response caching | reduce model calls; response caching; cache responses; semantic caching | response-caching, semantic-caching |
| Spend monitoring | track costs; track spending; monitor costs; monitor spend; spend tracking | spend-tracking |
| Model routing | model routing; route models; provider gateway | model-routing, provider-gateway |
| Agent workflows | agent orchestration; agent workflows; multi agent; build agents | agent-orchestration, typed-agents, code-agents |

Matching is case-insensitive and uses whole phrases after Unicode normalization
and punctuation handling. Common smart apostrophes are normalized before
tokenizing contractions. Hyphens may join words of a supported phrase, such as
`code-navigation` or `cost-optimization`. A word inside another compound does
not match on its own: `re-evaluation` and `evaluation-driven` remain unmatched.
Negation checks also inspect hyphen-separated words. This is a small English
phrase matcher, not natural-language inference.
Goals containing `no`, `not`, `never`, `avoid`, `without`, `unless`,
or `if` are conservatively left unmatched, as are `cannot` and negative
contractions ending in `n't` (including don't, don’t, won't, can't, and shouldn't).
Use a short positive goal and separate preference/selection flags for these cases.
An unmatched goal is returned explicitly. A Python/Node manifest alone does not
imply a need for an AI framework. Empty/unsupported projects may produce no match.

Compression, caching, routing, and spend measurement offer different ways to
investigate cost. Broad cost goals consider all these approaches, while specific
goals match only the relevant capability tags: `Compress context` suggests
Headroom/LLMLingua; `Reduce model calls` suggests GPTCache. Manually selected or
already declared tools still appear with their respective reasons, even without
a goal match. Recommendations include catalog limitations; savings,
model quality, compatibility, and provider access still require measurement.

## Dependency aliases

Python dependency names are normalized by inspection before exact matching.
The initial aliases are deliberately explicit:

| Python distribution names | Catalog tool |
| --- | --- |
| graphifyy | graphify |
| dspy, dspy-ai | dspy |
| langchain, langchain-core | langchain |
| llama-index, llama-index-core | llama-index |
| haystack-ai | haystack |
| pydantic-ai, pydantic-ai-slim | pydantic-ai |
| autogen-agentchat | autogen |
| gptcache, deepeval, inspect-ai, langgraph, crewai, smolagents, ragas, trulens, litellm, llmlingua, langfuse, openlit, opik | Same-named tool |

Node aliases: `promptfoo` → promptfoo, `@playwright/mcp` → playwright-mcp,
and `langfuse` → langfuse. All four supported Node dependency groups and Python
optional dependency groups are considered. Arbitrary package-name substrings
and MCP registration labels are not mapped to tools. This mapping does not
claim support for every package or integration in the catalog.

## Preferences, relationships, and readiness

Manual choices remain visible even when they conflict. Alternatives are options
to compare, not incompatibilities. Relationship pairs are deduplicated and show
only tools present in the result; each entry also lists its full catalog
alternatives for further discovery. Explicitly selected conflicts feed the
existing eligibility checker. Two unselected suggestions are never treated as
an approved combined installation. The current bundled catalog has no explicit
conflicts; tests use synthetic reciprocal conflicts to verify this behavior.

The local/hosted preference is retained in the inspection. The catalog currently
has no structured, reviewed model-backend support matrix, so either preference
produces `model_preference_status: "unverified"` and an explanation. It does not
silently filter or label tools as compatible. `any` means unrestricted; an omitted
preference means not requested. In particular, promptfoo's deterministic fixture
is not proof of compatibility with a local language model.

Eligibility comes from the existing catalog API. The command does not invent
adapter registration or prerequisite results. All entries currently remain
catalog-only while runner integration is pending, including promptfoo. A
recommendation is not an executable plan, setup approval, or functionality check.

Project inspection does not infer a target OS from the machine running the CLI.
Supply `--platform macos`, `--platform linux`, or `--platform windows` when known.
Without it, a CLI recommendation retains an unknown target and includes the
`platform-unknown` eligibility blocker. Python callers can supply profile
`facts["os"]` or `operating_system` evidence; the latter is a fallback when OS
facts are absent or empty. An explicit `platform` argument takes precedence,
without changing the input profile. This keeps host and project targets separate.

## Output and Python API

JSON has one envelope `schema_version` and a separate `rules_version`. It contains
the inspection, target platform, ordered recommendations, relationships,
unmatched goals, preference status, notes, and `complete`. Nested schema versions
are omitted by the CLI; Python models retain their versions.

- Exit 0: inspection completed, including no-match or unavailable-tool results.
- Exit 1: inspection was incomplete; valid findings and goal matches remain visible.
- Exit 2: invalid request or unavailable/invalid catalog.

```python
from stackwinnow.detect import inspect_project
from stackwinnow.recommend import RecommendationResult, recommend_tools

inspection = inspect_project(".", goals=["Evaluate answers"], selected_tools=["promptfoo"])
result = recommend_tools(inspection, platform="macos")
restored = RecommendationResult.model_validate_json(result.model_dump_json())
assert restored == result
print(result.recommendations[0].reasons)
```

The API can accept an already validated `Catalog` for offline scenarios. The CLI
loads one catalog and shares it with inspection and matching. Explicit
selections absent from it raise `RecommendationError`. The input inspection is
copied/revalidated; neither it nor the catalog is mutated. Catalog file errors
remain `CatalogError`, and invalid typed inputs can raise Pydantic validation errors.

When extending rules, document capability tags and exact aliases, preserve
existing selections and unknowns, and add contrasting scenario tests. Runtime
proof and adapter availability must come from their owning components.
