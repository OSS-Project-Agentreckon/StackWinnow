# Project inspection

`stackwinnow inspect PROJECT` reads project declarations and captures the user's
explicit intent. It also performs bounded [source discovery](source-discovery.md)
for recommendations without requiring goals. It does not
scan installed packages, execute project scripts, call providers, or determine
whether a selected tool can be installed. Implementation and tests were AI-assisted.

## CLI

```sh
stackwinnow inspect . --json
stackwinnow inspect . --goal "Reduce model calls" --goal "Evaluate answers"
stackwinnow inspect . --assistant codex --tool graphify --tool promptfoo
stackwinnow inspect . --model-preference local --config assistant-settings.json
```

The project directory must exist. Declaration parsing considers root manifests;
source discovery recursively scans supported files. Use `--no-source` for declarations only.
Long options must be written in full. Goals and tools can be repeated; tool IDs
are deduplicated in selection order and checked against the catalog. A catalog-only
tool is a valid selection, but selection gives no installation permission/readiness.
An omitted assistant or model preference stays null. Preference values are
`local`, `hosted`, and `any`; they record intent without performing model calls.

With `--config`, select a normalized project-relative `.json` path such as
`.cursor/mcp.json` or `assistant-settings.json`. The file must already exist.
Only the names of object-valued registrations under `mcpServers` are extracted.
Blank names and names with leading/trailing whitespace are rejected with a
diagnostic; valid registrations in the same file are retained.
No default assistant file is assumed and no home-directory configuration is scanned.
Command, argument, environment, URL, token, and unrelated configuration values are
not included in output. Registration presence does not prove client connectivity.

| Exit | Meaning |
| --- | --- |
| 0 | Supported inspection completed. Optional manifests may be absent; unsupported/dynamic fields may remain unknown with skipped diagnostics. |
| 1 | A requested file could not be read/parsed, or a supported field was malformed. Valid findings from other files/fields remain available. |
| 2 | Invalid arguments, project directory, configuration path, tool ID, or unavailable/invalid catalog needed to check selections. |

## Result and evidence

The CLI JSON envelope contains `schema_version: 1`, `complete`, `profile`,
`selected_tools`, `model_preference`, `diagnostics`, and `source_discovery`. Partial
source coverage makes inspection incomplete; source diagnostics and limitations
are included in the source_discovery object. Nested model schema
versions are omitted from CLI output. The Python models retain their own versions.

`profile` is the existing `ProjectProfile` contract: canonical project path,
explicit goals/assistant, observed facts, and evidence. The operating system
remains unknown because project inspection does not perform host inspection.
Project paths and evidence source paths retain significant whitespace exactly.
Each fact records its source file and field through `EvidenceRef`. Facts and
dependency names are sorted and deduplicated. Preferences never become facts.

| Fact key | Source and meaning |
| --- | --- |
| `manifests` | Successfully parsed root manifest filenames. |
| `ecosystems` | `python` or `node` based on manifest presence; this is not a claim about all source languages. |
| `python.dependencies` | Normalized distribution names parsed from `project.dependencies` using the PEP 508 parser in `packaging`. |
| `python.optional_dependencies.GROUP` | Names from each supported optional dependency group. |
| `python.requires` | Normalized PEP 440 constraint from `project.requires-python`, including prerelease and development versions. |
| `node.dependencies`, `node.devDependencies`, `node.optionalDependencies`, `node.peerDependencies` | Names from the respective root package declarations; version/URL values are omitted. |
| `node.requires` | Declared `engines.node` expression, limited to numeric version/comparator characters. It is not evaluated as a compatibility check. |
| `config.mcp_servers` | Names from the explicitly selected configuration's `mcpServers` object. |

An omitted key means unknown/unavailable, not an empty dependency set. An
explicitly empty list/object is reported as `[]`. If some declarations are invalid,
valid names are retained with a failed diagnostic; wholly invalid declarations
do not become an explicitly empty set. Python dependency extras, URL targets,
versions, and markers are not emitted; markers are not evaluated. These are
declared dependencies, including conditional ones, not installed package evidence.

Diagnostics use `OperationResult`. File/field names and actionable messages are
reported, without raw parser errors or file values. Here, `succeeded` means the
supported metadata was read, `skipped` means optional/unsupported information was
not interpreted, and `failed`/`blocked` make `complete` false. Complete inspection
does not imply complete project knowledge or validate the entire package manifest.

## Scope and limits

- Python 3.11+ is required. Initial file inspection uses POSIX descriptors and is
  supported on macOS/Linux. Other hosts return blocked file diagnostics.
- Each file is limited to **1 MiB**, including a bounded read when a file grows.
  Child symlinks, multiple hard links, directories used as files, and special files
  are rejected. The explicitly chosen project root is resolved before reading.
- The reader checks file size and timestamps before/after reading. Results are
  observations, not a multi-file transactional snapshot or reusable install approval.
- JSON must be UTF-8 with an object root, unique keys, and finite numbers.
  Comments/trailing commas are unsupported. TOML is parsed with `tomllib`.
- Node package names and Python optional-group names have bounded supported
  syntax. Unrecognized names/constraints generate diagnostics instead of exposing
  arbitrary field values. Named registrations must be printable and at most 128
  characters. Names, project paths, and explicit user goals are visible in output;
  this is not a general-purpose secret detector for those names or supplied goals.
- Python constraints are limited to 256 characters and parsed with `packaging`.
  Arbitrary equality (`===`) is supported only when its value parses as a
  PEP 440 version; arbitrary non-version strings are rejected without echoing them.
- No recursive workspace manifest scan, lockfile resolution, requirements-file expansion,
  Poetry-specific dependency extraction, or execution of dynamic build metadata.
  Unsupported structures remain unknown with an explanation. Static/dynamic
  declarations that conflict for an inspected Python field are rejected.
- No files are created in the inspected project and no scripts, provider calls,
  credential files, or host assistant discovery are invoked. Manifest/config files
  are parsed in memory; only the supported fields above are emitted.

## Python API and handoff

```python
from stackwinnow.detect import InspectionResult, inspect_project

inspection = inspect_project(
    ".",
    goals=["Evaluate answers"],
    assistant="codex",
    selected_tools=["promptfoo"],
    model_preference="local",
)
restored = InspectionResult.model_validate_json(inspection.model_dump_json())
assert restored == inspection
print(restored.profile.facts)
```

`InspectionError` reports invalid project/configuration scope or tool choice;
Pydantic `ValidationError` reports invalid typed inputs. An optional `catalog`
argument supplies a validated catalog for checking selected tools, so callers
can reuse it across inspection and recommendation. When omitted, inspection
loads the bundled catalog only if there are explicit selections. Catalog loading errors
can propagate when checking explicit selections. Ordinary file/read/parse errors
are returned as diagnostics so callers can display partial findings.

Future recommendation rules should consume `profile` and explicit preferences,
respect incomplete diagnostics, and use catalog eligibility independently. Do
not convert a parsed manifest, user selection, or a registration name into an
adapter-registration or prerequisite-success claim. Runtime inspection remains
available separately in `stackwinnow.runtime`.

## Validation

Inspection tests reuse isolated fixture projects and cover Python/Node/mixed/empty
projects, dependency groups, dynamic metadata, explicit intent, partial failures,
sanitized output, file boundaries, and read-only behavior. Installed CLI tests
run outside the checkout and verify JSON shape and exit statuses. No actual
agent, model provider, or package installation is involved in these scenarios.
