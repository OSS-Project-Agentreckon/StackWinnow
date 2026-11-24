# Development artifact and assignment handoff

Version **0.1.0.dev0** is an unpublished development build. Core implementation
is delivered; final combined acceptance remains deferred. This document does
not certify a public release or faculty submission. See the [current plan](two-person-sequential-plan.md).

## Build the exact reviewed source

Commit intended changes first. From the checkout with build dependencies installed:

```sh
git rev-parse HEAD
python scripts/build_release.py --source-ref HEAD --dist-dir /tmp/stackwinnow-final-artifacts --no-isolation
python scripts/build_release.py --source-ref HEAD --dist-dir /tmp/stackwinnow-final-artifacts --verify-only
```

Use a new empty directory per revision. Keep the wheel, source archive,
`SHA256SUMS` and `release-manifest.json` together. The manifest records the exact
source SHA and archive-member hashes; local uncommitted changes are excluded.
The manifest is stored with the artifacts, not committed back into its own source.
After merging or changing version/source, build again for that new revision.

Static verification checks source correspondence and hashes; it does not prove
fresh installability or tool functionality. `--install-check` and final combined
acceptance are deferred locally. Existing automated CI remains enabled.

## Assignment materials

- [Technical report draft](report-draft.md): project, design, evidence and limits.
- [Demo instructions](demo-instructions.md): discovery, review and portable plans.
- [Foundation handoff](foundation-handoff.md): historical narrow real lifecycles.
- [Contribution matrix](contribution-matrix.md): genuine authored evidence.
- [Evidence index](evidence/index.md): provenance, scope and measurements.
- [Support matrix](support-matrix.md): four executable modes and prerequisites.

The demo preview does not install upstream tools. A live lifecycle demo needs
the stated prerequisites and reviewed apply, fresh functional check and removal;
use the individual integration guides. Do not substitute a passive status for
functional verification. Avoid paid providers for the deterministic fixture demo.

## Open gates

| Gate | Current boundary / next action |
| --- | --- |
| A05 combined/profile acceptance | Deferred; run when the user resumes testing |
| Clean final artifact install | Deferred locally; inspect exact-revision hosted CI separately |
| Dependency/license closure | Historical snapshot only; refresh for intended release environments |
| Setup-effort comparison | Not measured; do not claim time or dollar savings |
| Final assignment formatting | Student details and faculty format/approval confirmation pending; Markdown report remains a draft |
| Release version/tag/publication | No release tag, GitHub release or PyPI upload performed |
| Faculty submission | Not performed |

No missing broad core feature was established by this plan audit. Optional PR #42
is independent. These remaining gates must not be relabeled “complete” merely
because implementation PRs are merged.
