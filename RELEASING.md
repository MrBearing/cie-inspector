# Releasing

Releases are cut by hand — nothing publishes from CI.

## 1. Check

```bash
git switch main && git pull
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

Bump `version` in `pyproject.toml` if this is not the first release, and commit
that on its own.

## 2. Build

```bash
rm -rf dist
uv build
```

`uv build` writes the sdist first and then builds the wheel *from* it, so a
broken sdist fails here instead of after the upload.

## 3. Rehearse on TestPyPI

`--dry-run` validates the artifacts and the target without sending anything:

```bash
uv publish --index testpypi --dry-run
```

Then upload for real (needs a TestPyPI token — see below):

```bash
uv publish --index testpypi
```

Confirm the uploaded package installs and runs. Install it by its TestPyPI
URL — that pins the artifact you just uploaded while every dependency still
resolves from real PyPI:

```bash
WHEEL=$(curl -s https://test.pypi.org/pypi/cie-inspector/json \
  | python3 -c "import json,sys; print(next(u['url'] for u in json.load(sys.stdin)['urls'] if u['filename'].endswith('.whl')))")

uvx --from "cie-inspector @ $WHEEL" cie-inspector --version
uvx --from "cie-inspector @ $WHEEL" cie-inspector extract tests/fixtures/ws_basic --format table
```

Do **not** reach for the obvious `--index https://test.pypi.org/simple/
--default-index https://pypi.org/simple/` form. uv's default index strategy
(`first-index`) pins every package to the first index it appears on, and
TestPyPI happens to carry stale copies of some dependencies — `pydantic` is
one — so resolution fails with a misleading message blaming `cie-inspector`:

```
Because cie-inspector was not found in the package registry and you require
cie-inspector, we can conclude that your requirements are unsatisfiable.
```

`--index-strategy unsafe-best-match` also works, but it switches off the
dependency-confusion protection for the whole resolution. The URL form above
does not, so prefer it.

## 4. Publish

```bash
uv publish
```

A version can never be re-uploaded, so make sure step 3 looked right first.

## 5. After a successful upload

Tag the released commit:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Then confirm the published artifact from a clean machine's point of view:

```bash
uvx cie-inspector --version
```

Never describe an install path in the README before it works. The first
release shipped instructions for `uvx cie-inspector` only once that command
had actually been run against PyPI.

## Tokens

`uv publish` takes `--token`, or reads `UV_PUBLISH_TOKEN`. Create tokens under
PyPI (or TestPyPI) → Account settings → API tokens; once the project exists,
replace the account-wide token with one scoped to it.

Outside CI, `uv publish` tries trusted publishing first and prints an
`No OIDC token discovered` error before falling back to the token. Pass
`--trusted-publishing never` to skip that.
