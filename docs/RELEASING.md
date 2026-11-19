# Preparing releases

The installed application is named **ProsperoEden**, with title ID `PPSA99018`.
`sce_sys/param.json` remains the source of truth for the application version.

| GitHub tag | PS5 contentVersion |
| --- | --- |
| `v1.000.000` | `01.000.000` |
| `v1.000.001` | `01.000.001` |
| `v1.001.000` | `01.001.000` |

The first component is padded to two digits in the PS5 package. The other two
components stay three digits in both the package and the release tag. There is
no leading `v` in the package metadata. Versions are explicit release numbers,
not dates. Existing `v26.011.018` releases and tags are retained.

## Normal release process

1. Open **Actions → Prepare release → Run workflow** and choose `main`.
2. Enter the intended version, for example `1.000.001`. A `v` prefix is optional;
   `1.0.1` is normalized to `v1.000.001`.
3. The workflow creates a release branch and PR, updates the package metadata,
   README and changelog heading, and explicitly starts a build of the branch.
4. Review and complete the release notes in the PR, then merge it into `main`.
5. The version change on `main` automatically creates the matching tag at the
   merge commit and explicitly dispatches **Release build** on that tag.
6. The existing build workflow creates the ZIP/checksum and publishes a
   pre-release. Review the result on GitHub Releases before making it stable.

Do not manually move the release tag after this process. Reusing a tag that
points to another commit is rejected rather than silently replacing a published
release. Use an unused version number for the next release.

The explicit build dispatches are intentional: pushes and PRs made with the
built-in `GITHUB_TOKEN` do not themselves trigger other push/PR workflows.

For automated PR creation, the repository/organization must permit GitHub
Actions to create pull requests (**Settings → Actions → General → Workflow
permissions → Allow GitHub Actions to create and approve pull requests**).
The workflow requests only the per-job permissions it uses. If policy forbids
bot PR creation, use the local procedure below; no personal access token is
required by the checked-in automation.

## Preparing a PR locally

Start a new branch from up-to-date `main`, then run:

```sh
python3 tools/ci/prepare-version.py 1.000.001
python3 tools/check-release-version.py
```

Review the changelog and the version diff, commit, push and open a PR. Merging
the version change triggers the same tag/build process automatically. Ordinary
feature PRs that do not change `contentVersion` do not create release tags.

For the initial `v1.000.000` release, the release PR already contains the version
change and automation. Merging that PR creates the new tag; the older
`v26.011.018` tag is not modified.

## Retrying a build

If tagging succeeded but dispatch failed, run **Release build** manually and
select the existing release tag. A rerun of the tagging job also accepts a tag
that already points to that exact merge commit. A different target is rejected.
The existing publish workflow does not overwrite a ZIP already attached to a
release; replace release assets deliberately if a rebuild is intended.
