# Example portable selections

These version 1 profiles select the current supported recipes without any local
state, source code or credentials. Import creates a reviewable plan and runs no
installation or functional check. See the [profile guide](../../docs/portable-profiles.md).

| Profile | Selected purpose | Prerequisites beyond macOS arm64 |
| --- | --- | --- |
| [local-compression.json](local-compression.json) | Headroom's fixed local compression fixture | Manager Python >=3.11 |
| [local-evaluation.json](local-evaluation.json) | promptfoo deterministic evaluation | Node 24 and npm |
| [browser-codex.json](browser-codex.json) | Playwright browser check through Codex | Node 24, npm, Codex 0.169.0 |
| [code-map-codex.json](code-map-codex.json) | Graphify relationship through Codex | CPython 3.11.5–3.11.x, macOS 14+, Codex 0.169.0 |

From the repository root, with an existing destination project:

~~~sh
stackwinnow profile import examples/profiles/local-evaluation.json /path/to/project --json > /tmp/reviewed-workflow.json
stackwinnow workflow apply /tmp/reviewed-workflow.json --dry-run --json
~~~

The Graphify example expects `sample_app/greetings.py:greet()` to call
`sample_app/names.py:normalize_name()`, as in `tests/fixtures/project`. Review
and update those portable selectors for your actual project. No profile promises
that equivalent files or relationships exist elsewhere.
