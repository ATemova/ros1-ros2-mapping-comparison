# Release process

## Milestones gate releases

Each release has a GitHub milestone with the same name (`v0.4.0`, `v0.5.0`, `v1.0.0`, ...).
Work planned for a release is an issue in its milestone.

When a release is published, the first job of `.github/workflows/images.yml` checks the
milestone with the release's name **and every earlier version milestone**. If any of them
has open issues, it:

1. turns the release back into a draft (the tag stays),
2. lists the blocking issues in the workflow summary,
3. stops, so no images are published.

Close or move the issues, then publish the draft again; the workflow runs again.
Milestones whose names are not versions (e.g. `ideas`) and later versions never block.
Releases without a milestone are not gated.

To move an issue to a later release instead of finishing it, change its milestone; the
decision then shows in the issue's history.

## Checklist

1. All issues in the milestone closed; CI green on `main`.
2. Release PR from `release/vX.Y.Z`:
   - `CHANGELOG.md`: `## [Unreleased]` → `## [X.Y.Z] - YYYY-MM-DD`, compare links updated
   - README badges and status block
   - `CITATION.cff`: `version`, `date-released`
   - `.zenodo.json`: `version`
3. Merge, then publish from `main`:
   `gh release create vX.Y.Z --target main --title "vX.Y.Z – <summary>" --notes-file <notes.md>`
4. Watch the *Release images* workflow: gate, three multi-arch images, `images.lock` attached.
5. If Zenodo archiving is on, check the new version's DOI.

For v1.0.0 the milestone also covers the results, paper, DOIs and the interface freeze;
see the issues in the `v1.0.0` milestone.
