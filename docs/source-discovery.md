# Source discovery

StackWinnow scans supported source files when inspecting a project. Goals are
optional: source findings can recommend catalog tools on their own. Findings
appear in inspect/recommend JSON, terminal output, project reports, workflow
discovery, and the Inspect/Recommend web pages.

    stackwinnow inspect /path/to/project
    stackwinnow recommend /path/to/project --json
    stackwinnow recommend /path/to/project --goal "Evaluate answers"
    stackwinnow inspect /path/to/project --no-source

The Python API accepts inspect_project(path, scan_source=False) for declarations
only. No source code is imported or executed; discovery performs no network,
provider, package-manager, or Git commands and writes no project files.

## Web UI

The app opens on Discover tools. Enter the project path and choose Scan and
discover tools; no goal is required. Inspect source offers a scan-only view.
Optional refinements contain goals and assistant preferences. Saved refinements
are shown so it is clear when they affect a new scan; remove goal chips to scan
without those priorities. Source findings appear before the supporting profile
or tool list. Workflow also keeps plan goals optional.

## Findings

| Source rule | Evidence | Suggested investigation |
| --- | --- | --- |
| source-context-assembly | Local context/history assembly flowing into recognized input arguments, or a literal of at least 4,000 characters | Compression, after measuring input size and existing truncation/compression |
| source-repeated-input | Two calls in one lexical scope with the same argument expressions and options | Caching, after checking runtime equality, freshness and sampling requirements |
| source-call-volume | Calls inside loops/comprehensions, recognized Python retry decorators, or exception handlers | Batching, retry bounds and call volume; catalog suggestions cover spend tracking and caching |
| source-model-choice | A literal model argument | Configuration or routing, after checking quality/latency requirements |
| source-multiple-providers | Calls through more than one recognized SDK | Shared routing, retry and observability policy |
| source-evaluation-coverage | Model calls outside recognized test/example paths, without recognized evaluation imports in scanned files | Ask where quality/regression evaluation lives, including custom/external tests |

Every finding contains project-relative paths, 1-based lines, an explanation,
confidence, a focused question, catalog capability tags, and relevant caveats.
Recommendations carry the full finding in a reason with kind "source". They preserve
catalog eligibility and executable-mode limitations. Recommendations never select
or install tools automatically.

Confidence describes the observed pattern, not the need for another tool. Direct
Python structural observations generally receive medium; repeated expressions,
fixed models, missing visible evaluation, and all JavaScript heuristics receive
low. No finding establishes excessive cost, redundant runtime requests, absent
evaluation everywhere, or measurable savings. Existing optimization imports add
caveats; evaluation imports suppress the missing-visible-import question, without
establishing quality coverage. Imports alone do not prove that tooling is used.

## Supported source patterns

Python uses the standard-library AST, resolving SDK import aliases, straightforward
client assignments, context-manager clients, class-held clients initialized directly
in __init__, and local context expressions. It
recognizes OpenAI/Azure OpenAI chat completions and Responses create/parse/stream,
including raw/streaming response wrappers; Anthropic messages create/stream;
Google GenAI generate_content; LiteLLM completion/acompletion; legacy Google GenerativeModel; and direct
LangChain OpenAI/Anthropic/Google chat-model invoke, stream and batch calls. Async calls,
loops, comprehensions, tenacity retry/backoff decorators and exception handlers
are included. Function parameters and reassigned clients are treated conservatively.

JavaScript/TypeScript uses bounded token heuristics for OpenAI, Anthropic and
Google GenAI imports, basic CommonJS require bindings, new clients, multiline
calls, simple context assignments, and braced loops/catch blocks. Comments,
strings/templates and regex literals are opaque. Confidence is always low.
This is not a JavaScript parser or type checker; complex templates, JSX, arrow
callbacks, destructuring, expression-bodied functions and regex/division ambiguity
can be missed. Files with unbalanced supported delimiters are skipped.

Neither pass performs cross-file dataflow or proves reachability. Custom wrappers,
HTTP calls, dynamic imports, generated clients, complex aliasing, model factories,
other languages, and indirect prompt construction may be missed. Repeated source
expressions may evaluate to different values or execute on different paths.
Examples/tests remain visible but receive a production-use caveat and do not
alone trigger the evaluation-coverage question.

## File boundaries and coverage

The source_discovery object also includes a file ledger (up to 2,000 entries),
language counts, recognized model-call counts, excluded-entry/unsupported-file
counts and an inventory_truncated flag. These observations power the workbench's
Source coverage page. Filenames and scan reasons are visible; source values stay private.

- Recursive .py, .js, .jsx, .ts, .tsx, .mjs, .cjs files; .d.ts excluded.
- Hidden paths and known dependency/build directories are excluded, including
  node_modules, vendor, dist, build, coverage, venv/env and site-packages.
- Nested .gitignore and .stackwinnowignore support simple glob patterns,
  root-relative patterns, directory exclusions and ! negation within traversed
  directories. This is a conservative glob subset, not Git's full escape/globstar
  semantics; global Git excludes are not read. Excluded directories are not
  traversed or re-included. Use .stackwinnowignore for additional exclusions.
- At most 500 attempted source files, 256 KiB per file, 8 MiB source bytes,
  10,000 directory entries and depth 20. Ignore files are limited to 32 KiB each.
  At most 100 findings and 8 locations per finding are returned.
- The existing POSIX descriptor reader rejects symlinks, multiple hard links,
  special files, oversize files and files changed during a read. Directory
  traversal also refuses symlinks. No source excerpts, prompt values, model names,
  API keys or raw parser errors are included in findings.
- Paths are visible; this is not a secret detector for filenames. A scan is not
  an atomic snapshot of a changing repository.

The source_discovery status is not-scanned, complete, or partial. Complete
means the bounded supported pass finished, not that the whole project is
understood. Missing optional manifests remain valid. Unreadable/unparseable source
or reached limits produce partial coverage diagnostics, preserve available findings,
and make inspection incomplete (CLI exit 1). Unknown extensions and documented
exclusions are outside the scan. Old serialized inspections default to not-scanned.

## Validation evidence

Focused synthetic tests exercise all six rules without goals, evidence locations,
serialization, secret omission, false positives, aliases, async/retry paths, existing
mitigations, bounded reads, exclusions, partial results and CLI/report integration.
They do not call any SDK.

Two unchanged upstream SDK examples were also downloaded at pinned revisions and
statically inspected in isolated temporary directories. The [captured results](evidence/source-discovery.json)
include revision, original path, content hash and findings. OpenAI's demo exposed
the raw-response wrapper pattern, which was added; three literal model choices
were found at lines 11, 24 and 43. Anthropic's messages example yielded two at
lines 5 and 17. These narrow example scans do not establish whole-repository
coverage or validate any runtime optimization. Larger external projects remain
useful for identifying further supported patterns.
