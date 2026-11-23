# Support and validation scope

The manager requires Python >=3.11. Linux Python 3.11/3.14 CI covers portable unit
behavior and packaging; it is not evidence of Linux tool integration support.
The executable workflow registry, not catalog membership, defines setup support.

| Tool / mode | Pinned upstream release | Supported integration target |
| --- | --- | --- |
| Headroom / library | 0.44.0 | macOS arm64; fixed local compression fixture |
| promptfoo / deterministic | 0.125.1 | macOS arm64; Node 24/npm; local evaluation fixture |
| Playwright MCP / Codex | 0.0.86 | macOS arm64; Node 24/npm; Codex 0.169.0; downloaded browser |
| Graphify / Codex | 0.9.114 | macOS >=14 arm64; CPython >=3.11.5,<3.12; Codex 0.169.0 |

The captured Node version is 24.13.1. Actual Codex verification uses a scripted
loopback provider, not paid inference. Catalog-only tools have no supported adapter.
Headroom's supported manager fixture measured zero savings; no arbitrary-project
cost reduction is promised. All direct pins have the dependency limitations in
[the reference inventory](../licenses/reference-2026-11-23/README.md).

Foundation acceptance at 2a4f3b8 established four narrow actual tool lifecycles.
A02 added two actual workflow smokes; A03 covered pure CLI profile round-trips.
Those earlier measurements do not establish final combined profile acceptance.
A04's final full/installed suites, A05 combinations, fresh dependency inventories,
new benchmarks and final release acceptance are deferred at the user's request.
A06 prepares packaging/CI; a successful build is not end-to-end product acceptance.
See [implementation-progress.md](implementation-progress.md) for revision-bound evidence.
