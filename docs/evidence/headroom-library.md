# Headroom library acceptance evidence

Recorded 23 November 2026 against implementation commit `c6b7e8a`, on macOS
arm64 with Python 3.11.14. [Machine-readable evidence](headroom-library.json)
records the exact distribution versions, report identities, fixture and
installation hashes, tokenizer cache hash, and measured token counts.

## Real lifecycle

```sh
python -m pytest tests/integration/test_headroom.py --run-integration \
  --basetemp=/private/tmp/stackwinnow-headroom-acceptance -q
```

Result: **1 passed in 429.32 seconds**. This duration covers the entire test,
including installation and repeated complete inventory checks; it is not an
installation or compression benchmark. The first restricted-network attempt
failed during pip installation and retained its created roots. The successful
run used authorized network access in a fresh temporary fixture.

| Observation | Actual result |
| --- | --- |
| Missing installation | Shared functional check blocked, no state created |
| Plan and dry-run | No managed project files created |
| First apply | Installed Headroom 0.44.0 and passed fixture compression |
| Passive shared check | Installed/configured succeeded; connected not applicable; functionality not run |
| Fresh shared check | Ready, with new compression evidence |
| Negative validation control | Failed after the actual fresh command, as requested |
| Fresh plan/reapply | Reused the current runtime, then passed new compression |
| Replaying the attempted plan | Blocked |
| User file | Unchanged throughout |

All three successful compression reports recorded **282 tokens before, 282
after, and 0 saved**, with two input and output messages. The exact system
instruction and full timeout failure survived. The short protected fixture
therefore proves successful execution and preservation, not AI cost savings.
No assistant connection or provider usage is claimed.

The runtime inventory contains 20,492 files and the health record lists 70
installed distributions. The explicit tokenizer cache contains one 3,613,922-byte
vocabulary file. `gpt-4o` selects `o200k_base`. Repeat runs used the same managed
runtime and cache; no claim of network-free execution was inferred from this
observation. The full dependency versions and cache digest are in the JSON.

Metadata and candidate license files were captured for all 70 installed
distributions in the local release-audit workspace. Capture is not a completed
license audit. Dependency locking and license closure remain A06 work.

## Local verification

- Rebuilt wheel/sdist succeeded; the installed package passed 1,098 default
  tests with warnings as errors and 13 opt-in skips.
- The final verification selection passed 35 tests, including two subsequently
  added regressions proving that altered system instructions or incomplete
  failure text are rejected by the executed fixture script.
- Python 3.14.4 passed 104 focused adapter/CLI/verification/removal tests.
- Ruff lint and formatting, dependency checks and Git whitespace checks passed.

The ordinary sandbox blocked two pre-existing localhost fixture tests; rerunning
the rebuilt-package suite with localhost access passed. No hosted CI result or
merge is asserted by these local results. Coordinated removal and the complete
four-tool foundation handoff are still separate milestones.
