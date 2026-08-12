# Releasing messpy

PyPI and standalone/Homebrew publication are independent release paths. Both use
one stable `vMAJOR.MINOR.PATCH` tag and the version in
`src/messpy/__init__.py`. Do not rebuild or replace a published artifact.

## One-time PyPI setup

1. On PyPI, create a trusted publisher for owner `quality-gates`, repository
   `messpy`, workflow `publish.yml`, and environment `pypi`.
2. In GitHub, create the matching protected environment named `pypi` and
   require maintainer approval.
3. Do not put a PyPI API token in repository secrets. Publication uses OIDC.

## One-time standalone and Homebrew setup

1. Enable immutable releases for `quality-gates/messpy`.
2. Protect stable `v*` tags against unauthorized creation, update, and
   deletion.
3. Create an organization-owned GitHub App with only **Actions: write**.
   Install it only on `quality-gates/homebrew-tap`, and do not add it to a
   ruleset bypass list.
4. Create a protected `homebrew` environment in `messpy`. Restrict deployment
   to stable release tags, require maintainer approval, and add
   `HOMEBREW_TAP_APP_ID` and `HOMEBREW_TAP_APP_PRIVATE_KEY` as environment
   secrets.
5. Deploy the tap-owned generic
   `.github/workflows/publish-formula.yml` workflow. Its `messpy` allowlist
   entry must derive the upstream repository, archive names, URLs, formula,
   and test command inside the tap. The source workflow sends release identity
   and checksums, not Ruby or download URLs.
6. Protect the tap's default branch and require formula clean-install and
   upgrade checks on its automation pull requests.

## Prepare one stable release

1. Bump `src/messpy/__init__.py::__version__` to `MAJOR.MINOR.PATCH`.
2. Update release notes and regenerate rule docs if the catalogue changed:
   `python scripts/generate_rule_docs.py`.
3. Merge the release source to the default branch and wait for green CI.
4. Create and push the stable tag `vMAJOR.MINOR.PATCH` at that exact commit.

The tag starts **Release standalone executables**. It rejects prerelease tags,
a version mismatch, a moved remote tag, or source outside the default branch.
It then runs the full test suite and self-analysis.

## Standalone and Homebrew publication

The release workflow builds with a hash-pinned PyInstaller toolchain on native
Intel and Apple Silicon macOS runners. It creates exactly:

- `messpy_VERSION_darwin_amd64.tar.gz`
- `messpy_VERSION_darwin_arm64.tar.gz`
- `checksums.txt`

Each archive contains only the top-level `messpy` executable and `LICENSE`.
The workflow tests the exact archive bytes on matching Intel and Apple Silicon
macOS hosts before it creates a GitHub release. It verifies the exact asset set
and checksums, publishes the release, requires GitHub immutability, and only
then dispatches formula publication through the protected `homebrew`
environment.

The immutable GitHub release is the release commit point. A later tap failure
must not cause the tag or release to be deleted.

## PyPI publication

Note the successful CI run ID for the tagged commit. Manually run **Publish
tested distributions** with:

- `ci_run_id`: the run that uploaded `messpy-distributions`
- `tag`: `vVERSION`
- `first_publication=true` only for the first public release

Review validation, then approve the protected `pypi` environment. The workflow
proves that the successful CI run and stable tag identify the same commit, and
that its wheel and source distribution have the tagged version. It publishes
those tested files through PyPI trusted publishing; it does not rebuild them.
For the first publication, a non-404 response from the PyPI project endpoint
stops publication.

## Safe retries

Manually run **Release standalone executables** with its existing stable `tag`
input.

- A matching draft keeps matching assets and uploads only missing assets.
- A draft containing different bytes or extra assets stops. Automation never
  uses clobber.
- A matching immutable release is downloaded and verified, then only Homebrew
  publication is retried.
- A published mutable release stops before Homebrew dispatch.
- A duplicate tap dispatch must converge on the same formula branch and pull
  request; a formula already on the tap's default branch is a successful
  no-op.

Correct tap policy, credentials, or checks and retry the source workflow. Never
mutate a valid published release to recover a formula failure.

## Verify user paths

```console
python -m pip install --no-cache-dir messpy==VERSION
messpy --version
brew update
brew install quality-gates/tap/messpy
messpy --version
```

Check PyPI trusted-publishing provenance, the immutable GitHub release's three
assets, and the protected formula pull request.
