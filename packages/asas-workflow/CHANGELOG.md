# Changelog — `asas-workflow`

Versions follow semver, and the git tag matches this file: `asas-workflow/v0.11.0`.
Pre-1.0, a breaking change bumps the **minor**.

Release procedure and the historical tag mapping: [`RELEASING.md`](../../RELEASING.md).

## 0.11.0 — 2026-08-25

- **Breaking:** `asas_workflow.seed` (the module) is now `asas_workflow.seeding`. The old name shadowed the seeding callable, so `asas_workflow.seed(session)` — what the README documented — raised `TypeError: 'module' object is not callable`. Import `seed_workflow_definitions` from the package.
- Declares `__all__` (54 names). It was the only package without one, so `import *` leaked every transitively-imported name.
- **Adoption is now shape-verified.** `migrate()` previously decided adopt-vs-create on the sentinel table's *name* alone, so a host that already owned a table of that name had the baseline stamped as applied and skipped entirely — silently, and unrepairable by re-running. It now requires every baseline table to be present and the sentinel to carry the baseline's columns, and raises with the table, the package and the remedy otherwise (Teamy TEAMY-795).
- Licensed under **Apache 2.0** (was proprietary/all-rights-reserved). `LICENSE` and `NOTICE` ship inside the wheel and the metadata carries `License-Expression: Apache-2.0` (Teamy TEAMY-797).
- Added `tests/test_host_contract.py`: `__all__` declared and resolving, contract names callable rather than shadowed by a submodule, module exports declared deliberately (Teamy TEAMY-798).

## Before 2026-08-25

Earlier releases were cut as **repo-wide** tags (`v0.1.0` … `v0.15.0`) under the
lockstep scheme in DR 0017, which decayed: from `v0.11.0` onward the repo tag no
longer matched any package's own version, so `asas-workflow @ v0.15.0` did not install
`asas-workflow` 0.15.0. `RELEASING.md` carries the full tag-to-version table for
decoding an old pin. Individual changes are in the git history.
