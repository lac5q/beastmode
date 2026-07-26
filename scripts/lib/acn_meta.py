#!/usr/bin/env python3
"""acn_meta — the one implementation of the ACN model-provenance gate.

Before v2.3 the gate existed twice: `enforce-models --check-meta` walked
`**/*.json` and compared two fields, while `acn-report` walked `*.json` plus
`**/meta.json` and compared the same two fields differently. Two readings of
one contract is one reading too many — a child could pass in one tool and
fail in the other. Both tools now call this module, and this module reads
`schema/acn-contract.json` so the schema is load-bearing rather than
decorative.

The gate answers exactly one question per child: **can we prove which model
served it?**

    ok            requested_model == actual_model
    drift         requested_model != actual_model
    unverifiable  provenance cannot be established at all

`unverifiable` is a failure, not a warning. ACN shared rule 2 says a child
whose model the runtime cannot prove is an unverified draft lane and is
never `validated`; a gate that exits 0 on "I don't know" would invert that
rule. The pre-v2.3 code hit this in two common cases:

  * a legacy `{"id", "model", "stop_reason", "usage"}` meta — the shape the
    repo's own pi and autonomy-levels docs used to specify — parsed fine,
    matched no known field, and was skipped as "not a meta file";
  * an empty directory (batch died before any child wrote) returned 0.

Contract *completeness* (all of `meta_json_required_fields` present) is
reported separately and only gates under `strict`. Provenance is the gate;
missing `commands_run` is a quality signal.

Usage as a CLI (what scripts/enforce-models shells out to):

    python3 acn_meta.py --check <dir> [--allow-empty] [--strict]

Exit codes match the rest of the toolchain: 0 clean, 1 gate failure,
2 usage error.
"""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

UNAVAILABLE = "unavailable"

OK = "ok"
DRIFT = "drift"
UNVERIFIABLE = "unverifiable"

# Fallback used only when schema/acn-contract.json cannot be located (the
# module is vendored somewhere without the repo). Keep in sync with the
# schema; tests/test-acn-parity.sh asserts the two agree.
DEFAULT_META_FIELDS = (
    "id",
    "requested_model",
    "actual_model",
    "stop_reason",
    "usage",
    "files_changed",
    "commands_run",
    "verify",
)

# A *.json file under the run directory is treated as an ACN child meta when
# it is literally named meta.json, or when its body carries a field only a
# meta would carry. Run dirs legitimately contain other JSON (harness config,
# task manifests); classifying those as unverifiable children would turn the
# fail-closed gate into a false-positive machine.
META_MARKERS = (
    "requested_model",
    "actual_model",
    "stop_reason",
    "files_changed",
    "commands_run",
    "verify",
)
# Pre-v2.3 shape: no requested/actual pair, just the model that ran. Matched
# so the gate can name it and tell the caller how to migrate, instead of
# skipping it silently.
LEGACY_MARKERS = ("model", "usage")


def contract_path(start: Path | None = None) -> Path | None:
    """Locate schema/acn-contract.json by walking up from this file."""
    here = (start or Path(__file__).resolve()).parent
    for candidate in (here, *here.parents):
        path = candidate / "schema" / "acn-contract.json"
        if path.is_file():
            return path
    return None


@functools.lru_cache(maxsize=1)
def required_meta_fields() -> tuple[str, ...]:
    """The contract's meta.json required fields, schema-first."""
    path = contract_path()
    if path is None:
        return DEFAULT_META_FIELDS
    try:
        with path.open() as f:
            contract = json.load(f)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_META_FIELDS
    fields = contract.get("meta_json_required_fields")
    if isinstance(fields, list) and fields:
        return tuple(str(x) for x in fields)
    return DEFAULT_META_FIELDS


def find_meta_files(target: Path) -> list[Path]:
    """Every candidate child meta under `target`, recursively, sorted."""
    found = []
    for path in sorted(set(target.glob("**/*.json"))):
        if not path.is_file():
            continue
        if path.name == "meta.json":
            found.append(path)
            continue
        try:
            with path.open() as f:
                body = json.load(f)
        except json.JSONDecodeError:
            # Unreadable JSON inside a run dir is itself a finding — a child
            # that half-wrote its meta must not pass as "no meta here".
            found.append(path)
            continue
        except OSError:
            continue
        if not isinstance(body, dict):
            continue
        if any(k in body for k in META_MARKERS):
            found.append(path)
        elif all(k in body for k in LEGACY_MARKERS):
            found.append(path)
    return found


