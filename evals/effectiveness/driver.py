"""Serial, resumable driver for the frozen effectiveness call schedule."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
try:
    import harness  # type: ignore
except ImportError:
    harness = None  # type: ignore
NO_INITIAL = "No initial implementation was returned; implement the public specification"
TERMINAL = frozenset({"completed", "failed", "timeout", "launch_error"})
class DriverError(RuntimeError): pass
def _harness() -> Any:
    if harness is None:
        raise DriverError("harness is unavailable; integrate the sibling harness before advancing")
    return harness
def _run_dir(value: str | Path) -> Path:
    path = Path(value)
    if path.is_dir():
        return path.resolve()
    h = _harness()
    try:
        resolved = h.resolve_run(value)
    except Exception as exc:
        raise DriverError(f"cannot resolve run: {exc}") from exc
    return Path(resolved).resolve()
def _root() -> Path:
    return Path(getattr(_harness(), "ROOT", Path(__file__).resolve().parent)).resolve()
def _path_from_record(root: Path, item: Mapping[str, Any]) -> Path:
    raw = item.get("path")
    if not isinstance(raw, str) or not raw:
        raise DriverError("frozen inventory contains an invalid path")
    return (root / raw).resolve()
def _fixture_path(manifest: Mapping[str, Any], task_id: str, name: str) -> Path:
    root = _root()
    fixture_root = manifest.get("fixtures_root")
    if not isinstance(fixture_root, str):
        raise DriverError("manifest has no fixtures root")
    path = (root / fixture_root / task_id / name).resolve()
    if not path.is_file():
        raise DriverError(f"public fixture is missing: {path}")
    return path
def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DriverError(f"cannot read {label}: {path}") from exc
def _json_text(path: Path) -> str:
    try:
        value = json.loads(_read(path, "public examples"))
    except json.JSONDecodeError as exc:
        raise DriverError(f"invalid public examples: {path}") from exc
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
def _exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise DriverError(f"refusing to overwrite existing driver file: {path}") from exc
def _record_path(run_dir: Path, entry: Mapping[str, Any]) -> Path:
    return run_dir / "invocations" / f"{entry['task_id']}_rep{entry['repetition']}_{entry['stage']}" / "record.json"
def _read_record(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DriverError(f"invocation record is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DriverError(f"invocation record is not an object: {path}")
    return value
def _pid_alive(pid: Any) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise DriverError("running invocation has no valid PID; explicit recovery is required")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True
def _check_terminal(record: Mapping[str, Any], entry: Mapping[str, Any], path: Path) -> str:
    status = record.get("status")
    if status != "running" and status not in TERMINAL:
        raise DriverError(f"record has non-terminal status {status!r}: {path}")
    for key in ("task_id", "repetition", "stage"):
        if key in record and record[key] != entry[key]:
            raise DriverError(f"record identity mismatch for {path}")
    if "schedule_entry" in record and record["schedule_entry"] != dict(entry):
        raise DriverError(f"record schedule mismatch for {path}")
    if record.get("final_output_path") not in (None, "final_output.txt"):
        raise DriverError(f"record output path mismatch for {path}")
    if record.get("final_output_path") == "final_output.txt" and not (path.parent / "final_output.txt").is_file():
        raise DriverError(f"record output is missing: {path.parent / 'final_output.txt'}")
    if status == "running":
        return status
    candidate_name = record.get("candidate_path")
    if candidate_name:
        if not isinstance(candidate_name, str) or Path(candidate_name).is_absolute() or ".." in Path(candidate_name).parts:
            raise DriverError(f"record candidate path is unsafe: {path}")
        candidate = path.parent / candidate_name
        if not candidate.is_file():
            raise DriverError(f"record candidate is missing: {candidate}")
        digest = record.get("candidate_sha256")
        if isinstance(digest, str) and _sha256(candidate) != digest:
            raise DriverError(f"record candidate hash mismatch: {candidate}")
    return str(status)
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
def _existing(run_dir: Path, entry: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None, Path]:
    record_path = _record_path(run_dir, entry)
    call_dir = record_path.parent
    if not record_path.exists():
        if call_dir.exists():
            raise DriverError(f"invocation directory has no record; explicit recovery required: {call_dir}")
        return "missing", None, record_path
    record = _read_record(record_path)
    status = _check_terminal(record, entry, record_path)
    if status == "running":
        if _pid_alive(record.get("pid")):
            return "running", record, record_path
        raise DriverError(f"interrupted invocation handle is stale; explicit recovery required: {record_path}")
    return "terminal", record, record_path
def _template_path(manifest: Mapping[str, Any], stage: str) -> Path:
    root = _root()
    for item in manifest.get("prompt_templates", []):
        if isinstance(item, dict) and str(item.get("path", "")).endswith(f"prompts/{stage}.txt"):
            return _path_from_record(root, item)
    raise DriverError(f"frozen prompt template is missing: {stage}")
def _plan_path(manifest: Mapping[str, Any], task_id: str) -> Path:
    root = _root()
    for item in manifest.get("director_plans", []):
        if isinstance(item, dict) and str(item.get("path", "")).endswith(f"plans/{task_id}.md"):
            return _path_from_record(root, item)
    raise DriverError(f"frozen director plan is missing: {task_id}")
def _initial_text(run_dir: Path, task_id: str, repetition: int, predecessor: str) -> str:
    path = run_dir / "invocations" / f"{task_id}_rep{repetition}_{predecessor}" / "final_output.txt"
    if not path.is_file():
        return NO_INITIAL
    value = _read(path, "initial implementation")
    return value if value.strip() else NO_INITIAL
def _review_request(run_dir: Path, manifest: Mapping[str, Any], entry: Mapping[str, Any]) -> None:
    task_id, repetition = entry["task_id"], entry["repetition"]
    spec = _fixture_path(manifest, task_id, "public.md")
    plan = _plan_path(manifest, task_id)
    initial = run_dir / "invocations" / f"{task_id}_rep{repetition}_beast_initial" / "final_output.txt"
    request = {
        "task_id": task_id,
        "repetition": repetition,
        "public_spec_path": str(spec),
        "plan_path": str(plan),
        "beast_initial_path": str(initial),
    }
    path = run_dir / "reviews" / f"{task_id}_rep{repetition}.request.json"
    if path.exists():
        if _read_record(path) != request:
            raise DriverError(f"review request was modified: {path}")
    else:
        _exclusive(path, json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print("review_required " + json.dumps(request, ensure_ascii=False, sort_keys=True))
def _render_prompt(run_dir: Path, manifest: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
    task_id, repetition, stage = entry["task_id"], entry["repetition"], entry["stage"]
    spec_path = _fixture_path(manifest, task_id, "public.md")
    examples_path = _fixture_path(manifest, task_id, "public_examples.json")
    values = {
        "public_spec": _read(spec_path, "public specification"),
        "public_examples": _json_text(examples_path),
    }
    if stage in {"beast_initial", "beast_revision"}:
        values["director_plan"] = _read(_plan_path(manifest, task_id), "director plan")
    if stage == "self_revision":
        values["initial_code"] = _initial_text(run_dir, task_id, repetition, "single")
    elif stage == "beast_revision":
        values["initial_code"] = _initial_text(run_dir, task_id, repetition, "beast_initial")
        values["director_review"] = _read(
            run_dir / "reviews" / f"{task_id}_rep{repetition}.md", "director review"
        )
    fixed = run_dir / str(manifest["fixed_prompt_template"]["path"])
    common = _read(fixed, "fixed common prompt")
    stage_template = _read(_template_path(manifest, stage), f"{stage} prompt template")
    rendered = stage_template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    if "{{" in rendered or "}}" in rendered:
        raise DriverError(f"unrendered prompt placeholder in {stage}")
    return common.rstrip() + "\n\n" + rendered.strip() + "\n"
def advance(run: str | Path) -> int:
    """Advance the frozen schedule until completion or a review barrier."""
    h = _harness()
    run_dir = _run_dir(run)
    try:
        manifest = h.verify_frozen_inputs(run_dir)
    except Exception as exc:
        raise DriverError(f"frozen-input verification failed: {exc}") from exc
    schedule = manifest.get("schedule")
    if not isinstance(schedule, list):
        raise DriverError("frozen manifest has no schedule")
    for entry in schedule:
        if not isinstance(entry, dict) or not all(k in entry for k in ("task_id", "repetition", "stage")):
            raise DriverError("invalid schedule entry")
        state, record, record_path = _existing(run_dir, entry)
        if state == "terminal":
            print(f"task={entry['task_id']} rep={entry['repetition']} stage={entry['stage']} status={record['status']} record={record_path}")
            continue
        if state == "running":
            print(f"task={entry['task_id']} rep={entry['repetition']} stage={entry['stage']} status=running record={record_path}")
            return 0
        if entry["stage"] == "beast_revision":
            review_path = run_dir / "reviews" / f"{entry['task_id']}_rep{entry['repetition']}.md"
            if not review_path.is_file():
                _review_request(run_dir, manifest, entry)
                return 0
        prompt = _render_prompt(run_dir, manifest, entry)
        prompt_path = run_dir / "driver_prompts" / (
            f"{entry['task_id']}_rep{entry['repetition']}_{entry['stage']}.txt"
        )
        _exclusive(prompt_path, prompt)
        try:
            result = h.invoke_call(
                run_dir, entry["task_id"], entry["repetition"], entry["stage"], prompt_path
            )
        except Exception as exc:
            raise DriverError(f"invoke failed for {entry['task_id']} {entry['stage']}: {exc}") from exc
        returned = Path(result) if result else record_path
        if not returned.is_file():
            raise DriverError(f"invoke returned no record: {returned}")
        finished = _read_record(returned)
        status = finished.get("status", "unknown")
        print(f"task={entry['task_id']} rep={entry['repetition']} stage={entry['stage']} status={status} record={returned}")
    return 0
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    advance_parser = sub.add_parser("advance")
    advance_parser.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    try:
        return advance(args.run)
    except (DriverError, OSError, ValueError) as exc:
        print(f"driver error: {exc}", file=sys.stderr)
        return 2
if __name__ == "__main__": raise SystemExit(main())
