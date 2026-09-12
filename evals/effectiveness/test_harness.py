"""Focused tests for the effectiveness harness.

These tests use tiny synthetic fixtures and never invoke a model provider.  The
candidate-isolation tests require the same bubblewrap capability as a scored
run and skip when the host cannot provide it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402


def _fixtures(root: Path) -> Path:
    fixtures = root / "fixtures"
    for task_id in harness.TASK_IDS:
        task = fixtures / task_id
        task.mkdir(parents=True)
        (task / "public.md").write_text(f"Return the input for {task_id}.\n", encoding="utf-8")
        (task / "public_examples.json").write_text("[{\"input\": 1, \"expected\": 1}]\n", encoding="utf-8")
        (task / "private_cases.json").write_text(
            '[{"id":"private-1","input":1,"expected":1},{"id":"private-2","input":true,"expected":true}]\n',
            encoding="utf-8",
        )
        (task / "reference.py").write_text("def solve(payload):\n    return payload\n", encoding="utf-8")
        (task / "mutants.json").write_text('[{"name":"constant","source":"return 0"}]\n', encoding="utf-8")
    return fixtures


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixtures = _fixtures(self.root)
        self.protocol = self.root / "PROTOCOL.md"
        self.protocol.write_text("protocol test\n", encoding="utf-8")
        self.runs = self.root / "runs"
        self.run_dir = harness.prepare_run(
            "test-run",
            fixtures_dir=self.fixtures,
            protocol_path=self.protocol,
            runs_dir=self.runs,
            plans_dir=self.root / "plans",
            prompt_templates_dir=self.root / "prompts",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schedule_and_matrix_are_frozen_at_expected_sizes(self) -> None:
        manifest = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["schedule"]), 96)
        self.assertEqual(len(manifest["final_matrix"]), 72)
        self.assertEqual([entry["call_index"] for entry in manifest["schedule"]], list(range(1, 97)))
        self.assertEqual(len({(e["task_id"], e["repetition"]) for e in manifest["schedule"]}), 24)
        inventory = {item["path"] for item in manifest["file_inventory"]}
        self.assertIn("driver.py", inventory)
        self.assertIn("test_driver.py", inventory)

    def test_freeze_rejects_fixture_mutation_and_overwrite(self) -> None:
        (self.fixtures / "task01" / "public.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaises(harness.HarnessError):
            harness.verify_frozen_inputs(self.run_dir)
        with self.assertRaises(harness.HarnessError):
            harness.prepare_run("test-run", fixtures_dir=self.fixtures, protocol_path=self.protocol, runs_dir=self.runs)

    def test_solution_parser_rejects_missing_malformed_and_ambiguous_output(self) -> None:
        self.assertEqual(harness.parse_solution("")[1], "missing_output")
        self.assertEqual(harness.parse_solution("Here is the code:\ndef solve(payload):\n return payload")[1], "syntax_error")
        self.assertEqual(harness.parse_solution("```python\ndef solve(payload):\n return payload\n```\n```\npass\n```")[1], "ambiguous_code_fence_or_extra_prose")
        source, error = harness.parse_solution("def solve(payload):\n    return payload\n")
        self.assertIsNotNone(source)
        self.assertIsNone(error)

    def test_json_equality_preserves_bool_int_distinction(self) -> None:
        self.assertFalse(harness.json_equal(True, 1))
        self.assertTrue(harness.json_equal(1, 1.0))
        self.assertTrue(harness.json_equal({"a": [1, 2]}, {"a": [1.0, 2.0]}))
        self.assertFalse(harness.json_equal([1, 2], [2, 1]))

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap unavailable")
    def test_known_candidate_and_exception(self) -> None:
        candidate = self.root / "candidate.py"
        candidate.write_text("def solve(payload):\n    return payload\n", encoding="utf-8")
        score_path = harness.score_candidate(self.run_dir, "task01", 1, "single", candidate_path=candidate)
        score = json.loads(score_path.read_text(encoding="utf-8"))
        self.assertTrue(score["artifact_solved"])
        self.assertFalse(score["solved"])
        self.assertFalse(score["valid_evidence"])
        self.assertEqual(score["passed_cases"], 2)

        failing = self.root / "failing.py"
        failing.write_text("def solve(payload):\n    raise RuntimeError('known failure')\n", encoding="utf-8")
        failure_path = harness.score_candidate(self.run_dir, "task02", 1, "single", candidate_path=failing)
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        self.assertFalse(failure["solved"])
        self.assertTrue(all(case["status"] == "candidate_exception" for case in failure["case_results"]))

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap unavailable")
    def test_isolated_timeout_is_reported_without_retry(self) -> None:
        candidate = self.root / "timeout.py"
        candidate.write_text("def solve(payload):\n    while True:\n        pass\n", encoding="utf-8")
        result = harness._run_isolated(candidate, 1, wall_timeout=0.5)
        self.assertEqual(result["status"], "candidate_timeout")

    def test_malformed_candidate_is_reported_for_every_case(self) -> None:
        candidate = self.root / "malformed.py"
        candidate.write_text("def solve(:\n", encoding="utf-8")
        score_path = harness.score_candidate(self.run_dir, "task03", 1, "single", candidate_path=candidate)
        score = json.loads(score_path.read_text(encoding="utf-8"))
        self.assertEqual(score["candidate_error"], "syntax_error")
        self.assertEqual(len(score["case_results"]), 2)
        self.assertTrue(all(not case["passed"] for case in score["case_results"]))

    def test_invoke_retains_output_and_refuses_duplicate_handle(self) -> None:
        fake = self.root / "fake-codex"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if '--version' in sys.argv:\n"
            "    print('codex-test')\n"
            "else:\n"
            "    print(json.dumps({'type':'thread.started','thread_id':'missing-test-thread'}))\n"
            "    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'def solve(payload):\\n    return payload'}}))\n"
            "    print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'cached_input_tokens':1,'output_tokens':4,'reasoning_tokens':2}}))\n",
            encoding="utf-8",
        )
        os.chmod(fake, 0o755)
        prompt = self.root / "prompt.txt"
        prompt.write_text("public task prompt\n", encoding="utf-8")
        record_path = harness.invoke_call(self.run_dir, "task06", 1, "single", prompt, codex=str(fake), timeout=10)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["usage"]["cached_input_tokens"], 1)
        self.assertTrue((record_path.parent / "raw.jsonl").is_file())
        self.assertTrue((record_path.parent / "candidate.py").is_file())
        with self.assertRaises(harness.HarnessError):
            harness.invoke_call(self.run_dir, "task06", 1, "single", prompt, codex=str(fake), timeout=10)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap unavailable")
    def test_tainted_initial_output_cannot_be_validated_by_revision(self) -> None:
        invocation = self.run_dir / "invocations/task05_rep1_single"
        invocation.mkdir(parents=True)
        (invocation / "record.json").write_text(
            json.dumps({
                "task_id": "task05",
                "repetition": 1,
                "stage": "single",
                "status": "completed",
                "exit_code": 0,
                "tool_used": True,
                "runtime": {"verified": True},
            }),
            encoding="utf-8",
        )
        candidate = self.root / "revision.py"
        candidate.write_text("def solve(payload):\n    return payload\n", encoding="utf-8")
        score_path = harness.score_candidate(self.run_dir, "task05", 1, "self_revision", candidate_path=candidate)
        score = json.loads(score_path.read_text(encoding="utf-8"))
        self.assertTrue(score["artifact_solved"])
        self.assertFalse(score["solved"])
        self.assertEqual(score["dependency_taint"], "tool_use_forbidden")

    def test_dependency_taint_uses_invocation_evidence_and_repairs_syntax_errors(self) -> None:
        invocation = self.run_dir / "invocations/task06_rep1_single"
        invocation.mkdir(parents=True)
        record_path = invocation / "record.json"
        record_path.write_text(
            json.dumps({
                "task_id": "task06",
                "repetition": 1,
                "stage": "single",
                "status": "completed",
                "exit_code": 0,
                "parse_error": "syntax_error",
                "runtime": {"verified": True},
            }),
            encoding="utf-8",
        )
        self.assertIsNone(harness._dependency_taint(self.run_dir, "task06", 1, "self_revision"))
        record_path.write_text(
            json.dumps({
                "task_id": "task06",
                "repetition": 1,
                "stage": "single",
                "status": "completed",
                "exit_code": 0,
                "runtime": {"verified": False},
            }),
            encoding="utf-8",
        )
        self.assertEqual(
            harness._dependency_taint(self.run_dir, "task06", 1, "self_revision"),
            "model_provenance_unverified",
        )
        record_path.unlink()
        self.assertEqual(
            harness._dependency_taint(self.run_dir, "task06", 1, "self_revision"),
            "missing_predecessor_invocation",
        )

    def test_isolation_failure_fails_closed(self) -> None:
        candidate = self.root / "candidate.py"
        candidate.write_text("def solve(payload):\n    return payload\n", encoding="utf-8")
        with mock.patch.object(harness.shutil, "which", return_value=None):
            with self.assertRaises(harness.IsolationUnavailable):
                harness.score_candidate(self.run_dir, "task04", 1, "single", candidate_path=candidate)
        records = list((self.run_dir / "scores").glob("task04_rep1_single.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text(encoding="utf-8"))["status"], "infrastructure_error")

    def test_prepare_runs_available_fixture_validator_and_retains_receipt(self) -> None:
        validator = self.fixtures / "validate.py"
        validator.write_text(
            "import json\n"
            "print(json.dumps({'ok': True, 'expected_tasks': 12, 'discovered_tasks': 12, 'tasks': []}))\n",
            encoding="utf-8",
        )
        run = harness.prepare_run(
            "validator-run",
            fixtures_dir=self.fixtures,
            protocol_path=self.protocol,
            runs_dir=self.runs,
            plans_dir=self.root / "plans",
            prompt_templates_dir=self.root / "prompts",
        )
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        receipt = manifest["fixture_validation"]["receipt"]
        self.assertTrue(receipt["ok"])
        self.assertEqual(
            manifest["fixture_validation"]["receipt_sha256"],
            harness.sha256_text(harness.json_dump(receipt)),
        )

    def test_cli_schedule_guard_and_score_seal(self) -> None:
        manifest = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        second = manifest["schedule"][1]
        with self.assertRaises(harness.HarnessError):
            harness._require_schedule_predecessors_terminal(self.run_dir, manifest, second["task_id"], second["repetition"], second["stage"])

        def write_record(entry: dict[str, object]) -> None:
            path = self.run_dir / "invocations" / f"{entry['task_id']}_rep{entry['repetition']}_{entry['stage']}" / "record.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({**entry, "status": "completed", "exit_code": 0}), encoding="utf-8")

        write_record(manifest["schedule"][0])
        harness._require_schedule_predecessors_terminal(self.run_dir, manifest, second["task_id"], second["repetition"], second["stage"])
        with self.assertRaises(harness.HarnessError):
            harness._seal_score_inputs(self.run_dir, manifest)
        for entry in manifest["schedule"][1:]:
            write_record(entry)
        for task_id in harness.TASK_IDS:
            for repetition in harness.REPETITIONS:
                review = self.run_dir / "reviews" / f"{task_id}_rep{repetition}.md"
                review.parent.mkdir(parents=True, exist_ok=True)
                review.write_text("review\n", encoding="utf-8")
        seal = harness._seal_score_inputs(self.run_dir, manifest)
        self.assertTrue(seal.is_file())
        (self.run_dir / "reviews/task01_rep1.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaises(harness.HarnessError):
            harness._seal_score_inputs(self.run_dir, manifest)

    def test_runtime_attestation_uses_exact_child_rollout_only(self) -> None:
        home = self.root / "home"
        thread_id = "child-thread-123"
        session_dir = home / ".codex" / "sessions" / "2026" / "09" / "11"
        session_dir.mkdir(parents=True)
        (session_dir / f"rollout-date-{thread_id}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": thread_id}}) + "\n"
            + json.dumps({"type": "turn_context", "payload": {"model": "wrong-model", "effort": "max"}}) + "\n",
            encoding="utf-8",
        )
        (session_dir / "rollout-unrelated.jsonl").write_text(
            f"unrelated transcript mentions {thread_id} with gpt-5.6-luna max\n",
            encoding="utf-8",
        )
        with mock.patch.object(harness.Path, "home", return_value=home):
            evidence = harness._runtime_model_evidence(thread_id, "2026-09-11T12:00:00Z")
        self.assertFalse(evidence["verified"])
        self.assertEqual(evidence["reason"], "turn_context_mismatch")

    def test_analyze_uses_fixed_missing_denominators_and_task_weighting(self) -> None:
        scores = self.run_dir / "scores"
        scores.mkdir(exist_ok=True)
        # Baseline solves both repetitions of task01 only.  Self revision solves
        # one repetition of task01; missing cells remain zero in the fixed rate.
        for task_id in harness.TASK_IDS:
            for repetition in harness.REPETITIONS:
                for stage, arm in (("single", "single"), ("self_revision", "self_revision")):
                    solved = task_id == "task01" and (stage == "single" or repetition == 1)
                    value = {
                        "task_id": task_id,
                        "repetition": repetition,
                        "stage": stage,
                        "arm": arm,
                        "status": "scored",
                        "solved": solved,
                        "artifact_solved": solved,
                        "fraction_passed": 1.0 if solved else 0.0,
                        "case_count": 1,
                        "passed_cases": 1 if solved else 0,
                        "case_results": [],
                    }
                    (scores / f"{task_id}_rep{repetition}_{stage}.json").write_text(json.dumps(value), encoding="utf-8")
        analysis_path = harness.analyze_run(self.run_dir)
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        self.assertEqual(analysis["arms"]["single"]["fixed_cell_denominator"], 24)
        self.assertEqual(analysis["arms"]["beastmode"]["missing_cells"], 24)
        # Task averages are computed before averaging the twelve tasks.
        self.assertAlmostEqual(analysis["arms"]["self_revision"]["task_average_mean"], 0.5 / 12)
        self.assertEqual(len(analysis["paired_contrasts"]["self_revision_minus_single"]["task_differences"]), 12)
        self.assertIn("six_family_bootstrap", analysis["paired_contrasts"]["self_revision_minus_single"])
        self.assertIn("beastmode_minus_self_revision", analysis["paired_contrasts"])
        self.assertEqual(len(analysis["paired_contrasts"]["beastmode_minus_self_revision"]["task_differences"]), 12)


if __name__ == "__main__":
    unittest.main()
