#!/usr/bin/env python3
"""Reproducible harness for the Beastmode effectiveness study.

The harness deliberately keeps orchestration outside of the model-call path.  A
prepared run freezes the task inputs and call schedule; ``invoke`` executes one
explicit call; ``score`` executes one candidate against the held-out cases; and
``analyze`` consumes only retained records.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import json
import math
import os
import random
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURES = ROOT / "fixtures"
DEFAULT_RUNS = ROOT / "runs"
DEFAULT_PROTOCOL = ROOT / "PROTOCOL.md"
SEED = 20260911
TASK_IDS = tuple(f"task{i:02d}" for i in range(1, 13))
REPETITIONS = (1, 2)
ARMS = ("baseline", "beastmode")
CALL_STAGES = ("single", "self_revision", "beast_initial", "beast_revision")
FINAL_STAGES = ("single", "self_revision", "beast_revision")
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "max"
MODEL_TIMEOUT_SECONDS = 600.0
CASE_CPU_SECONDS = 2
CASE_WALL_SECONDS = 5.0
CASE_MEMORY_BYTES = 256 * 1024 * 1024
CASE_STDOUT_BYTES = 1024 * 1024
BOOTSTRAP_SAMPLES = 10_000
TAINTED_DEPENDENCY_ERRORS = frozenset(
    {
        "tool_use_forbidden",
        "model_provenance_unverified",
        "candidate_provenance_mismatch",
        "candidate_changed_after_invoke",
        "invalid_invocation",
        "model_call_timeout",
        "launch_error",
        "missing_output",
        "missing_predecessor_invocation",
        "ambiguous_code_fence_or_extra_prose",
        "malformed_code",
        "missing_solve",
    }
)
REPAIRABLE_PREDECESSOR_ERRORS = frozenset({"syntax_error", "missing_solve", "ambiguous_code_fence_or_extra_prose"})
INVOCATION_TERMINAL_STATUSES = frozenset({"completed", "failed", "timeout", "launch_error"})
SCORE_INPUT_SEAL = "score_input_seal.json"

PROMPT_TEMPLATE = """You are solving one deterministic Python programming task.

Return exactly one complete Python module exposing solve(payload). The function
must accept one JSON value and return one JSON value. Return code only, with an
optional single Markdown code fence. Do not use tools, inspect files, or call
the network. The public specification and examples below are the full task
contract.

PUBLIC SPECIFICATION
{public_spec}

