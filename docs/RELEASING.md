# Releasing

`xian-py` publishes `xian-tech-py` from a strict `vX.Y.Z` tag. Prereleases may
use `alpha.N`, `beta.N`, or `rc.N` suffixes.

## Release Authority

- The tag commit is authoritative for the SDK source and package version.
- `release-manifest.json` is authoritative for sibling build inputs.
- Every sibling ref is an exact 40-character commit SHA, never a branch.
- Every manifest package version must match the pinned source and `uv.lock`.
- The independent package manifest is separate from `xian-stack`'s node/image
  launch-train manifest.

## Tag Workflow

1. Update `pyproject.toml` to the intended version.
2. Refresh and commit `uv.lock`.
3. Pin the coherent released `xian-contracting` source and all local-path
   package versions in `release-manifest.json`.
4. Run `uv run python scripts/release_context.py validate-manifest`.
5. Run the validation commands from `AGENTS.md` with `uv sync --frozen`.
6. Commit the version, lockfile, and release manifest from a clean tree.
7. Create and push the matching `vX.Y.Z` tag.

## Automated Gates

The tag workflow resolves the tag and trigger to one clean source SHA, checks
out the manifest's sibling SHA, verifies source/package/lock versions, runs
Ruff and the complete coverage test suite, and builds with `uv build
--no-sources`. It inspects the wheel and sdist metadata before uploading them.
PyPI publishing consumes only those uploaded validated artifacts.

The workflow fails closed on a malformed tag, a moved or dirty source checkout,
a floating sibling ref, any source/lock/package-version mismatch, missing tests,
or unexpected distribution metadata.
