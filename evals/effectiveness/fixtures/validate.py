"""Validate effectiveness fixtures without printing held-out case contents."""

import argparse
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path


TASK_RE = re.compile(r"^task(\d{2})$")
REQUIRED = ("public.md", "public_examples.json", "private_cases.json", "reference.py", "mutants.json")


def _load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_module(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module load failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(solve, case):
    try:
        result = solve(copy.deepcopy(case["input"]))
        json.dumps(result, sort_keys=True)
    except Exception:
        return False
    return result == case["expected"]


def _case_shape(cases, private):
    minimum = 20 if private else 1
    if not isinstance(cases, list) or not (minimum <= len(cases) <= 40):
        return False
    seen = set()
    for case in cases:
        if (not isinstance(case, dict) or "input" not in case
                or not isinstance(case.get("input"), (dict, list, str, int, float, bool, type(None)))):
            return False
        if "expected" not in case:
            return False
        if private:
            ident = case.get("id")
            if not isinstance(ident, str) or not ident or ident in seen:
                return False
            seen.add(ident)
    return True


def validate(root, expected_tasks):
    found = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and TASK_RE.fullmatch(path.name):
            found.append(path)
    expected_names = [root / f"task{i:02d}" for i in range(1, expected_tasks + 1)]
    report = {
        "expected_tasks": expected_tasks,
        "discovered_tasks": len(found),
        "tasks": [],
        "ok": True,
    }
    if found != expected_names:
        report["ok"] = False
    for index, folder in enumerate(expected_names, 1):
        item = {"task": folder.name, "ok": True}
        missing = [name for name in REQUIRED if not (folder / name).is_file()]
        if missing:
            item["ok"] = False
            item["missing_files"] = len(missing)
            report["tasks"].append(item)
            continue
        try:
            public = _load_json(folder / "public_examples.json")
            private = _load_json(folder / "private_cases.json")
            mutants = _load_json(folder / "mutants.json")
            module = _load_module(folder / "reference.py", f"fixture_reference_{index}")
            solve = getattr(module, "solve")
            if not callable(solve) or not _case_shape(public, False) or not _case_shape(private, True):
                raise ValueError("invalid fixture shape")
            if (not isinstance(mutants, list) or len(mutants) < 2
                    or any(not isinstance(m, dict) or not isinstance(m.get("name"), str)
                           or not isinstance(m.get("source"), str) for m in mutants)):
                raise ValueError("insufficient mutants")
            public_failures = sum(not _run(solve, case) for case in public)
            private_failures = sum(not _run(solve, case) for case in private)
            mutant_reports = []
            for mutant in mutants:
                name = mutant.get("name") if isinstance(mutant, dict) else "unnamed"
                source = mutant.get("source") if isinstance(mutant, dict) else None
                failures = len(private)
                passes = 0
                if isinstance(source, str):
                    try:
                        namespace = {}
                        exec(compile(source, f"<{folder.name}-mutant>", "exec"), namespace)
                        mutant_solve = namespace.get("solve")
                        if callable(mutant_solve):
                            passes = sum(_run(mutant_solve, case) for case in private)
                            failures -= passes
                    except Exception:
                        pass
                mutant_reports.append({
                    "name": name,
                    "private_cases": len(private),
                    "passes": passes,
                    "failures": failures,
                    "killed": failures > 0,
                })
            item.update({
                "public_cases": len(public),
                "public_failures": public_failures,
                "private_cases": len(private),
                "private_failures": private_failures,
                "mutants": mutant_reports,
            })
            item["ok"] = public_failures == 0 and private_failures == 0 and all(m["killed"] for m in mutant_reports)
        except Exception:
            item["ok"] = False
            item["fixture_errors"] = 1
        report["tasks"].append(item)
        report["ok"] = report["ok"] and item["ok"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-tasks", type=int, default=12)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    if args.expected_tasks < 1:
        parser.error("--expected-tasks must be positive")
    report = validate(args.root, args.expected_tasks)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