PUBLIC EXAMPLES
{public_examples}
"""


class HarnessError(RuntimeError):
    """Expected, user-actionable harness failure."""


class IsolationUnavailable(HarnessError):
    """The requested candidate isolation cannot be provided."""


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"invalid JSON in {path}: {exc}") from exc


def git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT.parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def safe_run_id(run_id: str) -> str:
    if not run_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise HarnessError("run id must contain only letters, digits, '.', '_' or '-' and be at most 128 characters")
    return run_id


def resolve_run(run: str | Path, runs_dir: Path = DEFAULT_RUNS) -> Path:
    candidate = Path(run)
    if not candidate.is_absolute() and len(candidate.parts) == 1:
        candidate = runs_dir / candidate
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise HarnessError(f"run directory does not exist: {candidate}")
    return candidate


def _relative(path: Path, base: Path) -> str:
    # Research fixtures may live in a sibling worktree while a run is being
    # prepared.  ``..`` relative paths remain portable within this workspace
    # and avoid putting an absolute machine path in the manifest.
    return os.path.relpath(path.resolve(), base.resolve()).replace(os.sep, "/")


def _file_record(path: Path, base: Path) -> dict[str, str]:
    if not path.is_file():
        raise HarnessError(f"required frozen file is missing: {path}")
    return {"path": _relative(path, base), "sha256": sha256_file(path)}


def _fixture_files(fixtures_dir: Path) -> list[Path]:
    files: list[Path] = []
    required = ("public.md", "public_examples.json", "private_cases.json", "reference.py", "mutants.json")
    for task_id in TASK_IDS:
        task_dir = fixtures_dir / task_id
        for name in required:
            path = task_dir / name
            if not path.is_file():
                raise HarnessError(f"missing required fixture: {path}")
            files.append(path)
        for extra in sorted(task_dir.iterdir()):
            if extra.is_file() and extra not in files:
                files.append(extra)
    return files


def _validate_fixture_json(fixtures_dir: Path) -> None:
    for task_id in TASK_IDS:
        examples = read_json(fixtures_dir / task_id / "public_examples.json")
        cases = read_json(fixtures_dir / task_id / "private_cases.json")
        mutants = read_json(fixtures_dir / task_id / "mutants.json")
        if not isinstance(examples, (list, dict)):
            raise HarnessError(f"{task_id}/public_examples.json must be a JSON list or object")
        if not isinstance(cases, list):
            raise HarnessError(f"{task_id}/private_cases.json must be a JSON list")
        for index, case in enumerate(cases):
            if not isinstance(case, dict) or "input" not in case or "expected" not in case:
                raise HarnessError(f"{task_id}/private_cases.json case {index} needs input and expected")
            if "id" not in case and "private_id" not in case:
                raise HarnessError(f"{task_id}/private_cases.json case {index} needs a private id")
        if not isinstance(mutants, (list, dict)):
            raise HarnessError(f"{task_id}/mutants.json must be a JSON list or object")
        try:
            reference_tree = ast.parse((fixtures_dir / task_id / "reference.py").read_text(encoding="utf-8"))
            if not any(isinstance(node, ast.FunctionDef) and node.name == "solve" for node in reference_tree.body):
                raise SyntaxError("reference does not expose solve")
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            raise HarnessError(f"invalid reference.py for {task_id}: {exc}") from exc


def _run_fixture_validator(fixtures_dir: Path) -> dict[str, Any] | None:
    """Run the repository's aggregate fixture validator when it is present."""
    validator = fixtures_dir / "validate.py"
    if not validator.is_file():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(validator), "--root", str(fixtures_dir), "--expected-tasks", str(len(TASK_IDS))],
            cwd=str(fixtures_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HarnessError(f"fixture validator could not run: {exc}") from exc
    raw = result.stdout.strip()
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"fixture validator did not emit one JSON receipt: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("ok") is not True or result.returncode != 0:
        detail = result.stderr.strip()[:500]
        raise HarnessError(f"fixture validator failed: {detail or 'receipt.ok is not true'}")
    return receipt


def make_schedule(seed: int = SEED) -> list[dict[str, Any]]:
    """Build the amendment-A serial call schedule without executing anything."""
    rng = random.Random(seed)
    blocks = [(task_id, repetition) for task_id in TASK_IDS for repetition in REPETITIONS]
    rng.shuffle(blocks)
    schedule: list[dict[str, Any]] = []
    call_index = 0
    for block_index, (task_id, repetition) in enumerate(blocks):
        arms = list(ARMS)
        rng.shuffle(arms)
        for arm in arms:
            stages = ("single", "self_revision") if arm == "baseline" else ("beast_initial", "beast_revision")
            for stage in stages:
                call_index += 1
                schedule.append(
                    {
                        "call_index": call_index,
                        "block_index": block_index + 1,
                        "task_id": task_id,
                        "repetition": repetition,
                        "arm": arm,
                        "stage": stage,
                    }
                )
    return schedule


def make_final_matrix() -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for task_id in TASK_IDS:
        for repetition in REPETITIONS:
            for arm, stage in (("single", "single"), ("self_revision", "self_revision"), ("beastmode", "beast_revision")):
                matrix.append(
                    {
                        "task_id": task_id,
                        "repetition": repetition,
                        "arm": arm,
                        "stage": stage,
                    }
                )
    return matrix


def _hash_inventory(
    fixtures_dir: Path,
    protocol_path: Path,
    plans_dir: Path | None,
    prompt_templates_dir: Path | None,
) -> list[dict[str, str]]:
    inventory = [_file_record(protocol_path, ROOT)]
    for path in _fixture_files(fixtures_dir):
        inventory.append(_file_record(path, ROOT))
    validator = fixtures_dir / "validate.py"
    if validator.is_file():
        inventory.append(_file_record(validator, ROOT))
    # These are the code and test inputs used to create the run, not mutable results.
    for path in (
        ROOT / "harness.py",
        ROOT / "test_harness.py",
        ROOT / "driver.py",
        ROOT / "test_driver.py",
        ROOT / "environment.json",
    ):
        if path.is_file():
            inventory.append(_file_record(path, ROOT))
    if plans_dir is not None and plans_dir.is_dir():
        for path in sorted(p for p in plans_dir.rglob("*") if p.is_file()):
            inventory.append(_file_record(path, ROOT))
    if prompt_templates_dir is not None and prompt_templates_dir.is_dir():
        for path in sorted(p for p in prompt_templates_dir.rglob("*") if p.is_file()):
            inventory.append(_file_record(path, ROOT))
    return inventory


def _default_run_id() -> str:
    return "run-" + _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sibling_effectiveness_dir() -> Path:
    return ROOT.parents[1].parent / "beastmode-evals" / "evals" / "effectiveness"


def prepare_run(
    run_id: str | None = None,
    *,
    fixtures_dir: Path = DEFAULT_FIXTURES,
    protocol_path: Path = DEFAULT_PROTOCOL,
    runs_dir: Path = DEFAULT_RUNS,
    plans_dir: Path | None = None,
    prompt_templates_dir: Path | None = None,
) -> Path:
    """Freeze a run manifest and refuse to overwrite an existing run directory."""
    run_id = safe_run_id(run_id or _default_run_id())
    fixtures_dir = fixtures_dir.resolve()
    protocol_path = protocol_path.resolve()
    runs_dir = runs_dir.resolve()
    sibling = _sibling_effectiveness_dir()
    if plans_dir is None:
        if (ROOT / "plans").is_dir():
            plans_dir = ROOT / "plans"
        elif (sibling / "plans").is_dir():
            plans_dir = sibling / "plans"
    if prompt_templates_dir is None:
        if (ROOT / "prompts").is_dir():
            prompt_templates_dir = ROOT / "prompts"
        elif (sibling / "prompts").is_dir():
            prompt_templates_dir = sibling / "prompts"
    if plans_dir is not None:
        plans_dir = plans_dir.resolve()
    if prompt_templates_dir is not None:
        prompt_templates_dir = prompt_templates_dir.resolve()
    if not protocol_path.is_file():
        raise HarnessError(f"protocol is missing: {protocol_path}")
    _validate_fixture_json(fixtures_dir)
    fixture_receipt = _run_fixture_validator(fixtures_dir)
    inventory = _hash_inventory(fixtures_dir, protocol_path, plans_dir, prompt_templates_dir)
    run_dir = runs_dir / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite existing run: {run_dir}") from exc

    prompt_template_path = run_dir / "prompt_template.txt"
    common_template = prompt_templates_dir / "common.txt" if prompt_templates_dir else None
    if common_template is not None and common_template.is_file():
        prompt_template_path.write_bytes(common_template.read_bytes())
    else:
        # Test and bootstrap fallback.  A production run with prompt templates
        # present freezes common.txt above and hashes every stage template too.
        prompt_template_path.write_text(PROMPT_TEMPLATE, encoding="utf-8")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "python_version": sys.version,
        "base_git_revision": git_revision(),
        "seed": SEED,
        "protocol_path": _relative(protocol_path, ROOT),
        "protocol_sha256": sha256_file(protocol_path),
        "fixtures_root": _relative(fixtures_dir, ROOT),
        "task_ids": list(TASK_IDS),
        "repetitions": list(REPETITIONS),
        "arms": list(ARMS),
        "call_stages": list(CALL_STAGES),
        "final_stages": list(FINAL_STAGES),
        "schedule": make_schedule(),
        "final_matrix": make_final_matrix(),
        "file_inventory": inventory,
        "fixed_prompt_template": {
            "path": "prompt_template.txt",
            "sha256": sha256_file(prompt_template_path),
            "source": _relative(common_template, ROOT) if common_template and common_template.is_file() else "generated-PROMPT_TEMPLATE",
        },
        "director_plans": [item for item in inventory if "plans/" in item["path"]],
        "prompt_templates": [item for item in inventory if "prompts/" in item["path"]],
        "fixture_validator": next((item for item in inventory if item["path"] == _relative(fixtures_dir / "validate.py", ROOT)), None),
        "fixture_validation": (
            {
                "receipt": fixture_receipt,
                "receipt_sha256": sha256_text(json_dump(fixture_receipt)),
            }
            if fixture_receipt is not None
            else None
        ),
        "planned_calls": 96,
        "planned_final_artifacts": 72,
        "status": "frozen",
    }
    manifest_path = run_dir / "manifest.json"
    write_json(manifest_path, manifest)
    (run_dir / "manifest.sha256").write_text(sha256_file(manifest_path) + "\n", encoding="ascii")
    return run_dir


def _manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise HarnessError(f"frozen manifest is missing: {manifest_path}")
    sidecar = run_dir / "manifest.sha256"
    if not sidecar.is_file() or sidecar.read_text(encoding="ascii").strip() != sha256_file(manifest_path):
        raise HarnessError("frozen manifest has been modified or its integrity record is missing")
    value = read_json(manifest_path)
    if not isinstance(value, dict) or value.get("status") != "frozen":
        raise HarnessError("manifest is not a frozen run manifest")
    return value


def verify_frozen_inputs(run_dir: Path) -> dict[str, Any]:
    """Verify every input named by the manifest before invocation or scoring."""
    manifest = _manifest(run_dir)
    for item in manifest.get("file_inventory", []):
        path = ROOT / item["path"]
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise HarnessError(f"frozen input changed: {item['path']}")
    template = run_dir / manifest["fixed_prompt_template"]["path"]
    if not template.is_file() or sha256_file(template) != manifest["fixed_prompt_template"]["sha256"]:
        raise HarnessError("fixed prompt template changed")
    return manifest


def _schedule_entry(manifest: Mapping[str, Any], task_id: str, repetition: int, stage: str) -> dict[str, Any]:
    for entry in manifest.get("schedule", []):
        if entry.get("task_id") == task_id and entry.get("repetition") == repetition and entry.get("stage") == stage:
            return dict(entry)
    raise HarnessError(f"{task_id} repetition {repetition} stage {stage} is not in the frozen schedule")