class Row:
    """One child's provenance verdict, ready for either tool's output."""

    def __init__(self, path: Path, data: dict | None, error: str | None = None):
        self.path = path
        self.error = error
        data = data if isinstance(data, dict) else {}
        self.id = _first(data, "id", "name") or path.stem
        self.requested = _first(data, "requested_model") or UNAVAILABLE
        self.actual = _first(data, "actual_model") or UNAVAILABLE
        self.legacy_model = _first(data, "model") or UNAVAILABLE
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        self.input_tokens = _stringify(usage.get("input_tokens"))
        self.output_tokens = _stringify(usage.get("output_tokens"))
        self.missing_fields = [f for f in required_meta_fields() if f not in data]
        self.status, self.reason = self._classify()

    def _classify(self) -> tuple[str, str]:
        if self.error:
            return UNVERIFIABLE, f"unreadable meta: {self.error}"
        has_req = self.requested != UNAVAILABLE
        has_act = self.actual != UNAVAILABLE
        if has_req and has_act:
            if self.requested == self.actual:
                return OK, ""
            return DRIFT, f"{self.requested} -> {self.actual}"
        if self.legacy_model != UNAVAILABLE and not (has_req or has_act):
            return UNVERIFIABLE, (
                f"legacy meta shape: only 'model' ({self.legacy_model}); "
                "emit requested_model and actual_model per schema/acn-contract.json"
            )
        missing = "requested_model" if not has_req else "actual_model"
        return UNVERIFIABLE, f"missing {missing}; cannot prove which model served this child"

    @property
    def failed(self) -> bool:
        return self.status in (DRIFT, UNVERIFIABLE)

    def line(self) -> str:
        label = "MODEL DRIFT" if self.status == DRIFT else "UNVERIFIABLE"
        return f"{label}: {self.reason} ({self.path})"


def _first(data: dict, *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _stringify(value) -> str:
    return UNAVAILABLE if value is None else str(value)


def load_rows(target: Path) -> list[Row]:
    rows = []
    for path in find_meta_files(target):
        try:
            with path.open() as f:
                rows.append(Row(path, json.load(f)))
        except (OSError, json.JSONDecodeError) as e:
            rows.append(Row(path, None, error=str(e)))
    return rows


class GateResult:
    def __init__(self, rows: list[Row], messages: list[str], exit_code: int):
        self.rows = rows
        self.messages = messages
        self.exit_code = exit_code


def check(target: Path, allow_empty: bool = False, strict: bool = False) -> GateResult:
    """Run the provenance gate over a directory of child metas."""
    if not target.is_dir():
        return GateResult([], [f"not a directory: {target}"], 2)

    rows = load_rows(target)
    if not rows:
        if allow_empty:
            return GateResult([], [f"no child metas found in {target} (--allow-empty)"], 0)
        # Fail closed: a batch that produced no provable child did not
        # produce a validated one either.
        return GateResult(
            [],
            [
                f"UNVERIFIABLE: no child metas found in {target}; "
                "no child's model can be proven, so nothing here is validated. "
                "Pass --allow-empty if this batch legitimately had no children."
            ],
            1,
        )

    messages = [row.line() for row in rows if row.failed]
    incomplete = [row for row in rows if row.missing_fields and not row.failed]
    for row in incomplete:
        messages.append(
            f"INCOMPLETE: {row.id} missing {', '.join(row.missing_fields)} ({row.path})"
        )

    failed = any(row.failed for row in rows)
    if failed or (strict and incomplete):
        return GateResult(rows, messages, 1)
    return GateResult(rows, messages, 0)


def main(argv: list[str]) -> int:
    target = None
    allow_empty = False
    strict = False
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--check":
            if not args:
                print("acn_meta: --check needs a directory", file=sys.stderr)
                return 2
            target = Path(args.pop(0))
        elif arg == "--allow-empty":
            allow_empty = True
        elif arg == "--strict":
            strict = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print(f"acn_meta: unknown arg: {arg}", file=sys.stderr)
            return 2

    if target is None:
        print("usage: acn_meta.py --check <dir> [--allow-empty] [--strict]", file=sys.stderr)
        return 2

    result = check(target, allow_empty=allow_empty, strict=strict)
    stream = sys.stderr if result.exit_code == 2 else sys.stdout
    for message in result.messages:
        print(message, file=stream)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
