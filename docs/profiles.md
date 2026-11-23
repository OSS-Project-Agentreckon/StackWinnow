# Portable profiles

`stackwinnow profiles export` captures a project's reproducible tool selections
and declared intent as a schema-versioned artifact, and `stackwinnow profiles
import` re-plans those selections in another project. A portable profile holds
the user's explicit goals, assistant, model preference, and chosen tools plus
catalog-derived compatibility metadata. It deliberately excludes machine-specific
state and secrets. Export and import run offline, make no model calls, install
nothing, and never write to the inspected project. Implementation and tests were
AI-assisted.

## CLI

```sh
stackwinnow profiles export . --goal "Evaluate answers" --tool promptfoo --json > profile.json
stackwinnow profiles export . --tool promptfoo --model-preference local --platform macos
stackwinnow profiles import profile.json ./other-project --json
stackwinnow profiles import profile.json ./other-project --platform linux
```

`export` accepts the same intent and configuration flags as
[`inspect`](project-inspection.md)/[`recommend`](recommendation-rules.md)
(`--goal`, `--assistant`, `--tool`, `--model-preference`, `--config`), plus
`--platform` to record a declared target. Without `--json` it prints a human
summary; with `--json` it emits the saveable profile. Long options must be
written in full.

`import` takes a saved `profile_file` and a target `project_root`. It re-inspects
the target with the profile's intent and prints recommendations in the same shape
as `recommend` (human or `--json`). `--platform` overrides the profile's recorded
`target_platform`. Importing selects and explains tools; it performs no
installation, configuration, or provider calls.

| Exit | Meaning |
| --- | --- |
| 0 | Export succeeded, or import re-planned the target (including no-match results). |
| 1 | Import re-inspection was incomplete; valid findings and matches remain visible. |
| 2 | Invalid arguments, unreadable project/profile file, malformed or incompatible profile, or a selected tool absent from the catalog. |

## Portable profile schema

The artifact carries one envelope `schema_version` (currently `1`). Fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Profile format version; a different value is rejected on import. |
| `stackwinnow_version` | The StackWinnow version that produced the profile, recorded for compatibility. |
| `goals` | The user's explicit goals, preserved as declared intent. |
| `assistant` | The selected assistant ID, or null when unknown. |
| `model_preference` | `local`, `hosted`, `any`, or null when not requested. |
| `target_platform` | Declared target OS (`macos`/`linux`/`windows`), or null. Compatibility context, not a host scan. |
| `tools` | Selected tools, each with `tool_id`, `name`, `category`, `license`, `availability`, an optional tested `version`, and the catalog's documented `supported_platforms`/`supported_assistants`. |
| `notes` | Optional free-text notes. |

A `version` is recorded only when a tested version is explicitly supplied; the
CLI does not invent or measure versions, so it exports `null`. `availability`
reports the catalog's adapter status (`catalog_only`/`adapter_available`); it is
not proof of installation or functional readiness. Empty documented
platform/assistant lists mean unknown compatibility.

### Excluded from the artifact

To keep profiles safe to share and free of private or machine-specific state,
the model has **no** field for any of the following, so they can never be
exported:

- the project path (`project_root`),
- observed dependency facts and ecosystem/manifest details (`facts`),
- source-file evidence (`evidence`),
- inspection diagnostics,
- configuration values, credentials, environment variables, tokens, or URLs.

Only the names the user typed (goals) and the IDs they selected, together with
public catalog metadata, are exported. Supply a short positive goal rather than
embedding paths or secrets in goal text.

## Scope and limits

- Python 3.11+ is required. Export inspects the project through the existing
  bounded, read-only [`inspect`](project-inspection.md) reader (macOS/Linux),
  so the same manifest size and file-safety limits apply.
- Export records explicit selections and declared intent only; project
  completeness does not affect a successful export.
- Import re-inspects the target project fresh; it does not copy the source
  project's observed facts. Selections are re-validated against the current
  catalog, so a profile exported against a newer catalog may reference tools the
  importing catalog lacks and will fail clearly.
- No installation, configuration write, removal, provider call, or
  coding-assistant connectivity is performed or implied.

## Python API

```python
from stackwinnow.detect import inspect_project
from stackwinnow.profiles import PortableProfile, export_profile, import_profile, replan_profile

inspection = inspect_project(".", goals=["Evaluate answers"], selected_tools=["promptfoo"])
profile = export_profile(inspection, platform="macos")

restored = PortableProfile.model_validate_json(profile.model_dump_json())
assert restored == profile

recommendation = replan_profile(profile, "./other-project")
print(recommendation.recommendations[0].tool_id)
```

`export_profile` accepts an optional validated `Catalog`, a target `platform`,
and a `tool_versions` mapping for recording tested versions. `import_profile`
raises `ProfileError` for malformed or incompatible JSON with a fixed message
that does not echo file contents. `replan_profile` propagates
`stackwinnow.detect.InspectionError` and `stackwinnow.recommend.RecommendationError`
for an invalid project or an uncatalogued tool. The input inspection and catalog
are not mutated.

## Verification

Profile tests live in `tests/test_profile_portability.py` and cover export JSON
and human output, Pydantic round-trips, export in a path with spaces, exclusion
of project paths/facts/evidence/secrets, export → import re-planning in a second
fixture project, a `--platform` override, and exit-2 handling for missing files,
malformed/unknown-field/wrong-version profiles, and uncatalogued tool selections.
They run offline with no installation or provider calls. See
[testing](testing.md) for fixtures and commands.