def _invocation_record_path(run_dir: Path, entry: Mapping[str, Any]) -> Path:
    return run_dir / "invocations" / f"{entry['task_id']}_rep{entry['repetition']}_{entry['stage']}" / "record.json"


def _read_terminal_invocation(run_dir: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    path = _invocation_record_path(run_dir, entry)
    if not path.is_file():
        raise HarnessError(f"schedule predecessor is missing: {path}")
    record = read_json(path)
    if not isinstance(record, dict):
        raise HarnessError(f"schedule predecessor record is not an object: {path}")
    if record.get("status") not in INVOCATION_TERMINAL_STATUSES:
        raise HarnessError(f"schedule predecessor is not terminal: {path}")
    for key in ("task_id", "repetition", "stage"):
        if key in record and record[key] != entry[key]:
            raise HarnessError(f"schedule predecessor identity mismatch: {path}")
    return record


def _require_schedule_predecessors_terminal(run_dir: Path, manifest: Mapping[str, Any], task_id: str, repetition: int, stage: str) -> None:
    """Guard the CLI call boundary with the frozen serial schedule."""
    entry = _schedule_entry(manifest, task_id, repetition, stage)
    try:
        call_index = int(entry["call_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HarnessError("frozen schedule entry has no valid call index") from exc
    schedule = manifest.get("schedule")
    if not isinstance(schedule, list):
        raise HarnessError("frozen manifest has no schedule")
    for predecessor in schedule:
        if not isinstance(predecessor, dict):
            raise HarnessError("frozen schedule contains an invalid entry")
        try:
            predecessor_index = int(predecessor["call_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HarnessError("frozen schedule contains an entry without a valid call index") from exc
        if predecessor_index < call_index:
            _read_terminal_invocation(run_dir, predecessor)


def _score_input_snapshot(run_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    schedule = manifest.get("schedule")
    if not isinstance(schedule, list) or len(schedule) != int(manifest.get("planned_calls", 96)):
        raise HarnessError("cannot score before all planned invocation records exist")
    for entry in schedule:
        if not isinstance(entry, dict):
            raise HarnessError("frozen schedule contains an invalid entry")
        _read_terminal_invocation(run_dir, entry)

    review_paths: list[Path] = []
    for task_id in TASK_IDS:
        for repetition in REPETITIONS:
            review = run_dir / "reviews" / f"{task_id}_rep{repetition}.md"
            if not review.is_file():
                raise HarnessError(f"director review is missing: {review}")
            review_paths.append(review)

    files: set[Path] = set(review_paths)
    for entry in schedule:
        call_dir = _invocation_record_path(run_dir, entry).parent
        files.update(path for path in call_dir.rglob("*") if path.is_file())
    return {
        "schema_version": 1,
        "planned_calls": len(schedule),
        "director_reviews": len(review_paths),
        "files": [
            {"path": path.relative_to(run_dir).as_posix(), "sha256": sha256_file(path)}
            for path in sorted(files)
        ],
    }


def _seal_score_inputs(run_dir: Path, manifest: Mapping[str, Any]) -> Path:
    """Seal terminal invocation artifacts and reviews at the CLI score boundary."""
    snapshot = _score_input_snapshot(run_dir, manifest)
    seal_path = run_dir / SCORE_INPUT_SEAL
    if seal_path.is_file():
        existing = read_json(seal_path)
        if json_dump(existing) != json_dump(snapshot):
            raise HarnessError("sealed invocation or review input changed")
    else:
        write_json(seal_path, snapshot)
    return seal_path


def _validate_task_rep_stage(task_id: str, repetition: int, stage: str, *, final: bool = False) -> None:
    if task_id not in TASK_IDS:
        raise HarnessError(f"unknown task: {task_id}")
    if repetition not in REPETITIONS:
        raise HarnessError(f"repetition must be 1 or 2, got {repetition}")
    allowed = FINAL_STAGES if final else CALL_STAGES
    if stage not in allowed:
        raise HarnessError(f"stage must be one of {', '.join(allowed)}")


def _is_private_path(path: Path, fixtures_dir: Path) -> bool:
    try:
        rel = path.resolve().relative_to(fixtures_dir.resolve()).parts
    except ValueError:
        return False
    return any(part in {"private_cases.json", "reference.py", "mutants.json"} for part in rel)


def _prompt_contains_private_case(prompt: str, fixtures_dir: Path, task_id: str) -> bool:
    """Catch accidental inclusion of a complete held-out case in a prompt."""
    private_path = fixtures_dir / task_id / "private_cases.json"
    try:
        raw = private_path.read_text(encoding="utf-8").strip()
        if raw and raw in prompt:
            return True
        cases = read_json(private_path)
    except (OSError, UnicodeDecodeError, HarnessError):
        return False
    if not isinstance(cases, list):
        return False
    for case in cases:
        if isinstance(case, dict):
            # Search the whole case as a compact object, avoiding false
            # positives from a single common scalar such as 0 or "".
            compact = json_dump(case)
            if len(compact) >= 16 and compact in prompt.replace(" ", ""):
                return True
    return False


def _write_exclusive(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding=encoding) as fh:
            fh.write(data)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite existing record: {path}") from exc


def _codex_cli_version(codex: str) -> str | None:
    try:
        result = subprocess.run(
            [codex, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT.parents[1]),
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or result.stderr).decode("utf-8", "replace").strip()
    return value[:200] if value else None


def _extract_usage(events: Sequence[Any]) -> dict[str, int | None]:
    values: dict[str, int | None] = {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None, "reasoning_tokens": None}
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "cached_input_tokens": ("cached_input_tokens", "cache_read_input_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "reasoning_tokens": ("reasoning_tokens",),
    }
    for event in events:
        if not isinstance(event, dict):
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        for target, names in aliases.items():
            for name in names:
                value = usage.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    values[target] = value
                    break
    return values


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _event_text(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    candidates: list[Any] = []
    item = event.get("item")
    if isinstance(item, dict):
        candidates.extend((item.get("text"), item.get("content")))
    candidates.extend((event.get("text"), event.get("content"), event.get("output")))
    for value in candidates:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = [part.get("text", "") for part in value if isinstance(part, dict) and isinstance(part.get("text"), str)]
            if parts:
                return "".join(parts)
    return ""


def parse_jsonl_output(raw: str) -> tuple[list[Any], str, str | None, bool]:
    """Return events, final text, thread id, and whether any tool event occurred."""
    events: list[Any] = []
    malformed = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            malformed = True
    thread_id: str | None = None
    texts: list[str] = []
    tool_used = False
    for event in events:
        if isinstance(event, dict):
            for obj in _walk_dicts(event):
                if isinstance(obj.get("thread_id"), str):
                    thread_id = obj["thread_id"]
            type_names = [str(obj.get("type", "")).lower() for obj in _walk_dicts(event)]
            if any(token in type_name for type_name in type_names for token in ("tool", "command", "mcp", "function_call", "shell")):
                tool_used = True
            text = _event_text(event)
            if text:
                texts.append(text)
    final_text = texts[-1] if texts else (raw if malformed else "")
    return events, final_text, thread_id, tool_used


_FENCE_RE = re.compile(r"^```(?:[A-Za-z0-9_+-]+)?\s*\n([\s\S]*?)\n```\s*$")


def parse_solution(output: str) -> tuple[str | None, str | None]:
    """Extract one Python module; prose or multiple fences are invalid."""
    if not isinstance(output, str) or not output.strip():
        return None, "missing_output"
    stripped = output.strip()
    fence_count = stripped.count("```")
    if fence_count:
        match = _FENCE_RE.fullmatch(stripped)
        if not match or fence_count != 2:
            return None, "ambiguous_code_fence_or_extra_prose"
        source = match.group(1)
    else:
        source = stripped
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, "syntax_error"
    if not any(isinstance(node, ast.FunctionDef) and node.name == "solve" for node in tree.body):
        return None, "missing_solve"
    return source + ("\n" if not source.endswith("\n") else ""), None


def _runtime_model_evidence(thread_id: str | None, started_at: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "thread_id": thread_id,
        "verified": False,
        "model": None,
        "effort": None,
        "source": "turn_context",
    }
    if not thread_id:
        result["reason"] = "missing_thread_id"
        return result
    sessions = Path.home() / ".codex" / "sessions"
    if not sessions.is_dir():
        result["reason"] = "sessions_directory_missing"
        return result
    date_part = None
    if started_at:
        try:
            date_part = _dt.datetime.fromisoformat(started_at.replace("Z", "+00:00")).strftime("%Y/%m/%d")
        except ValueError:
            pass
    def is_exact_rollout(path: Path) -> bool:
        return path.name.startswith("rollout-") and path.name.endswith(f"-{thread_id}.jsonl")

    files: list[Path] = []
    if date_part:
        files = sorted(path for path in (sessions / date_part).glob("rollout-*.jsonl") if is_exact_rollout(path))
    if not files:
        # Fall back to exact rollout filenames only; never search transcript content.
        files = sorted(path for path in sessions.rglob("rollout-*.jsonl") if is_exact_rollout(path))
    if not files:
        result["reason"] = "rollout_not_found"
        return result

    session_meta_seen = False
    session_meta_mismatch = False
    contexts: list[tuple[Any, Any]] = []
    for path in files:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get("type")
                    payload = event.get("payload")
                    if event_type == "session_meta" and isinstance(payload, dict):
                        session_meta_seen = True
                        if payload.get("id") != thread_id:
                            session_meta_mismatch = True
                    elif event_type == "turn_context":
                        if not isinstance(payload, dict):
                            contexts.append((None, None))
                            continue
                        model = payload.get("model")
                        effort = payload.get("effort", payload.get("model_reasoning_effort", payload.get("reasoning_effort")))
                        contexts.append((model, effort))
        except (OSError, UnicodeError):
            continue
    if not session_meta_seen:
        result["reason"] = "session_meta_not_found"
        return result
    if session_meta_mismatch:
        result["reason"] = "session_meta_mismatch"
        return result
    if not contexts:
        result["reason"] = "turn_context_not_found"
        return result
    result["model"], result["effort"] = contexts[-1]
    if all(model == MODEL and effort == REASONING_EFFORT for model, effort in contexts):
        result["verified"] = True
        return result
    result["reason"] = "turn_context_mismatch"
    return result


def _terminate_process(proc: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _collect_process(proc: subprocess.Popen[bytes], timeout: float, stdout_limit: int | None = None) -> tuple[bytes, bytes, bool, bool]:
    """Collect bounded process output without restarting a timed-out process."""
    selector = selectors.DefaultSelector()
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
    stdout = bytearray()
    stderr = bytearray()
    timed_out = False
    overflow = False
    deadline = time.monotonic() + timeout
    while selector.get_map() or proc.poll() is None:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0 and proc.poll() is None:
            timed_out = True
            _terminate_process(proc)
        events = selector.select(min(remaining, 0.1) if remaining else 0.05)
        for key, _ in events:
            try:
                data = os.read(key.fd, 65536)
            except OSError:
                data = b""
            if not data:
                try:
                    selector.unregister(key.fileobj)
                except Exception:
                    pass
                continue
            if key.fileobj is proc.stdout:
                stdout.extend(data)
                if stdout_limit is not None and len(stdout) > stdout_limit:
                    overflow = True
                    _terminate_process(proc)
            else:
                stderr.extend(data[: max(0, 1024 * 1024 - len(stderr))])
        if proc.poll() is not None and not selector.get_map():
            break
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _terminate_process(proc)
        proc.wait()
    selector.close()
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()
    return bytes(stdout), bytes(stderr), timed_out, overflow


def invoke_call(
    run: str | Path,
    task_id: str,
    repetition: int,
    stage: str,
    prompt_path: Path,
    *,
    codex: str = "codex",
    timeout: float = MODEL_TIMEOUT_SECONDS,
    runs_dir: Path = DEFAULT_RUNS,
) -> Path:
    """Execute exactly one explicitly requested native Codex call."""
    if timeout <= 0 or timeout > MODEL_TIMEOUT_SECONDS:
        raise HarnessError(f"model call timeout must be between 0 and {MODEL_TIMEOUT_SECONDS:g} seconds")
    run_dir = resolve_run(run, runs_dir)
    manifest = verify_frozen_inputs(run_dir)
    _validate_task_rep_stage(task_id, repetition, stage)
    _schedule_entry(manifest, task_id, repetition, stage)
    prompt_path = prompt_path.resolve()
    if not prompt_path.is_file():
        raise HarnessError(f"prompt file is missing: {prompt_path}")
    fixtures_dir = ROOT / manifest["fixtures_root"]
    if _is_private_path(prompt_path, fixtures_dir):
        raise HarnessError("private/reference fixture cannot be used as a model prompt")
    prompt = prompt_path.read_text(encoding="utf-8")
    if _prompt_contains_private_case(prompt, fixtures_dir, task_id):
        raise HarnessError("prompt appears to contain a complete held-out case")
    call_dir = run_dir / "invocations" / f"{task_id}_rep{repetition}_{stage}"
    try:
        call_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HarnessError(f"refusing to overwrite completed or live invocation: {call_dir}") from exc
    saved_prompt = call_dir / "prompt.txt"
    saved_prompt.write_text(prompt, encoding="utf-8")
    started_at = utc_now()
    metadata_path = call_dir / "record.json"
    requested = {
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "sandbox": "read-only",
        "tools": "forbidden",
        "cli_version": _codex_cli_version(codex),
        "command": [codex, "exec", "-m", MODEL, "-c", 'model_reasoning_effort="max"', "-s", "read-only", "--json", prompt],
    }
    running = {
        "schema_version": 1,
        "task_id": task_id,
        "repetition": repetition,
        "stage": stage,
        "schedule_entry": _schedule_entry(manifest, task_id, repetition, stage),
        "status": "running",
        "started_at_utc": started_at,
        "prompt_path": "prompt.txt",
        "prompt_sha256": sha256_text(prompt),
        "requested": requested,
    }
    write_json(metadata_path, running)
    command = [codex, "exec", "-m", MODEL, "-c", 'model_reasoning_effort="max"', "-s", "read-only", "--json", prompt]
    launch_error = None
    stdout = b""
    stderr = b""
    timed_out = False
    exit_code: int | None = None
    pid: int | None = None
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT.parents[1]),
            start_new_session=True,
        )
        pid = proc.pid
        running.update({"pid": pid, "pid_recorded_at_utc": utc_now()})
        write_json(metadata_path, running)
        stdout, stderr, timed_out, _ = _collect_process(proc, timeout)
        exit_code = proc.returncode
    except OSError as exc:
        launch_error = f"launch_error: {exc}"
    finished_at = utc_now()
    raw_path = call_dir / "raw.jsonl"
    raw_path.write_bytes(stdout)
    (call_dir / "stderr.log").write_bytes(stderr)
    raw_text = stdout.decode("utf-8", errors="replace")
    events, final_text, thread_id, tool_used = parse_jsonl_output(raw_text)
    output_path = call_dir / "final_output.txt"
    output_path.write_text(final_text, encoding="utf-8")
    parsed_source, parse_error = parse_solution(final_text)
    if tool_used:
        parse_error = "tool_use_forbidden"
        parsed_source = None
    if timed_out:
        parse_error = "model_call_timeout"
        parsed_source = None
    if launch_error:
        parse_error = launch_error
        parsed_source = None
    candidate_path = None
    if parsed_source is not None:
        candidate_path = call_dir / "candidate.py"
        candidate_path.write_text(parsed_source, encoding="utf-8")
    usage = _extract_usage(events)
    finished = {
        **running,
        "status": "timeout" if timed_out else ("launch_error" if launch_error else ("completed" if exit_code == 0 else "failed")),
        "finished_at_utc": finished_at,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "launch_error": launch_error,
        "raw_jsonl_path": "raw.jsonl",
        "stderr_path": "stderr.log",
        "final_output_path": "final_output.txt",
        "candidate_path": "candidate.py" if candidate_path else None,
        "candidate_sha256": sha256_file(candidate_path) if candidate_path else None,
        "thread_id": thread_id,
        "tool_used": tool_used,
        "parse_error": parse_error,
        "usage": usage,
        "runtime": _runtime_model_evidence(thread_id, started_at),
    }
    write_json(metadata_path, finished)
    return metadata_path


def _load_cases(fixtures_dir: Path, task_id: str) -> list[dict[str, Any]]:
    cases = read_json(fixtures_dir / task_id / "private_cases.json")
    if not isinstance(cases, list):
        raise HarnessError(f"private cases for {task_id} are not a list")
    normalized: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or "input" not in case or "expected" not in case:
            raise HarnessError(f"private case {index} for {task_id} lacks input or expected")
        private_id = case.get("id", case.get("private_id"))
        if not isinstance(private_id, str) or not private_id:
            raise HarnessError(f"private case {index} for {task_id} lacks a string id")
        normalized.append({"id": private_id, "input": case["input"], "expected": case["expected"]})
    return normalized


def json_equal(left: Any, right: Any) -> bool:
    """JSON equality with bool/int distinction and mathematical number equality."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, float) and math.isnan(left) or isinstance(right, float) and math.isnan(right):
            return False
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


_CHILD = r'''
import importlib.util, json, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
def reject_constant(value):
    raise ValueError("non-standard JSON number")
payload = json.load(sys.stdin, parse_constant=reject_constant)
spec = importlib.util.spec_from_file_location("candidate", "/candidate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if not callable(getattr(module, "solve", None)):
    raise TypeError("candidate does not expose solve")
answer = module.solve(payload)
sys.stdout.write(json.dumps(answer, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
sys.stdout.write("\n")
'''


def _bwrap_command(candidate_path: Path) -> list[str]:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise IsolationUnavailable(
            "scoring requires bubblewrap with --unshare-all, scrubbed environment, and private mounts; refusing unsafe fallback"
        )
    command = [
        bwrap,
        "--unshare-all",
        "--die-with-parent",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for system_dir in ("/lib", "/lib64"):
        if Path(system_dir).exists():
            command.extend(("--ro-bind", system_dir, system_dir))
    command.extend(("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--clearenv", "--setenv", "PATH", "/usr/bin"))
    command.extend(("--ro-bind", str(candidate_path.resolve()), "/candidate.py", "--chdir", "/", "/usr/bin/python3", "-c", _CHILD))
    return command


def _check_bwrap() -> str:
    """Verify the actual namespace operation before grading any case."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise IsolationUnavailable(
            "scoring requires bubblewrap with --unshare-all, scrubbed environment, and private mounts; refusing unsafe fallback"
        )
    command = [bwrap, "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr"]
    for system_dir in ("/lib", "/lib64"):
        if Path(system_dir).exists():
            command.extend(("--ro-bind", system_dir, system_dir))
    command.extend(("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--clearenv", "--setenv", "PATH", "/usr/bin", "--chdir", "/", "/usr/bin/python3", "-c", "print('ISOLATION_OK')"))
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise IsolationUnavailable(f"bubblewrap preflight failed; refusing unsafe fallback: {exc}") from exc
    if result.returncode != 0 or result.stdout.strip() != b"ISOLATION_OK":
        detail = result.stderr.decode("utf-8", "replace")[:500]
        raise IsolationUnavailable(f"bubblewrap namespace preflight failed; refusing unsafe fallback: {detail}")
    return bwrap


def _run_isolated(candidate_path: Path, payload: Any, *, wall_timeout: float = CASE_WALL_SECONDS) -> dict[str, Any]:
    if wall_timeout <= 0 or wall_timeout > CASE_WALL_SECONDS:
        raise HarnessError(f"case wall timeout must be between 0 and {CASE_WALL_SECONDS:g} seconds")
    command = _bwrap_command(candidate_path)
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise IsolationUnavailable(f"bubblewrap candidate launch failed: {exc}") from exc
    encoded = (json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        assert proc.stdin is not None
        proc.stdin.write(encoded)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        try:
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass
    stdout, stderr, timed_out, overflow = _collect_process(proc, wall_timeout, CASE_STDOUT_BYTES)
    if timed_out:
        return {"status": "candidate_timeout", "stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace")}
    if overflow:
        return {"status": "stdout_limit", "stdout": stdout[:CASE_STDOUT_BYTES].decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace")}
    if proc.returncode != 0:
        status = "candidate_timeout" if proc.returncode in (-signal.SIGXCPU, -signal.SIGKILL) else "candidate_exception"
        return {"status": status, "stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace"), "exit_code": proc.returncode}
    text = ""
    try:
        text = stdout.decode("utf-8", errors="strict")
        answer = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {"status": "non_json_output", "stdout": stdout[:CASE_STDOUT_BYTES].decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace"), "error": str(exc)}
    return {"status": "passed_output", "answer": answer, "stderr": stderr.decode("utf-8", "replace")}


def _candidate_for_call(run_dir: Path, task_id: str, repetition: int, stage: str) -> tuple[Path | None, dict[str, Any] | None]:
    record_path = run_dir / "invocations" / f"{task_id}_rep{repetition}_{stage}" / "record.json"
    if not record_path.is_file():
        return None, None
    record = read_json(record_path)
    if isinstance(record, dict):
        record["_path"] = record_path.as_posix()
    candidate = record.get("candidate_path")
    if not candidate:
        return None, record
    path = record_path.parent / candidate
    return (path if path.is_file() else None), record


def _invocation_candidate_error(candidate_path: Path | None, invocation: dict[str, Any] | None) -> str | None:
    if invocation is None:
        return None
    if invocation.get("status") != "completed" or invocation.get("exit_code") != 0:
        return invocation.get("parse_error") or "invalid_invocation"
    if invocation.get("timed_out"):
        return "model_call_timeout"
    if invocation.get("tool_used"):
        return "tool_use_forbidden"
    if invocation.get("parse_error"):
        return invocation["parse_error"]
    if candidate_path is None:
        return "missing_output"
    expected_path = (Path(invocation.get("_path", "")).parent / invocation.get("candidate_path", "")).resolve() if invocation.get("_path") else candidate_path.resolve()
    try:
        if candidate_path.resolve() != expected_path:
            return "candidate_provenance_mismatch"
    except OSError:
        return "candidate_provenance_mismatch"
    expected_digest = invocation.get("candidate_sha256")
    if not expected_digest or sha256_file(candidate_path) != expected_digest:
        return "candidate_changed_after_invoke"
    runtime = invocation.get("runtime") or {}
    if not runtime.get("verified"):
        return "model_provenance_unverified"
    return None


def _validate_candidate_file(candidate_path: Path | None) -> tuple[str | None, str | None]:
    if candidate_path is None or not candidate_path.is_file():
        return None, "missing_output"
    try:
        source = candidate_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, "malformed_code"
    return parse_solution(source)


def _dependency_taint(run_dir: Path, task_id: str, repetition: int, stage: str) -> str | None:
    if stage == "self_revision":
        predecessor = "single"
    elif stage == "beast_revision":
        predecessor = "beast_initial"
    else:
        return None
    path = run_dir / "invocations" / f"{task_id}_rep{repetition}_{predecessor}" / "record.json"
    if not path.is_file():
        return "missing_predecessor_invocation"
    predecessor_record = read_json(path)
    if not isinstance(predecessor_record, dict):
        return "invalid_invocation"
    if predecessor_record.get("status") != "completed" or predecessor_record.get("exit_code") != 0:
        return str(predecessor_record.get("parse_error") or "invalid_invocation")
    if predecessor_record.get("timed_out"):
        return "model_call_timeout"
    if predecessor_record.get("tool_used"):
        return "tool_use_forbidden"
    runtime = predecessor_record.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("verified") is not True:
        return "model_provenance_unverified"
    parse_error = predecessor_record.get("parse_error")
    if parse_error in REPAIRABLE_PREDECESSOR_ERRORS:
        return None
    if parse_error:
        return str(parse_error) if parse_error in TAINTED_DEPENDENCY_ERRORS else "invalid_invocation"
    candidate_name = predecessor_record.get("candidate_path")
    if not isinstance(candidate_name, str) or not candidate_name:
        return "missing_output"
    candidate_rel = Path(candidate_name)
    if candidate_rel.is_absolute() or ".." in candidate_rel.parts:
        return "candidate_provenance_mismatch"
    candidate_path = path.parent / candidate_rel
    if not candidate_path.is_file():
        return "missing_output"
    expected_digest = predecessor_record.get("candidate_sha256")
    if not isinstance(expected_digest, str) or sha256_file(candidate_path) != expected_digest:
        return "candidate_changed_after_invoke"
    return None


def score_candidate(
    run: str | Path,
    task_id: str,
    repetition: int,
    stage: str,
    *,
    candidate_path: Path | None = None,
    runs_dir: Path = DEFAULT_RUNS,
    wall_timeout: float = CASE_WALL_SECONDS,
) -> Path:
    """Score one artifact, one private case at a time, in a fail-closed sandbox."""
    run_dir = resolve_run(run, runs_dir)
    manifest = verify_frozen_inputs(run_dir)
    _validate_task_rep_stage(task_id, repetition, stage)
    _schedule_entry(manifest, task_id, repetition, stage)
    if candidate_path is None:
        candidate_path, invocation = _candidate_for_call(run_dir, task_id, repetition, stage)
    else:
        invocation = None
        candidate_path = candidate_path.resolve()
    candidate_error = _invocation_candidate_error(candidate_path, invocation)
    source, parse_error = _validate_candidate_file(candidate_path)
    if candidate_error is None:
        candidate_error = parse_error
    execution_error = None if candidate_error == "model_provenance_unverified" else candidate_error
    dependency_taint = _dependency_taint(run_dir, task_id, repetition, stage)
    fixtures_dir = ROOT / manifest["fixtures_root"]
    cases = _load_cases(fixtures_dir, task_id)
    if execution_error is not None:
        case_results = [{"id": case["id"], "passed": False, "status": candidate_error} for case in cases]
        infrastructure_error = None
    else:
        assert candidate_path is not None and source is not None
        try:
            _check_bwrap()
        except IsolationUnavailable as exc:
            score_path = run_dir / "scores" / f"{task_id}_rep{repetition}_{stage}.json"
            infrastructure_record = {
                "schema_version": 1,
                "task_id": task_id,
                "repetition": repetition,
                "stage": stage,
                "arm": {"single": "single", "self_revision": "self_revision", "beast_revision": "beastmode"}.get(stage, stage),
                "candidate_path": str(candidate_path),
                "candidate_error": None,
                "case_count": len(cases),
                "case_results": [],
                "status": "infrastructure_error",
                "infrastructure_error": str(exc),
                "scored_at_utc": utc_now(),
            }
            _write_exclusive(score_path, json.dumps(infrastructure_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            raise
        # Every case gets a fresh process, so state cannot leak between held-out cases.
        case_results = []
        infrastructure_error = None
        for case in cases:
            try:
                result = _run_isolated(candidate_path, case["input"], wall_timeout=wall_timeout)
            except IsolationUnavailable as exc:
                infrastructure_error = str(exc)
                break
            result["id"] = case["id"]
            result["passed"] = result.get("status") == "passed_output" and json_equal(result.get("answer"), case["expected"])
            if result.get("status") == "passed_output" and not result["passed"]:
                result["status"] = "wrong_answer"
            # Expected values never enter the retained child result.
            result.pop("answer", None)
            case_results.append(result)
        if infrastructure_error:
            score_path = run_dir / "scores" / f"{task_id}_rep{repetition}_{stage}.json"
            infrastructure_record = {
                "schema_version": 1,
                "task_id": task_id,
                "repetition": repetition,
                "stage": stage,
                "arm": {"single": "single", "self_revision": "self_revision", "beast_revision": "beastmode"}.get(stage, stage),
                "candidate_path": str(candidate_path),
                "candidate_error": None,
                "case_count": len(cases),
                "case_results": case_results,
                "status": "infrastructure_error",
                "infrastructure_error": infrastructure_error,
                "scored_at_utc": utc_now(),
            }
            _write_exclusive(score_path, json.dumps(infrastructure_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            raise IsolationUnavailable(infrastructure_error)
    passed = sum(1 for case in case_results if case.get("passed"))
    final_arm = {"single": "single", "self_revision": "self_revision", "beast_revision": "beastmode"}.get(stage, stage)
    artifact_solved = bool(case_results) and passed == len(case_results) and parse_error is None and execution_error is None
    evidence_valid = bool(invocation and invocation.get("runtime", {}).get("verified"))
    validated_solved = artifact_solved and evidence_valid and dependency_taint is None
    score_path = run_dir / "scores" / f"{task_id}_rep{repetition}_{stage}.json"
    record = {
        "schema_version": 1,
        "task_id": task_id,
        "repetition": repetition,
        "stage": stage,
        "arm": final_arm,
        "is_final_artifact": stage in FINAL_STAGES,
        "candidate_path": str(candidate_path) if candidate_path else None,
        "candidate_error": candidate_error,
        "dependency_taint": dependency_taint,
        "case_count": len(cases),
        "passed_cases": passed,
        "fraction_passed": (passed / len(cases)) if cases else 0.0,
        "artifact_solved": artifact_solved,
        "solved": validated_solved,
        "case_results": case_results,
        "valid_evidence": evidence_valid,
        "invocation": {"usage": invocation.get("usage"), "started_at_utc": invocation.get("started_at_utc"), "finished_at_utc": invocation.get("finished_at_utc")} if invocation else None,
        "scored_at_utc": utc_now(),
        "status": "scored",
    }
    _write_exclusive(score_path, json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return score_path


def _score_files(run_dir: Path) -> list[dict[str, Any]]:
    scores_dir = run_dir / "scores"
    if not scores_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(scores_dir.glob("*.json")):
        value = read_json(path)
        if isinstance(value, dict):
            value["_path"] = path.as_posix()
            records.append(value)
    return records


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bootstrap_ci(task_differences: Sequence[float], seed: int = SEED, samples: int = BOOTSTRAP_SAMPLES) -> dict[str, Any]:
    if not task_differences:
        return {"mean": None, "lower": None, "upper": None, "samples": samples, "degenerate": False, "warning": "no task differences"}
    rng = random.Random(seed)
    resamples = []
    for _ in range(samples):
        draw = [task_differences[rng.randrange(len(task_differences))] for _ in task_differences]
        resamples.append(sum(draw) / len(draw))
    mean = sum(task_differences) / len(task_differences)
    degenerate = len(set(task_differences)) == 1
    return {
        "mean": mean,
        "lower": _percentile(resamples, 0.025),
        "upper": _percentile(resamples, 0.975),
        "samples": samples,
        "seed": seed,
        "degenerate": degenerate,
        "warning": "all paired task differences are identical; the degenerate interval is descriptive and is not evidence of population equivalence" if degenerate else None,
    }


def _family_differences(task_differences: Mapping[str, float]) -> list[float]:
    """Average adjacent task pairs for the six-family sensitivity check."""
    return [
        (float(task_differences[f"task{i:02d}"]) + float(task_differences[f"task{i + 1:02d}"])) / 2
        for i in range(1, 12, 2)
        if f"task{i:02d}" in task_differences and f"task{i + 1:02d}" in task_differences
    ]


def _invoke_records(run_dir: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    result: dict[tuple[str, int, str], dict[str, Any]] = {}
    directory = run_dir / "invocations"
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*/record.json")):
        record = read_json(path)
        if isinstance(record, dict) and all(key in record for key in ("task_id", "repetition", "stage")):
            result[(record["task_id"], int(record["repetition"]), record["stage"])] = record
    return result


def _call_metrics(invoke_records: Mapping[tuple[str, int, str], dict[str, Any]]) -> dict[str, Any]:
    usage_totals: dict[str, int] = {}
    elapsed: list[float] = []
    by_stage: dict[str, dict[str, Any]] = {}
    for record in invoke_records.values():
        stage = str(record.get("stage", "unknown"))
        stage_row = by_stage.setdefault(stage, {"calls": 0, "usage": {}, "elapsed_seconds": []})
        stage_row["calls"] += 1
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        for name in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"):
            value = usage.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                usage_totals[name] = usage_totals.get(name, 0) + value
                stage_row["usage"][name] = stage_row["usage"].get(name, 0) + value
        try:
            start = _dt.datetime.fromisoformat(str(record["started_at_utc"]).replace("Z", "+00:00"))
            finish = _dt.datetime.fromisoformat(str(record["finished_at_utc"]).replace("Z", "+00:00"))
            seconds = (finish - start).total_seconds()
            elapsed.append(seconds)
            stage_row["elapsed_seconds"].append(seconds)
        except (KeyError, TypeError, ValueError):
            pass
    return {
        "unique_invocation_count": len(invoke_records),
        "usage_totals": usage_totals,
        "elapsed_seconds": elapsed,
        "by_stage": by_stage,
        "note": "Usage fields are reported as returned; cached input and reasoning fields are not added to input/output totals.",
    }


def analyze_run(run: str | Path, *, runs_dir: Path = DEFAULT_RUNS, output_path: Path | None = None) -> Path:
    """Analyze retained score records with fixed denominators and task clustering."""
    run_dir = resolve_run(run, runs_dir)
    manifest = _manifest(run_dir)
    scores = _score_files(run_dir)
    score_map: dict[tuple[str, int, str], dict[str, Any]] = {}
    duplicates: list[str] = []
    for score in scores:
        key = (score.get("task_id"), int(score.get("repetition", 0)), score.get("stage"))
        if key in score_map:
            duplicates.append(str(score.get("_path")))
        else:
            score_map[key] = score
    final_records: dict[str, list[dict[str, Any] | None]] = {arm: [] for arm in ("single", "self_revision", "beastmode")}
    for cell in manifest.get("final_matrix", []):
        key = (cell["task_id"], int(cell["repetition"]), cell["stage"])
        final_records[cell["arm"]].append(score_map.get(key))
    missing = []
    for arm, records in final_records.items():
        for cell, record in zip((cell for cell in manifest["final_matrix"] if cell["arm"] == arm), records):
            if record is None:
                missing.append({"task_id": cell["task_id"], "repetition": cell["repetition"], "arm": arm, "stage": cell["stage"]})
    if any(score.get("status") == "infrastructure_error" for score in scores):
        raise HarnessError("scorer infrastructure failures are present; resolve them before analysis")

    per_arm: dict[str, Any] = {}
    task_solved: dict[str, dict[str, list[float]]] = {arm: {task: [] for task in TASK_IDS} for arm in final_records}
    invoke_records = _invoke_records(run_dir)
    for arm, records in final_records.items():
        solved_values = [float(record.get("solved", False)) if record else 0.0 for record in records]
        fractions = [float(record.get("fraction_passed", 0.0)) if record else 0.0 for record in records]
        task_rows = []
        for task_id in TASK_IDS:
            reps = []
            for repetition in REPETITIONS:
                record = score_map.get((task_id, repetition, {"single": "single", "self_revision": "self_revision", "beastmode": "beast_revision"}[arm]))
                value = float(record.get("solved", False)) if record else 0.0
                reps.append(value)
                task_solved[arm][task_id].append(value)
            task_rows.append({"task_id": task_id, "repetition_values": reps, "mean_solved": sum(reps) / len(reps)})
        tokens: dict[str, int] = {}
        elapsed: list[float] = []
        for cell, record in zip((c for c in manifest["final_matrix"] if c["arm"] == arm), records):
            if record is None:
                continue
            invocation = invoke_records.get((cell["task_id"], int(cell["repetition"]), cell["stage"]))
            usage = (invocation or record.get("invocation") or {}).get("usage", {}) if isinstance(invocation or record.get("invocation"), dict) else {}
            if isinstance(usage, dict):
                for name in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"):
                    if isinstance(usage.get(name), int):
                        tokens[name] = tokens.get(name, 0) + usage[name]
            start = (invocation or record.get("invocation") or {}).get("started_at_utc") if isinstance(invocation or record.get("invocation"), dict) else None
            finish = (invocation or record.get("invocation") or {}).get("finished_at_utc") if isinstance(invocation or record.get("invocation"), dict) else None
            if isinstance(start, str) and isinstance(finish, str):
                try:
                    elapsed.append((_dt.datetime.fromisoformat(finish.replace("Z", "+00:00")) - _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds())
                except ValueError:
                    pass
        per_arm[arm] = {
            "fixed_cell_denominator": len(records),
            "solved_count": int(sum(solved_values)),
            "artifact_solved_count": sum(1 for record in records if record and record.get("artifact_solved", record.get("solved", False))),
            "solved_rate": sum(solved_values) / len(records) if records else None,
            "mean_case_pass_fraction_fixed_denominator": sum(fractions) / len(records) if records else None,
            "task_average_mean": sum(row["mean_solved"] for row in task_rows) / len(task_rows),
            "task_averages": task_rows,
            "missing_cells": sum(record is None for record in records),
            "tokens_observed": tokens,
            "elapsed_seconds_observed": elapsed,
        }

    contrasts: dict[str, Any] = {}
    for arm, control in (("self_revision", "single"), ("beastmode", "single"), ("beastmode", "self_revision")):
        diffs = [per_arm[arm]["task_averages"][index]["mean_solved"] - per_arm[control]["task_averages"][index]["mean_solved"] for index in range(len(TASK_IDS))]
        task_difference_map = dict(zip(TASK_IDS, diffs))
        contrasts[f"{arm}_minus_{control}"] = {
            "task_differences": task_difference_map,
            "bootstrap": _bootstrap_ci(diffs),
            "six_family_bootstrap": _bootstrap_ci(_family_differences(task_difference_map)),
        }

    initial = {(record.get("task_id"), int(record.get("repetition", 0))): record for record in scores if record.get("stage") == "beast_initial"}
    final = {(record.get("task_id"), int(record.get("repetition", 0))): record for record in scores if record.get("stage") == "beast_revision"}
    repair_regressions = []
    for key, initial_record in sorted(initial.items()):
        final_record = final.get(key)
        if final_record and initial_record.get("artifact_solved", initial_record.get("solved", False)) and not final_record.get("artifact_solved", final_record.get("solved", False)):
            repair_regressions.append({"task_id": key[0], "repetition": key[1]})

    missingness: dict[str, int] = {}
    for score in scores:
        status = score.get("candidate_error") or "observed"
        missingness[status] = missingness.get(status, 0) + 1
        for case in score.get("case_results", []):
            if not case.get("passed"):
                case_status = case.get("status", "failed")
                missingness[case_status] = missingness.get(case_status, 0) + 1
    analysis = {
        "schema_version": 1,
        "run_id": manifest.get("run_id"),
        "generated_at_utc": utc_now(),
        "fixed_planned_final_cells": len(manifest.get("final_matrix", [])),
        "observed_score_records": len(scores),
        "planned_calls": manifest.get("planned_calls", 96),
        "observed_invocations": len(invoke_records),
        "missing_invocations": max(0, int(manifest.get("planned_calls", 96)) - len(invoke_records)),
        "missing_cells": missing,
        "duplicate_score_records": duplicates,
        "call_metrics": _call_metrics(invoke_records),
        "missingness": missingness,
        "arms": per_arm,
        "paired_contrasts": contrasts,
        "repair_regressions": repair_regressions,
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": SEED, "cluster_unit": "task", "percentiles": [0.025, 0.975]},
        "limitations": [
            "Missing final cells are counted as unsolved in fixed denominators.",
            "Bootstrap intervals are exploratory with 12 task clusters.",
            "Dollar costs are omitted because authoritative billing units are unavailable.",
        ]
        + [contrast["bootstrap"]["warning"] for contrast in contrasts.values() if contrast["bootstrap"].get("warning")]
        + [contrast["six_family_bootstrap"]["warning"] for contrast in contrasts.values() if contrast["six_family_bootstrap"].get("warning")],
    }
    output_path = output_path or (run_dir / "analysis.json")
    write_json(output_path, analysis)
    return output_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="freeze fixtures and the seeded call schedule")
    prepare.add_argument("--run-id")
    prepare.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    prepare.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    prepare.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    prepare.add_argument("--plans", type=Path)
    prepare.add_argument("--prompts", type=Path)
    invoke = sub.add_parser("invoke", help="execute one explicit model call")
    invoke.add_argument("--run", required=True)
    invoke.add_argument("--task", required=True)
    invoke.add_argument("--rep", required=True, type=int)
    invoke.add_argument("--stage", required=True, choices=CALL_STAGES)
    invoke.add_argument("--prompt", required=True, type=Path)
    invoke.add_argument("--codex", default="codex")
    invoke.add_argument("--timeout", type=float, default=MODEL_TIMEOUT_SECONDS)
    score = sub.add_parser("score", help="score one candidate artifact")
    score.add_argument("--run", required=True)
    score.add_argument("--task", required=True)
    score.add_argument("--rep", required=True, type=int)
    score.add_argument("--stage", required=True, choices=CALL_STAGES)
    score.add_argument("--candidate", type=Path)
    score.add_argument("--wall-timeout", type=float, default=CASE_WALL_SECONDS)
    analyze = sub.add_parser("analyze", help="analyze retained score records")
    analyze.add_argument("--run", required=True)
    analyze.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            print(
                prepare_run(
                    args.run_id,
                    fixtures_dir=args.fixtures,
                    protocol_path=args.protocol,
                    runs_dir=args.runs_dir,
                    plans_dir=args.plans,
                    prompt_templates_dir=args.prompts,
                )
            )
        elif args.command == "invoke":
            guarded_run = resolve_run(args.run)
            guarded_manifest = verify_frozen_inputs(guarded_run)
            _require_schedule_predecessors_terminal(guarded_run, guarded_manifest, args.task, args.rep, args.stage)
            print(invoke_call(args.run, args.task, args.rep, args.stage, args.prompt, codex=args.codex, timeout=args.timeout))
        elif args.command == "score":
            guarded_run = resolve_run(args.run)
            guarded_manifest = verify_frozen_inputs(guarded_run)
            _seal_score_inputs(guarded_run, guarded_manifest)
            print(score_candidate(args.run, args.task, args.rep, args.stage, candidate_path=args.candidate, wall_timeout=args.wall_timeout))
        elif args.command == "analyze":
            print(analyze_run(args.run, output_path=args.output))
        return 0
    except (HarnessError, OSError, ValueError) as exc:
        print(f"harness error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
