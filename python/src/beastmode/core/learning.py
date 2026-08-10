"""Durable, redacted self-improvement records for Beastmode runs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .observability import redact_text, redact_value


MAX_LEARNING_LOG_BYTES = 8 * 1024 * 1024
MAX_LEARNING_ENTRY_BYTES = 64 * 1024
_LEARNING_MARKER_PREFIX = "<!-- beastmode-learning: "
_LEARNING_MARKER_SUFFIX = " -->"


def record_learning(state: Mapping[str, Any], *, repo: Path) -> dict[str, Any]:
    """Append one idempotent learning record and return its bounded report.

    A run can be replayed by LangGraph, so the event id is derived from the
    goal, run directory, result, and issue fingerprints.  Replaying the same
    state therefore does not duplicate the durable entry.  A later clean run
    for the same goal can explicitly evidence that earlier issues were
    addressed; it does not silently promote a prose note into a skill.
    """
    root = Path(repo).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("self-improvement repository must be an existing directory")
    log_path = _learning_path(root, state)
    previous = _read_records(log_path)
    issues = _collect_issues(state)
    _annotate_issue_history(issues, previous)
    result = _run_result(state, issues)
    goal_id = _one_line(state.get("goal_id") or state.get("goal") or "unknown-goal", 256)
    run_dir = _one_line(state.get("run_dir") or "", 512)
    addressed = _addressed_issues(
        previous,
        state,
        goal_id=goal_id,
        current_issue_ids={issue["id"] for issue in issues},
        result=result,
    )
    promotions = [
        {
            "issue_id": issue["id"],
            "action": "review recurring issue for promotion into the relevant skill or config",
        }
        for issue in issues
        if issue["status"] == "recurring"
    ]
    event_id = _event_id(goal_id, run_dir, result, issues, addressed)
    existing = next(
        (record for record in previous if record.get("event_id") == event_id),
        None,
    )
    if existing is not None:
        return _report(
            log_path,
            event_id=event_id,
            result=result,
            issues=issues,
            addressed=addressed,
            promotions=promotions,
            duplicate=True,
        )

    record = {
        "schema": "beastmode.learning.v1",
        "event_id": event_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "goal_id": goal_id,
        "run_dir": run_dir,
        "result": result,
        "issues": issues,
        "addressed": addressed,
        "promotions": promotions,
    }
    markdown = _render_markdown(record)
    _append_record(log_path, markdown, record)
    return _report(
        log_path,
        event_id=event_id,
        result=result,
        issues=issues,
        addressed=addressed,
        promotions=promotions,
        duplicate=False,
    )


def _report(
    log_path: Path,
    *,
    event_id: str,
    result: str,
    issues: list[dict[str, Any]],
    addressed: list[dict[str, Any]],
    promotions: list[dict[str, Any]],
    duplicate: bool,
) -> dict[str, Any]:
    return {
        "recorded": True,
        "duplicate": duplicate,
        "path": str(log_path),
        "event_id": event_id,
        "result": result,
        "issue_count": len(issues),
        "issues": issues,
        "addressed": addressed,
        "promotions": promotions,
        "next_actions": [issue["next_action"] for issue in issues],
    }


def _learning_path(root: Path, state: Mapping[str, Any]) -> Path:
    contract = state.get("acceptance_contract")
    contract = contract if isinstance(contract, Mapping) else {}
    raw = contract.get("self_improvement_log_path", ".learnings/BEASTMODE.md")
    if not isinstance(raw, str) or not raw or len(raw) > 256:
        raise ValueError("self-improvement log path must be a bounded relative string")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("self-improvement log path must stay inside the repository")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("self-improvement log path must stay inside the repository")
    return resolved


def _read_records(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        if path.stat().st_size > MAX_LEARNING_LOG_BYTES:
            raise ValueError("self-improvement log exceeds its size bound")
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith(_LEARNING_MARKER_PREFIX) or not line.endswith(_LEARNING_MARKER_SUFFIX):
            continue
        payload = line[len(_LEARNING_MARKER_PREFIX) : -len(_LEARNING_MARKER_SUFFIX)]
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping) and value.get("schema") == "beastmode.learning.v1":
            records.append(dict(value))
    return records


def _append_record(path: Path, markdown: str, record: Mapping[str, Any]) -> None:
    encoded = markdown.encode("utf-8")
    if len(encoded) > MAX_LEARNING_ENTRY_BYTES:
        raise ValueError("self-improvement entry exceeds its size bound")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        # A concurrent creator can win the O_CREAT race; retry without
        # changing the existing file's permissions.
        fd = os.open(path, flags, 0o600)
    try:
        if os.fstat(fd).st_size:
            with path.open("rb") as existing:
                existing.seek(-1, os.SEEK_END)
                if existing.read(1) != b"\n":
                    encoded = b"\n" + encoded
        written = os.write(fd, encoded)
        if written != len(encoded):
            raise OSError("short write while recording self-improvement entry")
    finally:
        os.close(fd)


def _collect_issues(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    if state.get("preflight_ok") is False:
        issues.append(
            _issue(
                "preflight",
                "preflight did not pass",
                _compact(state.get("preflight_report")),
                "Fix the preflight report, then rerun the same goal.",
            )
        )

    challenge = state.get("challenge_report")
    if isinstance(challenge, Mapping) and challenge.get("passed") is False:
        issues.append(
            _issue(
                "challenge",
                "design challenge did not pass",
                _compact(challenge),
                "Resolve the challenge findings and rerun the design phase.",
            )
        )

    validation = state.get("validation_report")
    if isinstance(validation, Mapping):
        failures = validation.get("failures")
        if isinstance(failures, (list, tuple)):
            for failure in failures[:16]:
                issues.append(
                    _issue(
                        "validation",
                        "mechanical validation failed",
                        _one_line(failure, 512),
                        "Fix the validation failure and rerun the verification commands.",
                    )
                )
        elif validation.get("passed") is False:
            issues.append(
                _issue(
                    "validation",
                    "mechanical validation failed without a structured failure list",
                    _compact(validation),
                    "Repair the validator output, then rerun mechanical validation.",
                )
            )

    provenance = state.get("provenance_verdict")
    if provenance and provenance != "ok":
        issues.append(
            _issue(
                "provenance",
                f"child provenance is {_one_line(provenance, 128)}",
                _compact(state.get("provenance_messages")),
                "Rerun under the pinned model and repair missing or invalid attestation evidence.",
            )
        )

    task_results = state.get("task_results")
    if isinstance(task_results, (list, tuple)):
        for task in task_results[:32]:
            if not isinstance(task, Mapping) or task.get("execution_status") == "ok":
                continue
            task_id = _one_line(task.get("id") or "unknown-task", 128)
            status = _one_line(task.get("execution_status") or "unknown", 128)
            issues.append(
                _issue(
                    "execution",
                    f"task {task_id} reported {status}",
                    _compact(
                        {
                            "returncode": task.get("executor_returncode"),
                            "timed_out": task.get("executor_timed_out"),
                            "resource_exhausted": task.get("executor_resource_exhausted"),
                        }
                    ),
                    "Inspect the bounded executor evidence, fix the task failure, and rerun it.",
                )
            )

    review = state.get("review_report")
    if isinstance(review, Mapping) and review.get("approved") is not True:
        issues.append(
            _issue(
                "review",
                "judgment review did not approve the result",
                _compact(review),
                "Address the review findings and resubmit the result for review.",
            )
        )

    if state.get("status") == "blocked" and not issues:
        issues.append(
            _issue(
                "blocked",
                "run was blocked without a structured gate issue",
                _compact({"phase": state.get("phase"), "status": state.get("status")}),
                "Inspect the checkpoint and add a structured gate reason before rerunning.",
            )
        )
    return issues


def _issue(kind: str, summary: str, evidence: Any, next_action: str) -> dict[str, Any]:
    safe = {
        "kind": _one_line(kind, 64),
        "summary": _one_line(summary, 512),
        "evidence": _one_line(evidence, 768),
        "next_action": _one_line(next_action, 512),
    }
    fingerprint = hashlib.sha256(
        f"{safe['kind']}\0{safe['summary']}".encode("utf-8")
    ).hexdigest()[:16]
    return {"id": f"BM-ISSUE-{fingerprint}", **safe, "status": "open", "occurrences": 1}


def _annotate_issue_history(
    issues: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> None:
    counts: dict[str, int] = {}
    for record in previous:
        for issue in record.get("issues") or ():
            if not isinstance(issue, Mapping):
                continue
            issue_id = _one_line(issue.get("id"), 128)
            if issue_id:
                counts[issue_id] = counts.get(issue_id, 0) + 1
    for issue in issues:
        occurrences = counts.get(issue["id"], 0) + 1
        issue["occurrences"] = occurrences
        issue["status"] = "recurring" if occurrences > 1 else "open"


def _addressed_issues(
    previous: list[dict[str, Any]],
    state: Mapping[str, Any],
    *,
    goal_id: str,
    current_issue_ids: set[str],
    result: str,
) -> list[dict[str, Any]]:
    explicit = state.get("learning_resolutions")
    addressed: list[dict[str, Any]] = []
    if isinstance(explicit, Mapping):
        for issue_id, reason in list(explicit.items())[:32]:
            addressed.append(
                {
                    "id": _one_line(issue_id, 128),
                    "status": "addressed",
                    "reason": _one_line(reason, 512),
                }
            )
    if result != "pass":
        return addressed
    prior_ids: set[str] = set()
    for record in previous:
        if _one_line(record.get("goal_id"), 256) != goal_id:
            continue
        for issue in record.get("issues") or ():
            if isinstance(issue, Mapping) and issue.get("status") in {"open", "recurring"}:
                issue_id = _one_line(issue.get("id"), 128)
                if issue_id and issue_id not in current_issue_ids:
                    prior_ids.add(issue_id)
    existing_ids = {item["id"] for item in addressed}
    for issue_id in sorted(prior_ids - existing_ids):
        addressed.append(
            {
                "id": issue_id,
                "status": "addressed",
                "reason": "same goal completed without the previously recorded issue",
            }
        )
    return addressed


def _event_id(
    goal_id: str,
    run_dir: str,
    result: str,
    issues: list[dict[str, Any]],
    addressed: list[dict[str, Any]],
) -> str:
    payload = {
        "goal_id": goal_id,
        "run_dir": run_dir,
        "result": result,
        "issues": [issue["id"] for issue in issues],
        "addressed": [issue["id"] for issue in addressed],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    return f"BM-RUN-{digest}"


def _run_result(state: Mapping[str, Any], issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "pass"
    return "blocked" if state.get("status") == "blocked" or state.get("phase") == "blocked" else "partial"


def _render_markdown(record: Mapping[str, Any]) -> str:
    goal = _one_line(record.get("goal_id"), 256)
    lines = [
        f"## {record['event_id']} — {goal}",
        f"- Recorded: {record['recorded_at']}",
        f"- Result: {record['result']}",
        f"- Issues recorded: {len(record['issues'])}",
        f"- Issues addressed: {len(record['addressed'])}",
        f"- Promotions queued: {len(record['promotions'])}",
    ]
    for issue in record["issues"]:
        lines.extend(
            [
                f"- [{issue['status'].upper()}] `{issue['id']}` {issue['summary']}",
                f"  - Evidence: {issue['evidence']}",
                f"  - Next action: {issue['next_action']}",
            ]
        )
    for item in record["addressed"]:
        lines.append(f"- [ADDRESSED] `{item['id']}` {item['reason']}")
    if record["promotions"]:
        lines.append("- Promotion review: recurring issues are queued for a separate approved maintenance task.")
    marker = _LEARNING_MARKER_PREFIX + json.dumps(record, sort_keys=True, separators=(",", ":")) + _LEARNING_MARKER_SUFFIX
    return "\n".join(lines + [marker, ""]) + "\n"


def _compact(value: Any) -> str:
    return _one_line(redact_value(value, limit=768), 768)


def _one_line(value: Any, limit: int) -> str:
    return " ".join(redact_text(value, limit=limit).split())
