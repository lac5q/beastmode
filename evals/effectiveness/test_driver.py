import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driver


class FakeHarness:
    def __init__(self, root, run, schedule):
        self.ROOT = root
        self.run = run
        self.schedule = schedule
        self.calls = []

    def resolve_run(self, value):
        return self.run

    def verify_frozen_inputs(self, run):
        return self.manifest

    def invoke_call(self, run, task_id, repetition, stage, prompt_path):
        self.calls.append((task_id, repetition, stage, prompt_path.read_text()))
        call = run / "invocations" / f"{task_id}_rep{repetition}_{stage}"
        call.mkdir(parents=True)
        (call / "final_output.txt").write_text("BEAST CODE" if stage == "beast_initial" else "FINAL")
        record = {
            "task_id": task_id,
            "repetition": repetition,
            "stage": stage,
            "schedule_entry": next(x for x in self.schedule if x["stage"] == stage),
            "status": "completed",
            "final_output_path": "final_output.txt",
            "candidate_path": None,
        }
        path = call / "record.json"
        path.write_text(json.dumps(record))
        return path


class DriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        run = root / "run"
        run.mkdir()
        (root / "fixtures/task01").mkdir(parents=True)
        (root / "plans").mkdir()
        (root / "prompts").mkdir()
        (root / "fixtures/task01/public.md").write_text("PUBLIC SPEC")
        (root / "fixtures/task01/public_examples.json").write_text("[{\"input\":1,\"expected\":2}]")
        (root / "plans/task01.md").write_text("PUBLIC PLAN")
        (root / "prompts/common.txt").write_text("COMMON")
        for stage, text in {
            "single": "SINGLE {{public_spec}} {{public_examples}}",
            "self_revision": "SELF {{public_spec}} {{public_examples}} {{initial_code}}",
            "beast_initial": "BEAST {{public_spec}} {{public_examples}} {{director_plan}}",
            "beast_revision": "REVISE {{public_spec}} {{public_examples}} {{director_plan}} {{initial_code}} {{director_review}}",
        }.items():
            (root / f"prompts/{stage}.txt").write_text(text)
        self.schedule = [
            {"call_index": i + 1, "task_id": "task01", "repetition": 1, "arm": "baseline" if i < 2 else "beastmode", "stage": stage}
            for i, stage in enumerate(("single", "self_revision", "beast_initial", "beast_revision"))
        ]
        self.fake = FakeHarness(root, run, self.schedule)
        self.fake.manifest = {
            "fixtures_root": "fixtures",
            "schedule": self.schedule,
            "fixed_prompt_template": {"path": "prompt_template.txt"},
            "file_inventory": [
                {"path": "fixtures/task01/public.md"},
                {"path": "fixtures/task01/public_examples.json"},
                {"path": "plans/task01.md"},
                *({"path": f"prompts/{stage}.txt"} for stage in ("single", "self_revision", "beast_initial", "beast_revision")),
            ],
            "director_plans": [{"path": "plans/task01.md"}],
            "prompt_templates": [{"path": f"prompts/{stage}.txt"} for stage in ("single", "self_revision", "beast_initial", "beast_revision")],
        }
        (run / "prompt_template.txt").write_text("COMMON")
        self.run = run
        self.old_harness = driver.harness
        driver.harness = self.fake

    def tearDown(self):
        driver.harness = self.old_harness
        self.tmp.cleanup()

    def test_serial_order_public_rendering_and_review_barrier(self):
        self.assertEqual(driver.advance(self.run), 0)
        self.assertEqual([x[2] for x in self.fake.calls], ["single", "self_revision", "beast_initial"])
        self.assertIn("PUBLIC SPEC", self.fake.calls[0][3])
        self.assertIn("COMMON", self.fake.calls[0][3])
        self.assertNotIn("PRIVATE", self.fake.calls[0][3])
        request = self.run / "reviews/task01_rep1.request.json"
        self.assertTrue(request.is_file())
        request_text = request.read_text()
        self.assertNotIn("BASELINE", request_text)
        self.assertNotIn("single", request_text)
        (self.run / "reviews/task01_rep1.md").write_text("REVIEW")
        self.assertEqual(driver.advance(self.run), 0)
        self.assertEqual([x[2] for x in self.fake.calls], ["single", "self_revision", "beast_initial", "beast_revision"])
        revision = self.fake.calls[-1][3]
        self.assertIn("BEAST CODE", revision)
        self.assertIn("REVIEW", revision)

    def test_terminal_skip_and_running_records_are_not_restarted(self):
        self.fake.schedule = self.schedule[:1]
        self.fake.manifest["schedule"] = self.schedule[:1]
        call = self.run / "invocations/task01_rep1_single"
        call.mkdir(parents=True)
        record = {"status": "completed", "task_id": "task01", "repetition": 1, "stage": "single"}
        (call / "record.json").write_text(json.dumps(record))
        self.assertEqual(driver.advance(self.run), 0)
        self.assertFalse(self.fake.calls)
        record["status"] = "running"
        record["pid"] = os.getpid()
        (call / "record.json").write_text(json.dumps(record))
        self.assertEqual(driver.advance(self.run), 0)
        self.assertFalse(self.fake.calls)
        record["pid"] = 2**31
        (call / "record.json").write_text(json.dumps(record))
        with self.assertRaises(driver.DriverError):
            driver.advance(self.run)
        self.assertFalse(self.fake.calls)

    def test_empty_initial_uses_protocol_sentinel(self):
        call = self.run / "invocations/task01_rep1_single"
        call.mkdir(parents=True)
        (call / "final_output.txt").write_text("")
        (call / "record.json").write_text(json.dumps({"status": "completed"}))
        self.assertEqual(driver.advance(self.run), 0)
        self.assertIn(driver.NO_INITIAL, self.fake.calls[0][3])


if __name__ == "__main__":
    unittest.main()
