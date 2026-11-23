# Managed Graphify indexing

After locked package installation, Graphify can index reviewed project inputs
and answer a fresh local relationship query. This does not establish Codex
connectivity. The shared report keeps its connection check blocked until the
separate client integration is implemented and verified.

Save plan files outside the indexed project, so saving a plan does not change
its inputs:

    stackwinnow graphify index-plan ./my-project --expectation ./relationship.json --json > /tmp/index-plan.json
    stackwinnow graphify index /tmp/index-plan.json --dry-run --json
    stackwinnow graphify index /tmp/index-plan.json --json
    stackwinnow check ./my-project --tool graphify --json
    stackwinnow check ./my-project --tool graphify --run-functional --json

The expectation identifies exact caller/callee file paths and symbol labels.
See [the example expectation](../tests/fixtures/graphify-relationship.json).
The index plan captures the installed recipe/inventory identity, every included
file digest, fixed exclusions, and previous graph/provenance digests. It contains
no caller-supplied executable commands. Actual argv comes from the pinned recipe.

Index planning and dry runs perform no commands or writes. Apply revalidates
under the project lock, journals intent, and records ownership immediately after
creating the state directory. Extraction reads a private copy of precisely the
reviewed file set. A new generation is extracted and queried before publication;
source and runtime checks run again afterward. Each graph/provenance file is
atomically replaced under the lock. A failure between these replacements leaves
a failed receipt, never a successful index. Generated output and source copies
remain in .stackwinnow/graphify/run-* for explicit recovery/removal; this can
consume additional disk space across reindexing. Original project sources are
never modified by this adapter.

Source input is limited to 2,000 regular, unaliased files, 4 MiB per file and
32 MiB total. Files/directories named .git, .stackwinnow, .venv, venv,
node_modules, __pycache__ or .codex are excluded at every depth. This is a fixed,
visible boundary, not a general Git ignore implementation. The copied input lets
upstream apply its own code-language filters without consulting mutable live
files. Source symlinks, hardlinks, unreadable inputs, unsafe managed paths and
malformed JSON are rejected. Graph/provenance reads are bounded to 4 MiB. This
first release intentionally targets small project fixtures.

Reapplying a saved plan reuses the graph only while its installed runtime,
source snapshot, graph and provenance remain current. Deleted/changed graphs and
added/changed/deleted source files invalidate it. Generate and review a new
index-plan to deliberately reindex; the old graph remains available until the
new extraction/query succeeds. Partial/failed indexes or changed ownership need
inspection rather than automatic adoption. Reapplying the original installation
plan after indexing, including changed-source reindexing, reuses an intact runtime.

New installation manifests retain their original execution recipe (schema 2).
Existing schema-1 installations remain usable without rewriting ownership: pass
--installation-plan /path/to/original-execution-plan.json to index-plan. Its digest
must match installation evidence and its immutable recipe must still match the
reviewed lock and current runtime. If the original plan is unavailable, inspect
the installation before recovery; an unproven recipe is never reconstructed.

The graphify_index adapter exports GraphifyIndexPlan, plan_graphify_index,
load_graphify_index_plan, apply_graphify_index and inspect_graphify_index. The last
function is read-only and returns current provenance plus the relationship check.
Client integration must call it under the shared lock before using graph evidence.
validate_graphify_installation validates owned inventory and immutable recipe
independently of project sources. Shared functional verification runs upstream
path --directed, or explain --all for recursive edges, and records a new receipt;
a prior successful check cannot make a new failed check pass.

The inventory is a local change detector, not a defense against someone rewriting
both receipts and artifacts. Failures retain owned state; coordinated
configuration/runtime removal remains a later foundation task.
