# StackWinnow Interactive Installation Wizard — Design Spec

**Date:** 2026-11-25
**Command:** `stackwinnow wizard PROJECT [--goal GOAL ...]`
**Status:** Approved, ready for implementation

---

## Overview

A new `wizard` subcommand that walks the user through selecting and installing AI tools
for their project via an interactive CLI menu. The wizard inspects the project, groups
recommended tools by category, asks the user to select tools from each category, then
installs the selection with per-step progress output.

Target audience: developers who want guidance rather than the noninteractive
`workflow plan → apply` two-step flow.

---

## Architecture

Three files, following the same pattern as `workflow_cli.py` / `library_cli.py`:

| File | Purpose |
|------|---------|
| `src/stackwinnow/wizard.py` | All wizard logic — inspection, category grouping, interactive loop, batching, plan + apply |
| `src/stackwinnow/wizard_cli.py` | Argparse registration, `wizard_command()` entry point |
| `src/stackwinnow/cli.py` | Register the `wizard` subcommand (one import + one `add_wizard_parser` call) |

The wizard calls internal Python APIs only — no subprocess calls, no new dependencies.
APIs used: `inspect_project`, `recommend_tools`, `plan_workflow`, `apply_workflow`
(all already used by `workflow_cli.py`).

---

## Command Interface

```
stackwinnow wizard PROJECT [--goal GOAL ...]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `PROJECT` | (required) | Absolute or relative path to the project directory |
| `--goal` | `evaluation`, `track costs`, `compress context`, `model routing` | Goals to pass to the recommender; repeat for multiple. These four defaults cover all 11 tools verified against the SAP Concur POC. |

---

## Default Goals

The four default goals and what they unlock:

| Goal | Capabilities matched | Tools surfaced |
|------|---------------------|----------------|
| `evaluation` | prompt-evaluation, llm-evaluation, model-evaluation, agent-evaluation | DeepEval, Inspect AI, Opik, promptfoo, Ragas, TruLens |
| `track costs` | spend-tracking | Langfuse, OpenLIT, LiteLLM |
| `compress context` | context-compression, token-optimization, prompt-compression | Headroom, LLMLingua |
| `model routing` | model-routing, provider-gateway | LiteLLM |

---

## Category Grouping

The wizard groups `RecommendationResult` items by their catalog `category` field.
Display order is fixed:

1. Observability
2. Evaluation
3. Context Compression (catalog value: `context`)
4. Model Routing (catalog value: `model-gateway`)

Any category not in this list (e.g. `orchestration` if goals expand) is shown last
under its raw catalog name, capitalised.

`promptfoo` has `adapter_available` status but uses a `deterministic` executable mode,
not `library`. It is excluded from the wizard's install flow and shown as a note at the
end: `"promptfoo is available via 'stackwinnow promptfoo' — not installed by this wizard."`

---

## Batching

`WorkflowRequest` enforces `max_length=4`. The wizard never surfaces this constraint
to the user. Instead it silently splits the selection into ordered batches of ≤ 4 and
runs them sequentially:

- 1–4 tools selected → 1 round
- 5–8 tools selected → 2 rounds
- 9–10 tools selected → 3 rounds

Each round runs `plan_workflow` + `apply_workflow` independently.
If a round fails mid-install, the wizard marks failing tools with `✗`, reports the
error inline, and proceeds to the next round.

---

## Screen Layout

### Stage 1 — Header + Inspect (automatic)

```
╔══════════════════════════════════════════════════╗
║        StackWinnow — Installation Wizard         ║
╚══════════════════════════════════════════════════╝

Project : /path/to/project
Scanning project and loading recommendations...

Found N tools across M categories.
```

### Stage 2 — Category Menus (one per category, user picks)

```
──────────────────────────────────────────────────
 1 / 4  OBSERVABILITY
 Trace LLM calls, track spend, monitor AI performance
