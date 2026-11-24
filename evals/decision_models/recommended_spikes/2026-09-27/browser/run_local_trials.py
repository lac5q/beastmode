"""Bounded opt-in Jev + writer trials against the copied local hotel fixture.

The goal and exact acceptance values come from contract.json and cannot be
overridden on the command line. The worker never invokes this without the
explicit live flag; the root agent may provide model credentials at runtime.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import signal
import sys
import time
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from jev_ultrafast import model
from jev_ultrafast.agent import Agent

from validate_contract import CONTRACT, verify_browser


class DecisionTimeout(TimeoutError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class QuietFixtureHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


class RawReceiptCapture:
    """Persist provider request/response pairs without ever recording the API key."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.original = model.post_json
        self.count = 0

    @staticmethod
    def endpoint(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname or ''}{parsed.path}"

    def __call__(self, url: str, key: str, body: dict) -> dict:
        self.count += 1
        started = time.perf_counter()
        receipt = {"receipt": self.count, "endpoint": self.endpoint(url), "request": body}
        try:
            # The key is passed through for the provider call but is never put
            # in the receipt or in any printed result.
            result = self.original(url, key, body)
        except Exception as error:
            receipt["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
            receipt["error"] = {"type": type(error).__name__, "message": str(error)}
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False, default=str) + "\n")
            raise
        receipt["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        receipt["response"] = result
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False, default=str) + "\n")
        return result


def _alarm(_signum, _frame) -> None:
    raise DecisionTimeout("decision exceeded the frozen 60-second budget")


def next_with_timeout(iterator, seconds: int):
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    started = time.perf_counter()
    try:
        return next(iterator), round((time.perf_counter() - started) * 1000)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def fixture_server() -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(QuietFixtureHandler, directory=str(SOURCE / "jev_ultrafast" / "static"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, name="local-fixture", daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/fixture.html?scenario=travel"


def save_state(trial_dir: Path, index: int, state: dict, decision_ms: int) -> None:
    receipt = {
        "tick": index,
        "decision_wall_ms": decision_ms,
        "status": state.get("status"),
        "actions": len(state.get("history", [])),
        "decision": state.get("decisions", [])[-1] if state.get("decisions") else None,
        "history": state.get("history", [])[-1] if state.get("history") else None,
        "page": state.get("page"),
    }
    write_json(trial_dir / "receipts" / f"tick-{index:02d}.json", receipt)
    write_json(trial_dir / "state-latest.json", state)


def run_trial(index: int, url: str, trial_dir: Path, max_actions: int, decision_timeout: int) -> dict:
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "receipts").mkdir(parents=True, exist_ok=True)
    capture = RawReceiptCapture(trial_dir / "raw-model-receipts.jsonl")
    model.post_json = capture
    agent: Agent | None = None
    started = time.perf_counter()
    result: dict = {"trial": index, "url": url, "passed": False, "live": True}
    try:
        agent = Agent(url, CONTRACT["goal"], screenshots=False)
        iterator = agent.run()
        tick = 0
        while True:
            try:
                state, decision_ms = next_with_timeout(iterator, decision_timeout)
            except StopIteration:
                break
            tick += 1
            actions = len(state.get("history", []))
            if actions > max_actions:
                raise BudgetExceeded(f"executed {actions} actions; limit is {max_actions}")
            save_state(trial_dir, tick, state, decision_ms)
            if state.get("status") in {"done", "blocked"}:
                break
            if actions >= max_actions:
                raise BudgetExceeded(f"reached {max_actions} actions without a terminal state")

        state = agent.snapshot()
        verification = verify_browser(agent.browser)
        result.update(
            {
                "status": state.get("status"),
                "actions": len(state.get("history", [])),
                "decisions": len(state.get("decisions", [])),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "verification": verification,
                "passed": bool(verification.get("passed")),
            }
        )
        write_json(trial_dir / "final-state.json", state)
        write_json(trial_dir / "verification.json", verification)
    except (RuntimeError, ValueError, TypeError, KeyError, OSError) as error:
        result.update(
            {
                "error": {"type": type(error).__name__, "message": str(error)},
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        if agent is not None:
            try:
                state = agent.snapshot()
                write_json(trial_dir / "final-state.json", state)
            except (RuntimeError, ValueError, TypeError, KeyError, OSError) as snapshot_error:
                result["snapshot_error"] = {
                    "type": type(snapshot_error).__name__,
                    "message": str(snapshot_error),
                }
    finally:
        model.post_json = capture.original
        if agent is not None:
            agent.close()
    write_json(trial_dir / "summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live-model-calls", action="store_true", help="required explicit opt-in")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--max-actions", type=int, default=20)
    parser.add_argument("--decision-timeout", type=int, default=60)
    args = parser.parse_args()
    budgets = CONTRACT["budgets"]
    if not args.allow_live_model_calls:
        raise SystemExit("refusing live calls: pass --allow-live-model-calls from the root agent")
    if not 1 <= args.trials <= budgets["max_trials"]:
        raise SystemExit(f"trials must be between 1 and {budgets['max_trials']}")
    if not 1 <= args.max_actions <= budgets["max_actions_per_trial"]:
        raise SystemExit(f"max-actions must be <= {budgets['max_actions_per_trial']}")
    if not 1 <= args.decision_timeout <= budgets["max_seconds_per_decision"]:
        raise SystemExit(f"decision-timeout must be <= {budgets['max_seconds_per_decision']}")
    if not os.environ.get("TYPESAFE_API_KEY") or not os.environ.get("TEXT_MODEL_API_KEY"):
        raise SystemExit("refusing live calls: both model credentials must be supplied by the caller")
    cdp_url = os.environ.get("BU_CDP_URL", "")
    parsed = urlparse(cdp_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("refusing browser connection: set BU_CDP_URL to the dedicated loopback Chrome only")
    if os.environ.get("BU_CDP_WS") or os.environ.get("BU_BROWSER_ID"):
        raise SystemExit("refusing browser connection: cloud or unmanaged CDP configuration is present")

    fixture = SOURCE / "jev_ultrafast" / "static" / "fixture.html"
    fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    if fixture_hash != CONTRACT["source"]["fixture_sha256"]:
        raise SystemExit("fixture hash does not match the frozen contract")

    run_dir = ROOT / "trials" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir.mkdir(parents=True, exist_ok=True)
    server, url = fixture_server()
    results: list[dict] = []
    try:
        for index in range(1, args.trials + 1):
            results.append(run_trial(index, url, run_dir / f"trial-{index:02d}", args.max_actions, args.decision_timeout))
    finally:
        server.shutdown()
        server.server_close()
    report = {
        "contract": str(ROOT / "contract.json"),
        "goal": CONTRACT["goal"],
        "fixture_url": url,
        "budgets": {
            "max_trials": args.trials,
            "max_actions_per_trial": args.max_actions,
            "max_seconds_per_decision": args.decision_timeout,
        },
        "results": results,
        "passed_trials": sum(bool(item.get("passed")) for item in results),
        "live": True,
        "provenance": CONTRACT["provenance"],
    }
    write_json(run_dir / "run-summary.json", report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
