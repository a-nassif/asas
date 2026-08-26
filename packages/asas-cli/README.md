# asas-cli

The developer on-ramp to the Asas package collection. Not a runtime framework —
it never wraps or wires anything at import time in a consuming project. Two
one-shot code generators:

```
asas add lookups                          # pin one package into an existing project
asas new myservice --with lookups,access  # scaffold a new project wired for a set
asas list                                 # see every known package + its variant
```

## `asas add <package>`

Writes the correct `git+https://...#subdirectory=...` line into your
project's `pyproject.toml` `[project.dependencies]` — pinned to the latest
Asas git tag by default (`--tag` to override). Idempotent: running it again
for the same package updates the pin in place instead of duplicating it.
Accepts either the short key (`lookups`) or the full dist name
(`asas-lookups`).

```
asas add ratelimit --tag v0.15.0 --path ./services/api/pyproject.toml
```

## `asas new <name> --with <keys>`

Scaffolds `<name>/main.py`, `settings.py`, `pyproject.toml`, `README.md`,
and `.env.example`, wired for whichever packages you list. The generated
`main.py` is **plain, editable Python** — the same manual `migrate` →
`seed` → `build_routers` → `include_router` sequence you'd write by hand
following each package's host contract, just typed for you. It is not a
runtime abstraction: nothing in a consuming project depends on `asas-cli`
after generation, and re-running `asas new` never edits a file you've
already touched — it only ever starts a fresh project directory.

Every non-comment line it generates is a real call against the package's
actual API. Lines needing data or logic only the host can supply (policy
grants, workflow specs, tool implementations, …) are left as `# TODO`
comments naming the exact function to call — never a fabricated call.

```
asas new myservice --with lookups,ratelimit,access
cd myservice && pip install -e '.[dev]' && uvicorn main:app --reload
```

## Where this fits

See the repo README's "host contract" — every package's real behavior is
defined there and enforced by that package's own tests, not by this CLI.
`asas_cli.registry` (install metadata) and `asas_cli.templates` (boot
snippets) are this tool's description of that contract for scaffolding
purposes; update both when a package's public surface changes.
