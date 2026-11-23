# Historical dependency and notice reference, 23 November 2026

inventory.json is a sanitized schema-version-1 reference capture: 809 records,
739 installed and 70 optional platform lock records. Scopes: Graphify 33,
Headroom 70, promptfoo 690 (625 installed), Playwright 3, Codex 7 (2 installed),
manager core 6. Python inventories include environment packaging utilities.

Fields describe package versions, captured artifact hashes, declared terms and
significant review exceptions. Captured-license hashes refer to an earlier audit
of 472 evidence objects; only the 15 distinct direct-tool/manager-core notice
texts indexed by included-texts.json are included here. Each text filename is
its actual SHA256. Other hashes are references, not a claim those files are bundled.
Supplemental source URLs are distinguished from licenses actually present in an
installed wheel/npm archive. External Node/browser evidence is separate.

These are historical artifacts, not final A06/A08 runtime installations. B08 later
captured 70 Headroom and 33 Graphify distributions with unchanged name/version
pairs (not proof of identical bytes), 623 promptfoo hidden-lock paths and 3
Playwright paths. The b08 comparison files record the differences. promptfoo changed
six transitive versions and removed two nested ws paths; the earlier 625-path
license evidence does not certify the changed versions. Fresh inventory/notice
reconciliation is deferred alongside final runtime acceptance.

## Reproducibility boundaries

- Graphify's checked-in platform wheel lock pins 31 packages with URLs/hashes;
  environment pip/setuptools are separate. Support is restricted to its specified
  CPython/macOS/architecture combination.
- Headroom, promptfoo and Playwright pin direct releases. They are not complete
  transitive locks; resolution can drift, as the promptfoo comparison demonstrates.
- Manager dependency ranges in pyproject are compatibility requirements, not a
  complete lock. The observed six manager packages are not universal install pins.
- The release manifest binds manager source/resources to an exact commit and hashes
  its archives. That does not make separately downloaded runtime trees reproducible.

Do not use the inventory as a pip/npm lockfile. Refresh it from new actual installs
when testing resumes, preserving names, versions, resolver integrity/hash fields,
license files and exact evidence scope. See the root third-party notices for open
gaps, mixed-license components and the exclusion of runtime redistribution.
