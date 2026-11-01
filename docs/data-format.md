# Data format

Every run folder `results/raw/<stack>/<run_id>/` is self-describing. The four JSON files
below are a stable contract, defined by JSON Schemas in [`schemas/`](../schemas) and checked
in CI on every run CI produces. Other tools (notebooks, the published dataset, your own
scripts) can rely on them.

| File | Schema | Written by | Content |
|---|---|---|---|
| `run_meta.json` | [run_meta](../schemas/run_meta.schema.json) | `experiments/write_meta.py` | Run conditions and status: stack, distro, RMW, variant, arch, condition, bag, rate, tag, map/params/metrics status, exit status, host and limits |
| `run_metrics.json` | [run_metrics](../schemas/run_metrics.schema.json) | `metrics/analyze_run.py` | All metrics; `summary` holds the headline numbers ([metrics.md](metrics.md)) |
| `run_manifest.json` | [run_manifest](../schemas/run_manifest.schema.json) | `experiments/write_manifest.py` | Provenance: commit, image tag/id/digests and base image, input hashes, package versions, host, environment |
| `effective_params.json` | [effective_params](../schemas/effective_params.schema.json) | `experiments/dump_params.py` | Parameters the SLAM node actually held vs. the config file |

Raw logs (`cpu_mem.csv`, `proc_metrics.csv`, `net_io.csv`, `latency_events.csv`) keep the
columns documented in [metrics.md](metrics.md); new columns may be appended at the end.

## Run ID

`<YYYYmmdd_HHMMSS>_<variant>_<arch>`, e.g. `20261101_120000_ros2-humble-fastrtps_arm64`.
Unique per machine and safe to merge across machines and CI jobs.

## Versioning

Each file carries `schema_version` (currently `1`).

- **Compatible changes** keep the version: adding a field, adding a `summary` metric,
  appending a CSV column. Readers must ignore fields they do not know.
- **Breaking changes** increment it: renaming or removing a field, changing a field's type
  or meaning, changing a unit. The schema file, this page and the CHANGELOG change together.

From v1.0.0 of the repository, a breaking change to any of these files requires a major
release.

## Validation

```
make validate
python3 experiments/validate_runs.py results/raw/ros2/<run_id>
python3 experiments/validate_runs.py --self-test
```

`validate_runs.py` needs only the standard library. With `jsonschema` installed, the
self-test also checks the schemas themselves against the draft-07 meta-schema.

Runs recorded before v0.3.0 may lack `arch` (treated as `unknown` and never pooled with
newer runs) and, before v0.2.0, `condition` and `schema_version` in `run_metrics.json`;
they fail validation and should be re-run rather than mixed with new results.
