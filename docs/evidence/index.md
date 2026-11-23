# Evidence index

This index points to published evidence files. Each entry records what was
tested, by whom, and under what conditions. Evidence files record actual
command outputs and are not forward-looking acceptance claims.

## Foundation and tool lifecycle evidence

| File | Contents |
| --- | --- |
| [docs/evidence/b01-b02-baseline.md](b01-b02-baseline.md) | B01/B02 baseline removal classification; initial test-suite count |
| [docs/evidence/coordinated-removal.md](coordinated-removal.md) | Coordinated removal/reinstall evidence; real Headroom full CLI |
| [docs/evidence/foundation-cli.json](foundation-cli.json) | Foundation CLI acceptance — four narrow actual tool lifecycles |
| [docs/evidence/graphify-codex.md](graphify-codex.md) | Graphify Codex bridge actual query evidence |
| [docs/evidence/graphify-codex.json](graphify-codex.json) | Graphify Codex bridge JSON trace |
| [docs/evidence/graphify-lock.json](graphify-lock.json) | 31-wheel pinned hash lock for graphifyy 0.9.114 on macOS arm64 |
| [docs/evidence/graphify-managed-index.md](graphify-managed-index.md) | Managed Graphify install/index/query/reindex fixture evidence |
| [docs/evidence/graphify-probe.json](graphify-probe.json) | Known directed-call probe result for greet → normalize_name |
| [docs/evidence/headroom-library.md](headroom-library.md) | Headroom managed library compression evidence |
| [docs/evidence/headroom-library.json](headroom-library.json) | Headroom measurement results (control 282→282; PrettyJSON 5105→1980) |
| [docs/evidence/playwright-acceptance.json](playwright-acceptance.json) | Playwright MCP + Codex CLI actual browser fixture acceptance |
| [docs/evidence/playwright-artifacts.json](playwright-artifacts.json) | Playwright artifact inventory |
| [docs/evidence/portable-profiles.json](portable-profiles.json) | Portable profile CLI round-trip evidence (4 profiles, 20 actual CLI commands) |
| [docs/evidence/portable-profiles.md](portable-profiles.md) | Portable profile documentation and boundary notes |
| [docs/evidence/recommendation-acceptance.md](recommendation-acceptance.md) | Recommendation CLI coverage and deferred final acceptance notes |
| [docs/evidence/unified-workflow.md](unified-workflow.md) | Unified workflow evidence (2 actual CLI workflow smokes) |
| [docs/evidence/unified-workflow.json](unified-workflow.json) | Unified workflow JSON trace |

## Integration guides

| File | Contents |
| --- | --- |
| [docs/integrations/graphify.md](../integrations/graphify.md) | Graphify adapter scope, managed install, known-call checks |
| [docs/integrations/headroom.md](../integrations/headroom.md) | Headroom adapter scope, library compression, measurement conditions |
| [docs/integrations/playwright-mcp.md](../integrations/playwright-mcp.md) | Playwright MCP + Codex setup, scripted local provider, limitations |
| [docs/integrations/promptfoo.md](../integrations/promptfoo.md) | promptfoo adapter scope, evaluation fixture, macOS arm64 target |

## Review and progress notes

| File | Contents |
| --- | --- |
| [docs/reviews/commits-01-02.md](../reviews/commits-01-02.md) | Peer review notes for commits 01 and 02 |
| [docs/implementation-progress.md](../implementation-progress.md) | Running log of step-by-step validation results with test counts |
| [docs/foundation-handoff.md](../foundation-handoff.md) | B handoff: four narrow actual lifecycles accepted, combined acceptance deferred |

## Measurement conditions

Headroom measurements from `docs/evidence/headroom-library.json` were taken on
macOS arm64 using the pinned Headroom 0.44.0 release. Two repeat runs each:
- Control (plain text 282 chars): 282 → 282 (no compression saving)
- PrettyJSON (5105 chars): 5105 → 1980
- EquivalentCompactJSON (3276 chars): 3276 → 1980
- ProtectedText (1241 chars): 1241 → 1241

These are synthetic direct-library measurements on fixed inputs, not arbitrary
project cost-reduction claims. Human setup-effort comparison against an equivalent
manual workflow has not been measured; that comparison is deferred.
