#!/usr/bin/env python3
"""Validate run folders against the data-format schemas in schemas/.

    validate_runs.py results/raw [more dirs or run folders ...]
    validate_runs.py --self-test

Checks run_meta.json, run_metrics.json, run_manifest.json and effective_params.json in
every run folder found (a folder that contains run_meta.json). Exits 1 if any file breaks
its schema. --self-test checks that every schema accepts its own example and rejects the
example with a required field removed.

Standard library only: implements the JSON Schema (draft-07) keywords the schemas use:
type, enum, const, required, properties, additionalProperties, items, pattern, if/then/else.
docs/data-format.md describes the contract and the versioning policy.
"""

import argparse
import copy
import glob
import json
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCHEMA_DIR = os.path.join(REPO, "schemas")
FILES = ("run_meta", "run_metrics", "run_manifest", "effective_params")

TYPES = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def validate(value, schema, path="$"):
    """Return a list of error strings (empty when valid)."""
    errors = []
    if schema is True or schema == {}:
        return errors
    if schema is False:
        return [f"{path}: not allowed"]

    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(TYPES[x](value) for x in types):
            return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__} {value!r:.60}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}, got {value!r:.60}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}, got {value!r:.60}")
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
        errors.append(f"{path}: does not match {schema['pattern']}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, v in value.items():
            if key in props:
                errors += validate(v, props[key], f"{path}.{key}")
            elif extra is False:
                errors.append(f"{path}: unexpected '{key}'")
            elif isinstance(extra, dict):
                errors += validate(v, extra, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += validate(v, schema["items"], f"{path}[{i}]")

    if "if" in schema:
        branch = "then" if not validate(value, schema["if"], path) else "else"
        if branch in schema:
            errors += validate(value, schema[branch], path)
    return errors


def load_schemas():
    out = {}
    for name in FILES:
        with open(os.path.join(SCHEMA_DIR, f"{name}.schema.json")) as f:
            out[name] = json.load(f)
    return out


def find_runs(paths):
    runs = []
    for p in paths:
        if os.path.exists(os.path.join(p, "run_meta.json")):
            runs.append(p)
        else:
            runs += sorted(os.path.dirname(m) for m in glob.glob(os.path.join(p, "**", "run_meta.json"),
                                                                 recursive=True))
    return runs


def validate_run(run_dir, schemas):
    problems = {}
    for name in FILES:
        path = os.path.join(run_dir, f"{name}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            problems[name] = [f"unreadable: {e}"]
            continue
        errs = validate(doc, schemas[name])
        if errs:
            problems[name] = errs
    return problems


def self_test(schemas):
    failures = []
    for name, schema in schemas.items():
        for ex in schema.get("examples", []):
            errs = validate(ex, schema)
            if errs:
                failures.append(f"{name}: example rejected: {errs}")
            for key in schema.get("required", []):
                broken = copy.deepcopy(ex)
                broken.pop(key, None)
                if not validate(broken, schema):
                    failures.append(f"{name}: example without '{key}' was accepted")
    try:
        import jsonschema
        for name, schema in schemas.items():
            jsonschema.Draft7Validator.check_schema(schema)
            for ex in schema.get("examples", []):
                jsonschema.validate(ex, schema)
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        failures.append(f"jsonschema cross-check: {e}")
    return failures


def main():
    ap = argparse.ArgumentParser(description="Validate run folders against schemas/.")
    ap.add_argument("paths", nargs="*", help="results directories or run folders")
    ap.add_argument("--self-test", action="store_true", help="check the schemas against their examples")
    args = ap.parse_args()

    schemas = load_schemas()
    if args.self_test:
        failures = self_test(schemas)
        for f in failures:
            print(f"FAIL {f}", file=sys.stderr)
        if failures:
            sys.exit(1)
        print(f"OK: {len(schemas)} schemas accept their examples and enforce required fields.")
        if not args.paths:
            return

    runs = find_runs(args.paths or [os.path.join(REPO, "results", "raw")])
    bad = 0
    for run in runs:
        problems = validate_run(run, schemas)
        if problems:
            bad += 1
            print(f"INVALID {run}")
            for name, errs in problems.items():
                for e in errs[:10]:
                    print(f"  {name}.json {e}")
                if len(errs) > 10:
                    print(f"  {name}.json ... {len(errs) - 10} more")
    print(f"{len(runs) - bad}/{len(runs)} run folder(s) valid.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
