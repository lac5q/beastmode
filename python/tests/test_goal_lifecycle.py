"""Unit tests for the native goal lifecycle (GL0–GL5) and its LangGraph bridge.

The end-to-end pilot lives in tests/test-goal-lifecycle.sh; these tests pin
the durable-state primitives and the exit-code contract without a harness.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lifecycle():
    return _load("beastmode_goal_lifecycle", ROOT / "scripts" / "lib" / "goal_lifecycle.py")


@pytest.fixture(scope="module")
def runner():
    return _load("beastmode_langgraph_runner", ROOT / "scripts" / "langgraph-runner")


@pytest.fixture
def store(lifecycle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return lifecycle.GoalStore()


def _goal(lifecycle, goal_id: str = "g-unit", **overrides):
    goal = {
        "contract_version": "1.0",
        "goal_id": goal_id,
        "goal": "unit goal",
        "state": "queued",
        "outcome": None,
        "harness": "pi",
        "autonomy": "medium",
        "worktree": "/nonexistent",
        "attempts": [],
        "current_attempt": None,
        "decisions": [],
        "pending_decision": None,
        "completion": None,
        "budget": {"max_attempts": 2, "used": {"tokens": 0, "seconds": 0}},
        "created_by": "tester",
        "contract_digest": lifecycle.contract_digest(
            "unit goal", harness="pi", autonomy="medium", seats={}
        ),
    }
    goal.update(overrides)
    return goal


# ---- GL0: contract --------------------------------------------------------


def test_contract_matches_module_constants(lifecycle) -> None:
    contract = json.loads((ROOT / "schema" / "goal-lifecycle.json").read_text("utf-8"))
    assert contract["version"] == "1.0"
    assert set(contract["states"]) == set(lifecycle.STATES)
    assert {k: tuple(v) for k, v in contract["transitions"].items()} == lifecycle.TRANSITIONS
    for terminal in contract["terminal_states"]:
        assert contract["transitions"][terminal] == []
    for harness, caps in contract["capabilities"].items():
        expected = "checkpoint" if harness == "langgraph" else "prompt_continuation"
        assert caps["resume"] == expected, harness
        assert caps["pause_running"] is False
        assert caps["remote"] is False
    codes = contract["exit_codes"]
    assert set(codes) == {str(i) for i in range(8)}
    assert "approval" in codes[str(lifecycle.EXIT_AWAITING)]
    assert "cancelled" in codes[str(lifecycle.EXIT_CANCELLED)]
    assert "unsupported" in codes[str(lifecycle.EXIT_UNSUPPORTED)]
    assert "conflict" in codes[str(lifecycle.EXIT_CONFLICT)]


def test_contract_digest_is_stable_and_seat_sensitive(lifecycle) -> None:
    a = lifecycle.contract_digest("x", harness="pi", autonomy="medium", seats={"economy": "m1"})
    b = lifecycle.contract_digest("x", harness="pi", autonomy="medium", seats={"economy": "m1"})
    c = lifecycle.contract_digest("x", harness="pi", autonomy="medium", seats={"economy": "m2"})
    assert a == b != c
    assert len(a) == 64


# ---- GL1: durable identity, atomic records, append-only events -----------


def test_store_is_owner_only_and_refuses_duplicate_goal(lifecycle, store) -> None:
    goal = store.create(_goal(lifecycle))
    assert oct(store.goals.stat().st_mode & 0o777) == "0o700"
    assert oct(store.goal_dir("g-unit").stat().st_mode & 0o777) == "0o700"
    assert store.load("g-unit")["goal_id"] == goal["goal_id"]
    with pytest.raises(lifecycle.LifecycleError) as excinfo:
        store.create(_goal(lifecycle))
    assert excinfo.value.exit_code == lifecycle.EXIT_CONFLICT


def test_events_are_append_only_and_sequenced(lifecycle, store) -> None:
    goal = store.create(_goal(lifecycle))
    store.transition(goal, "running", reason="start", attempt_id="a1")
    store.record_event(goal, "harness_started", attempt_id="a1", data={"pid": 1})
    store.transition(goal, "failed", reason="boom", outcome="harness_failed", attempt_id="a1")
    events = store.events("g-unit")
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert [e["type"] for e in events] == ["created", "transition", "harness_started", "transition"]
    assert events[-1]["from"] == "running" and events[-1]["to"] == "failed"
    assert store.load("g-unit")["last_event_seq"] == 4
    raw = store.events_path("g-unit").read_bytes().splitlines()
    assert len(raw) == 4


def test_illegal_transitions_fail_closed(lifecycle, store) -> None:
    goal = store.create(_goal(lifecycle))
    with pytest.raises(lifecycle.LifecycleError) as excinfo:
        store.transition(goal, "succeeded")
    assert excinfo.value.exit_code == lifecycle.EXIT_CONFLICT
    assert store.load("g-unit")["state"] == "queued"
    store.transition(goal, "running")
    store.transition(goal, "succeeded", outcome="succeeded")
    for target in lifecycle.STATES:
        with pytest.raises(lifecycle.LifecycleError):
            store.transition(goal, target)
    with pytest.raises(lifecycle.LifecycleError):
        store.transition(goal, "not-a-state")


def test_goal_ids_are_validated(lifecycle) -> None:
    assert lifecycle.validate_goal_id("g-ok_1") == "g-ok_1"
    for bad in ("../x", "a b", "", "x" * 100, "/abs"):
        with pytest.raises(lifecycle.LifecycleError):
            lifecycle.validate_goal_id(bad)
    assert lifecycle.validate_goal_id(lifecycle.new_goal_id())


def test_read_json_refuses_symlinked_record(lifecycle, tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.read_json(link)
    assert lifecycle.read_control_json(link) is None


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=path, check=True)
    return path


def test_run_refuses_non_git_worktree(lifecycle, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    sink: list[str] = []
    rc = lifecycle.main(["run", "queue me", "--goal-id", "g-q", "--queue-only"], out=sink.append)
    assert rc == lifecycle.EXIT_USAGE
    assert not (tmp_path / "state" / "beastmode" / "goals" / "g-q").exists()


def test_queue_only_run_and_inspect_round_trip(lifecycle, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(_git_repo(tmp_path / "repo"))
    lines: list[str] = []
    rc = lifecycle.main(
        ["run", "queue me", "--goal-id", "g-q", "--queue-only", "--json"], out=lines.append
    )
    assert rc == 0
    record = json.loads(lines[-1])
    assert record["goal_id"] == "g-q" and record["state"] == "queued"
    assert record["attempts"] == [] and record["completion"] is None
    assert record["base_revision"]["dirty"] is False and len(record["base_revision"]["head"]) == 40
    assert record["capabilities"]["resume"] == "prompt_continuation"
    lines.clear()
    assert lifecycle.main(["inspect", "g-q", "--json"], out=lines.append) == 0
    inspected = json.loads(lines[-1])
    assert inspected["events"][0]["type"] == "created"
    assert inspected["liveness"]["alive"] is None and inspected["liveness"]["lock_holder"] is None
    lines.clear()
    assert lifecycle.main(["runs", "--json"], out=lines.append) == 0
    assert [g["goal_id"] for g in json.loads(lines[-1])] == ["g-q"]


def test_usage_errors_exit_two(lifecycle, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    sink: list[str] = []
    assert lifecycle.main(["no-such-verb"], out=sink.append) == lifecycle.EXIT_USAGE
    assert lifecycle.main(["inspect", "missing"], out=sink.append) == lifecycle.EXIT_USAGE
    assert lifecycle.main(["approve"], out=sink.append) == lifecycle.EXIT_USAGE


# ---- GL2/GL3: approval binding and budgets -------------------------------


def test_decision_binding_rejects_changed_attempt_or_digest(lifecycle, store) -> None:
    goal = store.create(_goal(lifecycle, current_attempt="a1"))
    decision = {
        "id": "d1",
        "attempt_id": "a1",
        "contract_digest": goal["contract_digest"],
        "revision": {"head": None},
    }
    lifecycle._check_decision_binding(store, goal, decision)
    goal["current_attempt"] = "a2"
    with pytest.raises(lifecycle.LifecycleError) as excinfo:
        lifecycle._check_decision_binding(store, goal, decision)
    assert excinfo.value.exit_code == lifecycle.EXIT_CONFLICT
    assert "attempt changed" in str(excinfo.value)
    assert store.events("g-unit")[-1]["type"] == "approval_stale"
    goal["current_attempt"] = "a1"
    goal["contract_digest"] = "0" * 64
    with pytest.raises(lifecycle.LifecycleError, match="contract digest changed"):
        lifecycle._check_decision_binding(store, goal, decision)


def test_decision_binding_rejects_moved_revision(lifecycle, store) -> None:
    goal = store.create(_goal(lifecycle, current_attempt="a1"))
    decision = {
        "id": "d1",
        "attempt_id": "a1",
        "contract_digest": goal["contract_digest"],
        "revision": {"head": "a" * 40},
    }
    with pytest.raises(lifecycle.LifecycleError, match="worktree moved"):
        lifecycle._check_decision_binding(store, goal, decision)


def test_budgets_fail_closed(lifecycle) -> None:
    goal = _goal(lifecycle, attempts=["a1", "a2"])
    with pytest.raises(lifecycle.LifecycleError, match="attempt budget exhausted"):
        lifecycle._check_budget(goal)
    goal = _goal(lifecycle, attempts=["a1"], budget={"max_attempts": 3, "max_tokens": 10, "used": {"tokens": 10}})
    with pytest.raises(lifecycle.LifecycleError, match="token budget"):
        lifecycle._check_budget(goal)
    goal = _goal(lifecycle, attempts=["a1"], budget={"max_attempts": 3, "max_seconds": 5, "used": {"seconds": 6.0}})
    with pytest.raises(lifecycle.LifecycleError, match="time budget"):
        lifecycle._check_budget(goal)
    lifecycle._check_budget(_goal(lifecycle, attempts=["a1"]))


def test_capabilities_and_unsupported_remote(lifecycle, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(_git_repo(tmp_path / "repo"))
    assert lifecycle._capability("langgraph", "resume") == "checkpoint"
    assert lifecycle._capability("claude", "resume") == "prompt_continuation"
    assert lifecycle._capability("pi", "pause_running") is False
    sink: list[str] = []
    rc = lifecycle.main(["run", "remote goal", "--goal-id", "g-remote", "--on", "remote", "--queue-only"], out=sink.append)
    assert rc == lifecycle.EXIT_UNSUPPORTED


# ---- GL5: scheduling ------------------------------------------------------


def test_cron_interval_rounding(lifecycle) -> None:
    assert lifecycle._cron_interval(60) == "*/1 * * * *"
    assert lifecycle._cron_interval(900) == "*/15 * * * *"
    assert lifecycle._cron_interval(3600) == "0 */1 * * *"
    assert lifecycle._cron_interval(6 * 3600) == "0 */6 * * *"
    assert lifecycle._cron_interval(86400) == "0 0 */1 * *"
    assert lifecycle._cron_interval(90 * 86400) == "0 0 */28 * *"


def test_recurring_schedule_spawns_fresh_goal_per_occurrence(lifecycle, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(_git_repo(tmp_path / "repo"))
    lines: list[str] = []
    assert lifecycle.main(["run", "nightly", "--goal-id", "g-tpl", "--queue-only"], out=lines.append) == 0
    lines.clear()
    assert lifecycle.main(["schedule", "g-tpl", "--every", "86400", "--export", "cron"], out=lines.append) == 0
    assert lines[0] == "CRON_TZ=UTC"
    assert lines[1].startswith("0 0 */1 * * XDG_STATE_HOME=")
    assert "bm-goal run --from-template g-tpl --occurrence" in lines[1]
    assert "resume" not in lines[1]
    lines.clear()
    assert lifecycle.main(["schedule", "g-tpl", "--every", "86400", "--export", "json"], out=lines.append) == 0
    schedule = json.loads("\n".join(lines))
    assert schedule["mode"] == "recurring_template" and schedule["timezone"] == "UTC"
    assert schedule["overlap_policy"].startswith("reject") and schedule["duplicate_policy"].startswith("reject")
    lines.clear()
    args = ["run", "--from-template", "g-tpl", "--occurrence", "20300101T0000", "--queue-only", "--json"]
    assert lifecycle.main(args, out=lines.append) == 0
    occurrence = json.loads(lines[-1])
    assert occurrence["goal_id"] == "g-tpl-20300101T0000"
    assert occurrence["template"] == "g-tpl" and occurrence["goal"] == "nightly"
    assert occurrence["budget"]["used"]["attempts"] == 0
    assert lifecycle.main(args, out=lines.append) == lifecycle.EXIT_CONFLICT
    assert lifecycle.main(["run", "--from-template", "g-tpl", "--queue-only"], out=lines.append) == lifecycle.EXIT_USAGE
    assert lifecycle.main(
        ["run", "extra text", "--from-template", "g-tpl", "--occurrence", "x", "--queue-only"], out=lines.append
    ) == lifecycle.EXIT_USAGE
    lines.clear()
    assert lifecycle.main(["inspect", "g-tpl", "--json"], out=lines.append) == 0
    assert "occurrence_created" in [e["type"] for e in json.loads(lines[-1])["events"]]


def test_one_shot_schedule_is_utc_and_launchd_local(lifecycle, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.chdir(_git_repo(tmp_path / "repo"))
    lines: list[str] = []
    assert lifecycle.main(["run", "once", "--goal-id", "g-once", "--queue-only"], out=lines.append) == 0
    lines.clear()
    assert lifecycle.main(
        ["schedule", "g-once", "--at", "2030-01-02T03:04:00+02:00", "--export", "launchd"], out=lines.append
    ) == 0
    plist = json.loads("\n".join(lines))
    assert plist["ProgramArguments"][1:] == ["resume", "g-once"]
    assert plist["StartCalendarInterval"] == {"Month": 1, "Day": 2, "Hour": 1, "Minute": 4}
    assert "host-local" in plist["Comment"]


# ---- GL5: notifications ---------------------------------------------------


def _attempt_for_notify(lifecycle, store, goal_id: str, script: Path, body: str):
    script.write_text("#!/usr/bin/env bash\n" + body + "\n")
    script.chmod(0o700)
    goal = _goal(lifecycle, goal_id, notify={"command": str(script)}, state="succeeded", reason="accepted")
    store.create(goal)
    return goal, {"attempt_id": "a1"}


def test_notification_is_delivered_once_and_cannot_approve(lifecycle, store, tmp_path: Path) -> None:
    sink = tmp_path / "sink.jsonl"
    goal, attempt = _attempt_for_notify(
        lifecycle, store, "g-n1", tmp_path / "notify-ok", f"cat >> {sink}; echo >> {sink}"
    )
    lifecycle._notify(store, goal, attempt, "succeeded")
    lifecycle._notify(store, goal, attempt, "succeeded")
    payloads = [json.loads(line) for line in sink.read_text().splitlines() if line.strip()]
    assert len(payloads) == 1
    assert payloads[0]["notification_id"] == "g-n1:a1:succeeded"
    assert payloads[0]["state"] == "succeeded" and payloads[0]["outcome"] == "succeeded"
    assert goal["notifications"] == ["g-n1:a1:succeeded"]
    events = [e["type"] for e in store.events(goal["goal_id"])]
    assert events.count("notified") == 1
    assert store.load("g-n1")["state"] == "succeeded" and store.load("g-n1")["decisions"] == []


def test_notification_failure_is_recorded_and_bounded(lifecycle, store, tmp_path: Path) -> None:
    counter = tmp_path / "calls"
    goal, attempt = _attempt_for_notify(
        lifecycle, store, "g-n2", tmp_path / "notify-fail", f"echo x >> {counter}; exit 1"
    )
    lifecycle._notify(store, goal, attempt, "failed")
    assert counter.read_text().count("x") == lifecycle.NOTIFY_RETRIES
    failed = [e for e in store.events("g-n2") if e["type"] == "notification_failed"]
    assert len(failed) == 1 and failed[0]["data"]["retries"] == lifecycle.NOTIFY_RETRIES
    assert "notifications" not in goal or goal["notifications"] == []


def test_notification_without_command_is_noop(lifecycle, store) -> None:
    goal = _goal(lifecycle, "g-n3")
    store.create(goal)
    lifecycle._notify(store, goal, {"attempt_id": "a1"}, "succeeded")
    assert [e["type"] for e in store.events("g-n3")] == ["created"]


# ---- GL5: learning harvest (review-only) -----------------------------------


def test_harvest_proposes_but_never_applies(lifecycle, store, tmp_path: Path) -> None:
    store.create(_goal(lifecycle, "g-h1", state="failed", outcome="budget_exhausted", harness="pi"))
    store.create(_goal(lifecycle, "g-h2", state="blocked", outcome="review_missing", harness="codex"))
    store.create(_goal(lifecycle, "g-h3", state="running", outcome=None))
    lines: list[str] = []
    assert lifecycle.main(["harvest", "--json"], out=lines.append) == 0
    report = json.loads("\n".join(lines))
    assert report["goals_examined"] == 2 and report["applies_changes"] is False
    assert report["outcomes"] == {"budget_exhausted": 1, "review_missing": 1}
    targets = {p["target"] for p in report["proposals"]}
    assert targets == {"budget", "watcher prompt"}
    lines.clear()
    target = tmp_path / "proposal.md"
    assert lifecycle.main(["harvest", "--out", str(target)], out=lines.append) == 0
    body = target.read_text()
    assert "review before applying" in body and "watcher prompt" in body and "[config] budget" in body
    lines.clear()
    assert lifecycle.main(["harvest", "--since", "2999-01-01T00:00:00Z", "--json"], out=lines.append) == 0
    assert json.loads("\n".join(lines))["goals_examined"] == 0
    assert lifecycle.main(["harvest", "--since", "yesterday"], out=lines.append) == lifecycle.EXIT_USAGE
    assert store.load("g-h1")["state"] == "failed" and store.load("g-h2")["state"] == "blocked"
    assert [e["type"] for e in store.events("g-h1")] == ["created"]


# ---- LangGraph bridge: lifecycle summary + exit codes --------------------


def _graph_result(**overrides):
    result = {
        "status": "ready_to_merge",
        "phase": "review",
        "preflight_ok": True,
        "validation_report": {"passed": True},
        "provenance_verdict": "ok",
        "provenance_messages": [],
        "task_results": [{"id": "goal", "status": "completed"}],
        "review_report": {"approved": True},
        "merge_decision": "approved",
    }
    result.update(overrides)
    return result


def test_standalone_runner_keeps_merge_contract(runner, monkeypatch) -> None:
    monkeypatch.delenv("BM_LIFECYCLE_SUMMARY", raising=False)
    result = _graph_result()
    assert runner._write_lifecycle_summary(result) is None
    assert runner._exit_code(result, None) == 1
    assert runner._exit_code(_graph_result(status="merged"), None) == 0


def test_supervised_runner_completion_is_acceptance_not_merge(runner, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "attempt" / "harness-summary.json"
    target.parent.mkdir()
    monkeypatch.setenv("BM_LIFECYCLE_SUMMARY", str(target))
    result = _graph_result()
    summary = runner._write_lifecycle_summary(result)
    assert runner._exit_code(result, summary) == 0
    written = json.loads(target.read_text("utf-8"))
    assert written["merged"] is False
    assert written["provenance_verdict"] == "ok"
    assert written["ok_children"] == ["goal"]
    assert written["review_report"] == {"approved": True}
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert not target.with_name(target.name + ".tmp").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"provenance_verdict": "drift"},
        {"provenance_verdict": None},
        {"review_report": None},
        {"review_report": {"approved": False}},
        {"validation_report": {"passed": False}},
        {"preflight_ok": False},
        {"status": "failed"},
    ],
)
def test_supervised_runner_fails_closed(runner, tmp_path: Path, monkeypatch, overrides) -> None:
    target = tmp_path / "harness-summary.json"
    monkeypatch.setenv("BM_LIFECYCLE_SUMMARY", str(target))
    result = _graph_result(**overrides)
    summary = runner._write_lifecycle_summary(result)
    assert runner._exit_code(result, summary) == 1
    if overrides.get("provenance_verdict", "ok") is None:
        assert summary["provenance_verdict"] == "unverifiable"


def test_supervised_runner_interrupt_exits_awaiting_approval(runner, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "harness-summary.json"
    monkeypatch.setenv("BM_LIFECYCLE_SUMMARY", str(target))

    class Interrupt:
        value = {"gate": "plan", "question": "approve plan?"}

    result = _graph_result(status="running", phase="plan", __interrupt__=[Interrupt()])
    summary = runner._write_lifecycle_summary(result)
    assert runner._exit_code(result, summary) == 4
    assert summary["interrupt"] == [{"gate": "plan", "question": "approve plan?"}]


def test_supervised_runner_requires_parent_owned_summary_dir(runner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BM_LIFECYCLE_SUMMARY", str(tmp_path / "missing" / "summary.json"))
    with pytest.raises(SystemExit):
        runner._write_lifecycle_summary(_graph_result())


def test_langgraph_resume_value_from_decision(lifecycle) -> None:
    approved = {"approved": True, "answers": {"scope": "narrow"}}
    assert lifecycle._langgraph_resume_value(approved) == "approved"
    assert lifecycle._langgraph_resume_value({"approved": False}) == {"approved": False}
