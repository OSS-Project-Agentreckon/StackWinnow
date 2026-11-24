# Local project workbench

Run the UI from a source checkout with Python 3.11+ and Node/npm:

    python -m pip install -e '.[ui]'
    npm --prefix ui/frontend ci
    python scripts/run_ui.py

Open http://localhost:5173. Ctrl+C stops the two processes started by the launcher.
The launcher uses this checkout's Python source, refuses occupied ports, and binds
the servers to localhost. Alternatively run uvicorn ui.api:app on port 8000 and
npm run dev from ui/frontend on port 5173. Refresh the browser after restarting
the backend; review plans expire after one hour or a backend restart.

## What each page does

| Page | Available behavior |
| --- | --- |
| Discovery | Scan without goals; review source findings, recommendations, declarations, diagnostics and unmatched goals; select managed tools |
| Source coverage | Search the recursive file ledger; distinguish analyzed files, excluded entries, unsupported file types and read/parse errors; inspect counts, recognized calls and scan limits |
| Tool catalog | Search/filter all reviewed entries; compare capabilities, license scope, alternatives, prerequisites and assistant/platform compatibility; distinguish catalog entries from executable modes |
| Manage tools | Select the four registered modes; provide Graphify relationship expectations; prepare/download a setup plan; validate a dry run; explicitly apply it; read passive status; explicitly run functional checks; prepare/review/apply removal |
| Portable profiles | Export from a reviewed workflow plan; upload/paste a portable profile and generate a new plan for the destination project |
| Project report | Generate a fresh Markdown/JSON report using current scan options and selections; preview and download it |
| Environment | Inspect actual local runtime facts and compare them with exact registered-mode requirements |

Project choices are shared across pages. Changing the project clears prior scan
and plan state. Changed goals/config/scope require a rescan; the UI marks older
findings. Assistant/platform changes refresh catalog compatibility separately.
Profile imports populate the selected modes and profile preferences for review.

## What assistant selection means

The selector lists actual catalog identifiers: codex, claude-code, cursor, aider,
gemini-cli, github-copilot and opencode. It selects a compatibility target, not a
model that performs the analysis. Source findings are deterministic for the same
source. Two assistants with the same documented compatibility can correctly
produce the same gates. Managed client integrations currently configure Codex;
the UI calls out other selected targets before setup.

## What scanning means

The live backend was checked against a source-only project with no manifests:
it returned one scanned Python file, one recognized model call and four source
findings, matching the direct Python API. The previous UI obscured this distinction
by emphasizing manifest facts and not exposing file coverage. The new file ledger
shows what the recursive pass actually inspected, including files with no matches.

Coverage remains bounded to the languages/patterns in [source discovery](source-discovery.md).
Declarations are still read separately. An entry marked unsupported in the source
ledger may be a manifest inspected by the declaration parser. Excluded directory
counts are entry counts, not counts of all files below them. The ledger displays
up to 2,000 entries and exposes truncation. Complete means the supported scan
finished; it does not mean every language or every behavior is understood.

## Execution and validation

Setup/removal uses server-retained, expiring review IDs. The browser cannot submit
arbitrary executable plan documents. Application requires an explicit confirmation,
a local-session action token and an unattempted plan; the core lifecycle functions
revalidate project state and recipes. Cross-origin/foreign-host requests are rejected.
A dry run does not consume the application attempt. This is a local workbench,
not an authenticated remote multi-user service.

Validation for this follow-up: 178 relevant tests in total (32 source/API cases
and 146 existing detection/recommendation/report cases), production UI build,
Python lint/format and diff checks. Live Chromium checks exercised a goal-free scan,
file coverage, tool selection, plan creation, application disabled before review,
a real dry run, report generation, assistant selection and mobile width. Desktop
and mobile screenshots were inspected. Tests cover apply/removal/check API gates
with stub executors; no real installs/removals/provider calls were performed for
this UI change. Two installed test-dependency deprecation warnings were observed.
Full lifecycle/release acceptance remains deferred.
