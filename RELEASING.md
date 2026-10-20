# Releasing

Releases go out from CI. Publishing a GitHub Release is the trigger:
[`.github/workflows/release.yml`](.github/workflows/release.yml) re-runs the
checks, builds, and uploads to PyPI with trusted publishing — no token is
stored anywhere.

## One-time setup

Register this workflow as a trusted publisher at
<https://pypi.org/manage/project/cie-inspector/settings/publishing/>:

| Field | Value |
| --- | --- |
| Owner | `MrBearing` |
| Repository name | `cie-inspector` |
| Workflow name | `release.yml` |
| Environment name | *(leave empty)* |

The workflow declares no environment, so that field has to stay blank or the
OIDC exchange will not match. Do the same at
<https://test.pypi.org/manage/project/cie-inspector/settings/publishing/> to
enable the TestPyPI rehearsal below.

## Cutting a release

1. **Bump the version** in `pyproject.toml` (`uv version --bump patch|minor|major`)
   and merge that on its own.

2. **Tag the commit** you want to release:

   ```bash
   git switch main && git pull
   git tag -a v0.2.0 -m "cie-inspector 0.2.0" && git push origin v0.2.0
   ```

3. **Draft a GitHub Release** against that tag, write the notes, and press
   **Publish**. That starts the workflow.

4. **Watch it.** The build job refuses to continue if the tag disagrees with
   the version in `pyproject.toml` — PyPI never lets a version number be
   reused, so this guard exists to stop a wrong number going out.

5. **Verify** once it is green:

   ```bash
   uvx cie-inspector@latest --version
   ```

The workflow attaches the sdist and wheel to the GitHub Release, so the files
on the release page are the exact ones that were tested and uploaded.

## Rehearsing on TestPyPI

Run the workflow manually — Actions → Release → *Run workflow* — with the
target set to `testpypi`. It builds from the selected branch and uploads
there without touching PyPI or creating a release.

To check what landed, install it by URL. Dependencies then still resolve from
real PyPI:

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

## Publishing by hand

Only needed if CI is unavailable. The `testpypi` index is already configured
in `pyproject.toml`:

```bash
rm -rf dist && uv build
uv publish --index testpypi --dry-run   # validates without uploading
uv publish --index testpypi             # needs a TestPyPI token
uv publish                              # needs a PyPI token
```

`uv publish` takes `--token`, or reads `UV_PUBLISH_TOKEN`. TestPyPI and PyPI
are separate services with separate accounts and tokens — a token from one
returns `403 Invalid or non-existent authentication information` on the other.

Outside CI, `uv publish` tries trusted publishing first and prints
`No OIDC token discovered` before falling back to the token. Pass
`--trusted-publishing never` to skip that.

## Rule

Never describe an install path anywhere — README, release notes, blog posts —
before it has actually been run against the published package.
