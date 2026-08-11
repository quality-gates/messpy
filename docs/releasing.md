# Releasing messpy

Publish only artifacts CI already built and tested. The release workflow never rebuilds the wheel or sdist. Ordinary push and pull-request CI has no registry credential and no OIDC permission to publish.

## One-time PyPI setup

Do this once before the first public release:

1. On PyPI, create a trusted publisher for owner `quality-gates`, repository `messpy`, workflow `publish.yml`, and environment `pypi`.
2. In GitHub, create the matching protected environment named `pypi` and require maintainer approval.
3. Do not put a PyPI API token in repository secrets. Publication uses OIDC only.

## Each release

1. Bump `src/messpy/__init__.py::__version__`. That single value drives package metadata, `messpy --version`, and report tool version.
2. Update changelog or release notes and regenerate rule docs if the catalogue changed (`python scripts/generate_rule_docs.py`).
3. Merge to `main` with green CI.
4. Tag that exact commit as `vVERSION` and push the tag.
5. Note the successful CI run ID for the tag commit (the run that uploaded `messpy-distributions`).
6. Manually run the **Publish tested distributions** workflow with:
   - `ci_run_id` = that run ID
   - `tag` = `vVERSION`
   - `first_publication=true` only for the very first public release; otherwise `false`
7. Review the validation job, then approve the protected `pypi` environment.

## What the workflow checks

Before it can publish, the workflow proves:

- the selected run is a successful `.github/workflows/ci.yml` run
- that run’s head SHA matches the pushed tag
- the downloaded `messpy-distributions` artifact contains a valid wheel and sdist for the tagged version

For the first publication only, immediately before upload it requires `https://pypi.org/pypi/messpy/json` to return HTTP 404. Any other response aborts so an unexpected name collision cannot be overwritten by mistake. Later releases set `first_publication=false` because the project must already exist on PyPI.

## After publication

Confirm the install path end users will hit:

```console
python -m pip install --no-cache-dir messpy==VERSION
messpy --version
```

Also check the PyPI project page shows trusted-publishing provenance for the new files.
