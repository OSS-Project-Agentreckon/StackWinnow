# Coordinated removal validation

Recorded 23 November 2026 on macOS arm64, Python 3.11.14. The implementation
through commit `1c22568` comprises durable release state (`7c56cfb`), the removal
engine and CLI (`1df0f9c`), and adapter reinstall support (`1c22568`).

| Check | Observed result |
| --- | --- |
| Rebuilt wheel installed in a dedicated environment; default suite with `-W error` | 1,137 passed, 13 opt-in skips, 43.67 seconds |
| Removal/configuration/classifier selection on Python 3.14.4 with `-W error` | 97 passed |
| New removal tests within those suites | 37 cases, including six adapter command-double cases |
| Ruff 0.17.6 lint | Passed |
| Ruff formatting for project content | 115 files passed; unrelated untracked `docs/superpowers/` excluded and preserved |
| Dependency compatibility and Git whitespace | Passed |
| Wheel and source-distribution build | Succeeded; existing setuptools data-package discovery warning remains for A06 |

The full suite used an installed wheel without `PYTHONPATH`. The Python 3.14
selection used the source tree. The isolated environments and artifacts were
created under `/private/tmp/stackwinnow-b07-*`; these are test artifacts, not a
published release. Local socket access was enabled for existing fixture tests.

Coverage includes all four fixed runtime scopes; actual filesystem deletion;
retained graphs/reports/cache state; unchanged, modified and foreign settings;
both Codex tables sharing one file; aliases and retained evidence descendants;
cross-tool and failed ownership; forged/stale plans and swapped parents; bounded
growing-file reads; partial configuration and runtime failure; fresh continuation;
harmless repeat; deliberate reinstall; replaced retained directories; and refusal
to adopt a user-modified restored promptfoo file.

The four adapter cases use command doubles. They establish composition with
the installation/configuration APIs, not actual upstream installation or client
functionality. Real pinned-tool lifecycle acceptance belongs to the next B08/A01
handoff. The 13 default skips comprise explicit real-integration/provider and
packaging checks. No hosted CI result or merge is asserted here.

The first full run had 1,135 passes and one failure because an added global
constructor validation rejected an existing intentionally corrupt test fixture
before its reader was exercised. The unnecessary constructor tightening was
removed; bounded removal readers still reject duplicates, now with a dedicated
regression. The final results above include that repair.
