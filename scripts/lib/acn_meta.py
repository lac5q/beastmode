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
import re
import sys
from pathlib import Path

UNAVAILABLE = "unavailable"

OK = "ok"
DRIFT = "drift"
UNVERIFIABLE = "unverifiable"

_REPORT_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    re.compile(r"/(?:home|Users)/[^/\s]+"),
    re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+"),
)


def safe_report_text(value: object, *, limit: int = 256) -> str:
    """Keep report identifiers/reasons bounded and free of obvious secrets/paths."""
    text = str(value)
    for pattern in _REPORT_SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[:limit] + "…[TRUNCATED]"
    return text

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
#
# Marker choice is load-bearing in BOTH directions, and the first cut of this
# got it wrong: requiring a provenance field to recognise a child meant a child
# that died before writing one was not a child, so it vanished from the report
# and a sibling's clean row carried the batch to exit 0. That is the same
# fail-open this module exists to close, just one level up. Recognition must
# therefore key on "this is a child record", never on "this child proved
# something" — deciding whether it proved anything is `classify`'s job.
META_MARKERS = (
    "requested_model",
    "actual_model",
    "stop_reason",
    "files_changed",
    "commands_run",
    "verify",
    # A token-usage block is the one field no harness config carries, so it
    # identifies a half-written child that has nothing else left to match on.
    "usage",
)
# Pre-v2.3 shape: no requested/actual pair, just the model that ran. `model`
# needs a companion field — a bare {"model": ...} is as likely to be provider
# config as a child record, and false-failing a config file would train people
# to pass --allow-empty everywhere.
LEGACY_PAIRS = (("model", "id"), ("model", "usage"), ("model", "stop_reason"))


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


def is_child_record(body: dict) -> bool:
    """Does this JSON body look like an ACN child record at all?

    Deliberately not "does it prove its model" — see the note on META_MARKERS.
    """
    if not isinstance(body, dict):
        return False
    if any(k in body for k in META_MARKERS):
        return True
    return any(all(k in body for k in pair) for pair in LEGACY_PAIRS)


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
        if is_child_record(body):
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


def expected_ids(source: str) -> list[str]:
    """Expected child ids, from a batch JSON path or a comma-separated list.

    The batch already declares its children — `tasks[].id` is required by
    `schema/acn-contract.json` — so the manifest the gate needs to notice an
    absent child is a file the contract guarantees exists.
    """
    path = Path(source)
    if path.is_file():
        with path.open() as f:
            batch = json.load(f)
        tasks = batch.get("tasks") if isinstance(batch, dict) else None
        if not isinstance(tasks, list):
            raise ValueError(f"{source} has no 'tasks' list to read child ids from")
        return [str(t.get("id")) for t in tasks if isinstance(t, dict) and t.get("id")]
    return [part.strip() for part in source.split(",") if part.strip()]


def check(target: Path, allow_empty: bool = False, strict: bool = False,
          expect: list[str] | None = None) -> GateResult:
    """Run the provenance gate over a directory of child metas."""
    if not target.is_dir():
        return GateResult([], [f"not a directory: {target}"], 2)

    rows = load_rows(target)
    if not rows and not expect:
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

    # A child that died before writing anything leaves no file, so scanning
    # what is present can never notice it — one surviving sibling would carry
    # the batch to exit 0. Only the batch's own list of ids can catch that.
    missing_children = []
    if expect:
        seen = {row.id for row in rows}
        missing_children = [cid for cid in expect if cid not in seen]
        for cid in missing_children:
            messages.append(
                f"UNVERIFIABLE: expected child {cid!r} wrote no meta in {target}; "
                "it cannot be shown to have run under the pinned model"
            )
    incomplete = [row for row in rows if row.missing_fields and not row.failed]
    for row in incomplete:
        messages.append(
            f"INCOMPLETE: {row.id} missing {', '.join(row.missing_fields)} ({row.path})"
        )

    failed = any(row.failed for row in rows) or bool(missing_children)
    if failed or (strict and incomplete):
        return GateResult(rows, messages, 1)
    return GateResult(rows, messages, 0)


def main(argv: list[str]) -> int:
    target = None
    allow_empty = False
    strict = False
    expect: list[str] | None = None
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--check":
            if not args:
                print("acn_meta: --check needs a directory", file=sys.stderr)
                return 2
            target = Path(args.pop(0))
        elif arg == "--expect":
            if not args:
                print("acn_meta: --expect needs a batch file or id list", file=sys.stderr)
                return 2
            try:
                expect = expected_ids(args.pop(0))
            except (OSError, ValueError, json.JSONDecodeError) as e:
                print(f"acn_meta: --expect: {e}", file=sys.stderr)
                return 2
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
        print("usage: acn_meta.py --check <dir> [--expect <batch.json|id,...>] "
              "[--allow-empty] [--strict]", file=sys.stderr)
        return 2

    result = check(target, allow_empty=allow_empty, strict=strict, expect=expect)
    stream = sys.stderr if result.exit_code == 2 else sys.stdout
    for message in result.messages:
        print(message, file=stream)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
