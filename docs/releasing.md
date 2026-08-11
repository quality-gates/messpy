# Releasing messpy

The release workflow publishes artifacts already built and tested by CI; it never rebuilds them. Ordinary push/pull-request CI has no registry credential or OIDC publication permission.

## One-time PyPI setup

Create a PyPI trusted publisher with owner `quality-gates`, repository `messpy`, workflow `publish.yml`, and environment `pypi`. Create the matching protected GitHub environment and require maintainer approval. The workflow uses no API token.

## Release

1. Update `src/messpy/__init__.py::__version__`, changelog/release notes, and generated rule docs.
2. Merge green CI, create a tag `vVERSION` at that exact commit, and push it.
3. Record the successful CI run ID for the tag commit.
4. Manually run **Publish tested distributions** with that run ID, tag, and `first_publication=true` only for the first public release.
5. Approve the protected `pypi` environment after provenance/version checks.

The workflow proves the CI run succeeded at the tag SHA, downloads its `messpy-distributions` artifact, checks wheel/sdist contents and tag version, then publishes through PyPI OIDC. Immediately before the first authorized publication it requires the PyPI JSON endpoint for `messpy` to return 404; any other response aborts. Later releases set `first_publication=false` because the project must already exist.

After publication, verify `python -m pip install --no-cache-dir messpy==VERSION`, `messpy --version`, and the PyPI provenance display.
