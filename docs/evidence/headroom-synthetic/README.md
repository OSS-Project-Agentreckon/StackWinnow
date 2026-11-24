# Historical synthetic compression measurements

Captured 23 November 2026; published here without rerunning the experiment.
This is separate from the managed lifecycle in [headroom-library.md](../headroom-library.md).
`summary.json` is the unchanged recorded summary; inputs and output messages
are the original synthetic files. Its source hashes identify the original local
experiment scripts, not scripts distributed with this snapshot.

| Fixture | Before (tokens) | After (tokens) | Saving |
| --- | ---: | ---: | ---: |
| Protected short control | 282 | 282 | 0% |
| Pretty JSON | 5,105 | 1,980 | 61.21% |
| Equivalent compact JSON | 3,276 | 1,980 | 39.56% |
| Protected error text | 1,241 | 1,241 | 0% |

Two trials per fixture used Headroom 0.44.0, Python 3.11.14, macOS arm64,
warm tokenizer caches and fresh processes. `gpt-4o` selected the tokenizer only;
no model was called. Compression disabled the optional Kompress model and
otherwise used upstream defaults. A socket audit hook blocked network attempts;
none were recorded. Existing runtime fingerprints remained unchanged.

The JSON contains 100 passing records and one failure. Recorded analysis checked
all fields of all 101 records and summary counts, the system instruction and
the complete critical failure line. This is fixture-specific preservation, not
a general semantic guarantee. Upstream did not assert losslessness.

Always show the compact baseline and zero-saving controls alongside pretty JSON.
Counts are **tokens, not characters**. These are direct-library observations, not
current-release acceptance, arbitrary-project savings, setup-time or dollar-cost
benchmarks. New measurements and a human manual-versus-managed setup comparison
remain deferred. The snapshot
allows inspection of prior results without claiming fresh reproduction.

## Optional future reproduction

The new parameterized runner uses the existing pinned Headroom interpreter and
copies a warm tokenizer cache into a disposable directory. It installs nothing.
Run each fixture in a fresh process with a new output directory:

```sh
/path/to/headroom/python/bin/python -I -B scripts/measure_headroom.py \
  docs/evidence/headroom-synthetic/older_tool_compact_json_results.input.json \
  /tmp/headroom-compact-trial1 --tokenizer-cache /path/to/warm/tiktoken
```

Repeat for all four inputs and retain both trials, including failures and controls.
The output contains messages, token counts, hashes and preservation diagnostics.
The Python socket hook blocks ordinary network attempts; it is not an OS sandbox.
This runner does not repeat the original full field-by-field table analysis or
runtime inventory fingerprint; it checks system messages, the fixture failure
line and count arithmetic. It is a new reproduction aid, not the original script
identified by the historical summary. Only syntax/lint/help were checked during
this handoff; actual compression execution remains deferred.
