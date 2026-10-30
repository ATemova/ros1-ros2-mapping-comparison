# Dataset, sample bag and DOI

Three things make the study reproducible by others: a **sample bag** that CI replays on
every push, the **full dataset** archived with a DOI, and the **code** archived with a DOI.

## 1. Sample bag for CI (GitHub release asset)

A short cut of a real recording, replayed through both stacks in the `docker-e2e` CI job.
Large files stay out of git; a release asset avoids Git LFS bandwidth quotas.

```
make sample-bag BAG=data/bags/corridor_01.bag SECONDS=30
cd data/bags && zip sample.zip sample.bag sample.groundtruth.tum sample.reference.yaml sample.reference.pgm && cd -
sha256sum data/bags/sample.zip
gh release create sample-data-v1 data/bags/sample.zip --title "Sample bag v1" --notes "30 s of corridor_01 for CI"
```

Only include the companion files that exist. Then set two repository variables
(Settings → Secrets and variables → Actions → Variables):

| Variable | Value |
|---|---|
| `SAMPLE_BAG_URL` | `https://github.com/ATemova/ros1-ros2-mapping-comparison/releases/download/sample-data-v1/sample.zip` |
| `SAMPLE_BAG_SHA256` | the sha256 printed above |

From the next push, CI downloads it (`experiments/fetch_sample_bag.sh`), verifies the
checksum, runs `make matrix RUNS=1 BAG=data/bags/sample.bag`, and fails if either stack
does not produce and save a map. Locally: `SAMPLE_BAG_URL=... ./experiments/fetch_sample_bag.sh`.

Until the variables are set, CI runs the same end-to-end path on the synthetic bag only.

## 2. Full dataset on Zenodo (DOI)

```
RESULTS_TAG=<final_run_tag> make dataset NAME=ros1-ros2-mapping-dataset BAGS="data/bags/corridor_01.bag data/bags/corridor_02.bag"
```

This writes `data/release/<NAME>.zip` with both bag formats, ground truth and reference
maps when present, `*.info.txt` per bag, the parameter files, `CITATION.cff`, a README,
`SHA256SUMS`, and (with `RESULTS_TAG`) the per-run outputs and reports.

On zenodo.org: **New upload** → upload type *Dataset* → add the zip → fill in title, authors,
description (the generated README is a good start) and a data licence (CC BY 4.0 is the
common choice for research data; it is your decision) → **Reserve DOI** before publishing
if you want to cite the DOI inside the dataset or the paper → Publish.

Add the DOI badge to the README and the DOI to `CITATION.cff` (`identifiers:`).

## 3. Code DOI (GitHub ↔ Zenodo)

1. On zenodo.org, sign in with GitHub, open *GitHub* settings and switch the repository on.
2. Create a GitHub release (e.g. `v0.2.0`). Zenodo archives it and mints a DOI, using
   `.zenodo.json` for title, creators, keywords and licence.
3. Link the two records: in the dataset record add the software DOI as *is supplemented by*,
   and vice versa.

`CITATION.cff` makes GitHub show "Cite this repository". Add co-authors and ORCID iDs to both
`CITATION.cff` and `.zenodo.json` before the first release.