──────────────────────────────────────────────────
  a) Langfuse    — Collect traces, track usage, manage prompt workflows
  b) OpenLIT     — OpenTelemetry-based agent call observability
  c) Opik        — Trace AI apps, run evaluations over datasets

  Select (a / a,b / all / skip):
```

### Stage 3 — Selection Summary + Confirm

```
──────────────────────────────────────────────────
 Your selection (N tools)
──────────────────────────────────────────────────
  ✓ Langfuse       Observability
  ✓ DeepEval       Evaluation
  ...

Proceed with installation? [y/n]:
```

If the user enters `n`, all selections are cleared and the wizard re-enters Stage 2 from the first category.

### Stage 4 — Install (per-step progress)

```
──────────────────────────────────────────────────
 Installing — Round 1 of 2
──────────────────────────────────────────────────
  Langfuse  [1/2] Creating venv and installing langfuse@5.2.0...
  Langfuse  [2/2] Verifying import...                            ✓
  DeepEval  [1/2] Creating venv and installing deepeval@4.3.5...
  DeepEval  [2/2] Verifying import...                            ✓
  ...
```

Step descriptions come from the plan's `installation.steps[i].description` field —
the wizard does not hard-code them. Because `apply_workflow` runs synchronously
and returns a `WorkflowResult` only after all steps complete, the wizard prints each
step's description line *before* calling apply for that round, then overlays the
✓ / ✗ result on the same lines after the call returns. This means the per-step lines
appear as a block before the round runs, then update in place using `\r` carriage
returns, giving the appearance of live progress without requiring a streaming API.

### Stage 5 — Results

```
──────────────────────────────────────────────────
 Results
──────────────────────────────────────────────────
  ✓ Langfuse    installed
  ✗ DeepEval    failed — ImportError: No module named 'deepeval'
  ✓ Ragas       installed

2 of 3 tools installed. Run 'stackwinnow check PROJECT' to verify anytime.
```

---

## ANSI Formatting (stdlib only, no new dependencies)

| Element | Code |
|---------|------|
| Bold heading | `\033[1m` |
| Green ✓ | `\033[32m✓\033[0m` |
| Red ✗ | `\033[31m✗\033[0m` |
| Cyan category name | `\033[36m` |
| Reset | `\033[0m` |

All ANSI codes are emitted only when stdout is a TTY (`sys.stdout.isatty()`).
When piped or redirected, plain text is used.

---

## Error Handling

| Situation | Behaviour |
|-----------|-----------|
| Invalid selection input (e.g. `z`) | Re-prompt: `"Invalid — enter letters from the list, 'all', or 'skip':"` |
| 0 tools selected across all categories | `"Nothing selected. Exiting."` — clean exit, return code 0 |
| `plan_workflow` raises `WorkflowError` | Print error clearly, exit before any install begins, return code 1 |
| Install step fails mid-round | Mark tool `✗`, print error inline, continue remaining tools in the round and subsequent rounds |
| User enters `n` at confirm | Re-enter category menus from Stage 2 |

---

## Tests

File: `tests/test_wizard.py`

| Test | What it covers |
|------|---------------|
| `test_category_grouping` | Mock `RecommendationResult` → correct category → tools mapping in display order |
| `test_selection_parsing_valid` | `"a,c"` → correct tool IDs; `"all"` → all tools; `"skip"` → empty list |
| `test_selection_parsing_invalid` | `"z"` and `"a,z"` both return `None` (signals re-prompt) |
| `test_batch_splitting` | 7 tools → `[[t1,t2,t3,t4], [t5,t6,t7]]`; 4 → `[[...4]]`; 1 → `[[t1]]` |

---

## Out of Scope

- JSON output mode (`--json`) — wizard is interactive only
- `promptfoo` install through the wizard — it uses a separate command
- Graphify — requires an `--expectation` file; not suitable for interactive selection
- Removal — handled by `stackwinnow remove`
- Windows / Linux — wizard targets macOS arm64, same as all other wizard-surfaced modes
