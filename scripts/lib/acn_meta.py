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
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from pathlib import Path

UNAVAILABLE = "unavailable"

OK = "ok"
DRIFT = "drift"
UNVERIFIABLE = "unverifiable"

MAX_META_FILES = 1024
MAX_SCANNED_ENTRIES = 8192
MAX_SCAN_DEPTH = 8
MAX_JSON_BYTES = 256 * 1024
MAX_JSON_DEPTH = 8
MAX_JSON_ITEMS = 2048
ATTESTATION_FIELDS = (
    "id",
    "requested_model",
    "actual_model",
    "source",
    "run_id",
    "result_digest",
)

_REPORT_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    re.compile(r"/(?:home|Users)/[^/\s]+"),
    re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+"),
    re.compile(
        r"(?i)\b(?:password|passwd|secret|token|api[-_]?key|authorization|"
        r"database[-_]?url|access[-_]?token)\b\s*[:=]\s*[^\s,;]+"
    ),
)


def safe_report_text(value: object, *, limit: int = 256) -> str:
    """Keep report identifiers/reasons bounded and free of obvious secrets/paths."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
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
    found: list[Path] = []
    scanned = 0
    target = Path(target)
    pending = [target]
    while pending:
        root_path = pending.pop()
        try:
            depth = len(root_path.relative_to(target).parts)
        except ValueError as exc:
            raise MetadataLimitError("metadata scan escaped its target") from exc
        if depth > MAX_SCAN_DEPTH:
            raise MetadataLimitError(f"metadata scan depth exceeds {MAX_SCAN_DEPTH}")

        directories: list[Path] = []
        files: list[Path] = []
        with os.scandir(root_path) as entries:
            for entry in entries:
                scanned += 1
                if scanned > MAX_SCANNED_ENTRIES:
                    raise MetadataLimitError(
                        f"metadata scan exceeds {MAX_SCANNED_ENTRIES} filesystem entries"
                    )
                path = root_path / entry.name
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    directories.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(path)

        # Each list is bounded by MAX_SCANNED_ENTRIES before sorting. Reverse
        # insertion keeps the depth-first traversal deterministic.
        pending.extend(reversed(sorted(directories)))
        for path in sorted(files):
            if path.suffix.lower() != ".json":
                continue
            if len(found) >= MAX_META_FILES:
                raise MetadataLimitError(
                    f"metadata scan exceeds {MAX_META_FILES} JSON candidates"
                )
            if path.name == "meta.json":
                found.append(path)
                continue
            try:
                body = _load_json(path)
            except (OSError, json.JSONDecodeError, RecursionError, MetadataLimitError):
                # Any unreadable or structurally excessive JSON in a run
                # directory is fail-closed: it may be a partial child record.
                found.append(path)
                continue
            if is_child_record(body):
                found.append(path)
    return sorted(found)


class MetadataLimitError(ValueError):
    """Raised when a run directory or JSON structure exceeds gate bounds."""


def _load_json(path: Path):
    if path.is_symlink() or not path.is_file():
        raise MetadataLimitError("JSON metadata must be a regular, non-symlink file")
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        raise MetadataLimitError(f"JSON file exceeds {MAX_JSON_BYTES} bytes")
    with path.open(encoding="utf-8") as handle:
        body = json.load(handle)
    _validate_json_shape(body)
    return body


def _validate_json_shape(value: object) -> None:
    items = 0

    def visit(node: object, depth: int) -> None:
        nonlocal items
        if depth > MAX_JSON_DEPTH:
            raise MetadataLimitError(f"JSON nesting exceeds depth {MAX_JSON_DEPTH}")
        items += 1
        if items > MAX_JSON_ITEMS:
            raise MetadataLimitError(f"JSON structure exceeds {MAX_JSON_ITEMS} items")
        if isinstance(node, dict):
            for key, child in node.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)

    visit(value, 0)


class Row:
    """One child's provenance verdict, ready for either tool's output."""

    def __init__(
        self,
        path: Path,
        data: dict | None,
        error: str | None = None,
        attestation: dict | None = None,
    ):
        self.path = path
        self.error = error
        data = data if isinstance(data, dict) else {}
        self.raw_id = _first(data, "id", "name") or path.stem
        self.id = safe_report_text(self.raw_id)
        self._requested_raw = _first(data, "requested_model") or UNAVAILABLE
        self._worker_actual_raw = _first(data, "actual_model") or UNAVAILABLE
        self._attestation = attestation
        self._actual_raw = _first(attestation or {}, "actual_model") or UNAVAILABLE
        self._legacy_raw = _first(data, "model") or UNAVAILABLE
        self.requested = safe_report_text(self._requested_raw)
        self.actual = safe_report_text(self._actual_raw)
        self.legacy_model = safe_report_text(self._legacy_raw)
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        self.input_tokens = _stringify(usage.get("input_tokens"))
        self.output_tokens = _stringify(usage.get("output_tokens"))
        self.missing_fields = [f for f in required_meta_fields() if f not in data]
        self.status, self.reason = self._classify()

    def _classify(self) -> tuple[str, str]:
        if self.error:
            return UNVERIFIABLE, f"unreadable meta: {self.error}"
        if self._attestation is None:
            return UNVERIFIABLE, (
                "missing independent harness/provider attestation; "
                "worker-authored actual_model is not trusted evidence"
            )
        attested_id = _first(self._attestation, "id")
        attested_requested = _first(self._attestation, "requested_model")
        if attested_id != self.raw_id or attested_requested != self._requested_raw:
            return UNVERIFIABLE, "trusted attestation does not bind this child id/request"
        if not hmac.compare_digest(
            str(self._attestation.get("result_digest", "")),
            hashlib.sha256(self.path.read_bytes()).hexdigest(),
        ):
            return UNVERIFIABLE, "trusted attestation does not bind these result bytes"
        if self._worker_actual_raw != self._actual_raw:
            return UNVERIFIABLE, "worker metadata disagrees with trusted actual_model"
        has_req = self._requested_raw != UNAVAILABLE
        has_act = self._actual_raw != UNAVAILABLE
        if has_req and has_act:
            if self._requested_raw == self._actual_raw:
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
        return safe_report_text(f"{label}: {self.reason} ({self.path})", limit=1024)


def _first(data: dict, *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _stringify(value) -> str:
    return UNAVAILABLE if value is None else safe_report_text(value)


def _attestation_payload(record: Mapping[str, object]) -> bytes:
    return json.dumps(
        {field: record.get(field) for field in ATTESTATION_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def sign_attestation(record: Mapping[str, object], key: bytes) -> str:
    """Authenticate one bounded provider attestation with a parent-held key."""
    if not isinstance(key, bytes) or len(key) < 32:
        raise MetadataLimitError("attestation key must contain at least 32 bytes")
    return hmac.new(key, _attestation_payload(record), hashlib.sha256).hexdigest()


def attestation_credentials_from_environment() -> tuple[bytes, str]:
    """Read CLI-only credentials without placing the authentication key in argv."""
    encoded_key = os.environ.get("BEASTMODE_ATTESTATION_KEY", "")
    run_id = os.environ.get("BEASTMODE_ATTESTATION_RUN_ID", "")
    try:
        key = bytes.fromhex(encoded_key)
    except ValueError as exc:
        raise MetadataLimitError("attestation key must be valid hexadecimal") from exc
    if len(key) < 32 or not run_id:
        raise MetadataLimitError(
            "trusted attestations require parent-held BEASTMODE_ATTESTATION_KEY "
            "(hex) and BEASTMODE_ATTESTATION_RUN_ID"
        )
    return key, run_id


def _attestation_records(
    source: Path, *, key: bytes, run_id: str
) -> list[dict]:
    if source.is_symlink():
        raise MetadataLimitError("attestation source must not be a symlink")
    if source.is_dir():
        paths: list[Path] = []
        with os.scandir(source) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > MAX_SCANNED_ENTRIES:
                    raise MetadataLimitError(
                        f"attestation directory exceeds {MAX_SCANNED_ENTRIES} entries"
                    )
                path = source / entry.name
                if path.suffix.lower() == ".json":
                    paths.append(path)
        paths.sort()
    else:
        paths = [source]
    records: list[dict] = []
    for path in paths:
        metadata = path.stat()
        if metadata.st_uid not in {0, os.geteuid()} or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise MetadataLimitError(
                "attestation files must be current-user/root owned and not group/world writable"
            )
        body = _load_json(path)
        values = body.get("attestations") if isinstance(body, dict) else None
        if values is None:
            values = [body]
        if not isinstance(values, list):
            raise MetadataLimitError("attestations must be a JSON list or object")
        for value in values:
            if not isinstance(value, dict):
                raise MetadataLimitError("each attestation must be a JSON object")
            if not all(
                isinstance(value.get(key), str) and value.get(key)
                for key in (*ATTESTATION_FIELDS, "signature")
            ):
                raise MetadataLimitError(
                    "attestation requires authenticated child/model/run/result fields"
                )
            if value["run_id"] != run_id:
                raise MetadataLimitError("attestation does not bind the expected run id")
            expected_signature = sign_attestation(value, key)
            if not hmac.compare_digest(value["signature"], expected_signature):
                raise MetadataLimitError("attestation authentication failed")
            records.append(value)
            if len(records) > MAX_META_FILES:
                raise MetadataLimitError(
                    f"attestation count cannot exceed {MAX_META_FILES}"
                )
    return records


def load_attestations(
    target: Path,
    source: Path | None,
    *,
    attestation_key: bytes | None,
    attestation_run_id: str | None,
) -> dict[str, dict]:
    """Load parent-owned evidence outside the worker-writable run tree."""
    if source is None:
        return {}
    if not isinstance(attestation_key, bytes) or len(attestation_key) < 32:
        raise MetadataLimitError("authenticated attestations require a parent-held key")
    if not isinstance(attestation_run_id, str) or not attestation_run_id:
        raise MetadataLimitError("authenticated attestations require a run id")
    target_resolved = target.resolve()
    source_resolved = source.resolve()
    if source_resolved == target_resolved or target_resolved in source_resolved.parents:
        raise MetadataLimitError(
            "attestations must be outside the worker-writable run directory"
        )
    metadata = source_resolved.stat()
    if metadata.st_uid not in {0, os.geteuid()} or stat.S_IMODE(metadata.st_mode) & 0o022:
        raise MetadataLimitError(
            "attestation source must be current-user/root owned and not group/world writable"
        )
    records = _attestation_records(
        source_resolved, key=attestation_key, run_id=attestation_run_id
    )
    result: dict[str, dict] = {}
    for record in records:
        child_id = str(record["id"])
        if child_id in result:
            raise MetadataLimitError(
                f"duplicate trusted attestation id: {safe_report_text(child_id)}"
            )
        result[child_id] = record
    return result


def load_rows(target: Path, attestations: dict[str, dict] | None = None) -> list[Row]:
    rows = []
    attestations = attestations or {}
    for path in find_meta_files(target):
        try:
            body = _load_json(path)
            row_data = body if isinstance(body, dict) else None
            row_id = _first(row_data or {}, "id", "name") or path.stem
            rows.append(Row(
                path,
                row_data,
                error=None if isinstance(body, dict) else "meta must be a JSON object",
                attestation=attestations.get(row_id),
            ))
        except (OSError, json.JSONDecodeError, RecursionError, MetadataLimitError) as e:
            rows.append(Row(path, None, error=safe_report_text(e)))
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
        batch = _load_json(path)
        tasks = batch.get("tasks") if isinstance(batch, dict) else None
        if not isinstance(tasks, list):
            raise ValueError(
                f"{safe_report_text(source)} has no 'tasks' list to read child ids from"
            )
        ids = [str(t.get("id")) for t in tasks if isinstance(t, dict) and t.get("id")]
    else:
        ids = [part.strip() for part in source.split(",") if part.strip()]
    if len(ids) > MAX_META_FILES:
        raise ValueError(f"expected child count cannot exceed {MAX_META_FILES}")
    duplicates = sorted({child_id for child_id in ids if ids.count(child_id) > 1})
    if duplicates:
        names = ", ".join(safe_report_text(child_id) for child_id in duplicates)
        raise ValueError(f"expected child ids must be unique; duplicates: {names}")
    return ids


def check(target: Path, allow_empty: bool = False, strict: bool = False,
          expect: list[str] | None = None,
          attestations: Path | None = None,
          attestation_key: bytes | None = None,
          attestation_run_id: str | None = None) -> GateResult:
    """Run the provenance gate over a directory of child metas."""
    if expect is not None and len(expect) != len(set(expect)):
        return GateResult(
            [],
            ["UNVERIFIABLE: expected child ids must be unique"],
            1,
        )
    if target.is_symlink() or not target.is_dir():
        return GateResult([], [f"not a regular directory: {safe_report_text(target)}"], 2)

    try:
        trusted_attestations = load_attestations(
            target,
            attestations,
            attestation_key=attestation_key,
            attestation_run_id=attestation_run_id,
        )
        rows = load_rows(target, trusted_attestations)
    except (OSError, json.JSONDecodeError, RecursionError, MetadataLimitError) as exc:
        return GateResult(
            [],
            [f"UNVERIFIABLE: metadata scan rejected: {safe_report_text(exc)}"],
            1,
        )
    if not rows and not expect:
        if allow_empty:
            return GateResult(
                [],
                [f"no child metas found in {safe_report_text(target)} (--allow-empty)"],
                0,
            )
        # Fail closed: a batch that produced no provable child did not
        # produce a validated one either.
        return GateResult(
            [],
            [
                f"UNVERIFIABLE: no child metas found in {safe_report_text(target)}; "
                "no child's model can be proven, so nothing here is validated. "
                "Pass --allow-empty if this batch legitimately had no children."
            ],
            1,
        )

    messages = [row.line() for row in rows if row.failed]

    observed_ids = [row.raw_id for row in rows]
    duplicate_observed = sorted(
        {child_id for child_id in observed_ids if observed_ids.count(child_id) > 1}
    )
    for child_id in duplicate_observed:
        messages.append(
            f"UNVERIFIABLE: duplicate observed child id {safe_report_text(child_id)!r}"
        )

    # A child that died before writing anything leaves no file, so scanning
    # what is present can never notice it — one surviving sibling would carry
    # the batch to exit 0. Only the batch's own list of ids can catch that.
    missing_children = []
    if expect:
        seen = {row.raw_id for row in rows}
        missing_children = [cid for cid in expect if cid not in seen]
        for cid in missing_children:
            messages.append(
                f"UNVERIFIABLE: expected child {safe_report_text(cid)!r} wrote no meta in "
                f"{safe_report_text(target)}; "
                "it cannot be shown to have run under the pinned model"
            )
    incomplete = [row for row in rows if row.missing_fields and not row.failed]
    for row in incomplete:
        messages.append(
            f"INCOMPLETE: {row.id} missing {', '.join(row.missing_fields)} "
            f"({safe_report_text(row.path)})"
        )

    failed = (
        any(row.failed for row in rows)
        or bool(missing_children)
        or bool(duplicate_observed)
    )
    if failed or (strict and incomplete):
        return GateResult(rows, messages, 1)
    return GateResult(rows, messages, 0)


def main(argv: list[str]) -> int:
    target = None
    allow_empty = False
    strict = False
    expect: list[str] | None = None
    attestations: Path | None = None
    trust_attestations = False
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
                print(f"acn_meta: --expect: {safe_report_text(e)}", file=sys.stderr)
                return 2
        elif arg == "--attestations":
            if not args:
                print(
                    "acn_meta: --attestations needs a JSON file or directory",
                    file=sys.stderr,
                )
                return 2
            attestations = Path(args.pop(0))
        elif arg == "--trust-attestations":
            trust_attestations = True
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
        print("usage: acn_meta.py --check <dir> --attestations <json|dir> "
              "--trust-attestations [--expect <batch.json|id,...>] "
              "[--allow-empty] [--strict]", file=sys.stderr)
        return 2
    if attestations is not None and not trust_attestations:
        print(
            "acn_meta: --attestations requires --trust-attestations; assert only "
            "for parent/provider evidence outside worker-writable paths",
            file=sys.stderr,
        )
        return 2

    attestation_key = None
    attestation_run_id = None
    if attestations is not None:
        try:
            attestation_key, attestation_run_id = attestation_credentials_from_environment()
        except MetadataLimitError as exc:
            print(
                f"acn_meta: {safe_report_text(exc)}",
                file=sys.stderr,
            )
            return 2

    result = check(
        target,
        allow_empty=allow_empty,
        strict=strict,
        expect=expect,
        attestations=attestations,
        attestation_key=attestation_key,
        attestation_run_id=attestation_run_id,
    )
    stream = sys.stderr if result.exit_code == 2 else sys.stdout
    for message in result.messages:
        print(message, file=stream)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
