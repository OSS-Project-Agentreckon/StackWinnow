# Runtime removal classification

For the explicit user-facing plan/apply lifecycle, see
[coordinated removal](coordinated-removal.md). This page describes its lower-level
read-only classifier.

The plan_removal(project_root, tool_ids=None) function in
stackwinnow.runtime.remove is a read-only preview over receipt-owned resources.
It does not delete files, change receipts, run tools, or grant permission for
a later deletion.

Only non-dry-run succeeded receipts contribute candidates. Other tools'
resources and failed/interrupted ownership protect overlapping paths in both
directions, including absolute and relative spellings of the same location.

Candidates must remain inside the project's .stackwinnow directory without
parent traversal or symlink components. The managed root, receipt file and
operation lock are protected. An ownership path that cannot be resolved safely
blocks planning with InstallerError; a missing path is retained as absent.
An explicitly retained symlink also protects a candidate parent from recursive
removal. No directory scan or subprocess is used to discover ownership.

Project data is retained by location, independently of evidence or a separate
receipt for every output:

| Location under .stackwinnow/ | Policy |
| --- | --- |
| graphify/ | Retain graphs, index state and its isolated caches |
| headroom/ | Retain compression reports, tokenizer cache and private mutable state |
| promptfoo/results/, promptfoo/cache/ | Retain evaluation results and cached responses |
| cache/, caches/ | Retain designated shared caches |
| Path components named results, reports, graphs, output, checks | Retain project output and verification history |
| envs/ | Eligible only when exclusively owned and no retained resource overlaps |

The parent of a retained output is also retained when removing that parent
would erase the output. An EvidenceRef is not by itself a retention rule:
an installation manifest or package health observation does not permanently
protect an otherwise removable runtime. Retention rules never establish
ownership of an unrecorded resource.

This classifier does not reconcile configuration references or authorize
deletion. The coordinated lifecycle adds those checks, fixed runtime scopes,
locked revalidation and durable recovery. A serialized classifier candidate
must not be deleted merely because it was eligible at preview time.

Python 3.14 can leave symlink loops unresolved in Path.resolve(strict=False).
Ownership normalization also checks stat() so ELOOP remains a blocking error
on every supported Python version. Missing owned paths still remain harmless.
The 40 removal-planning tests passed locally on Python 3.11.14 and 3.14.4
after the hosted Python 3.14 regression was reproduced in CI.
