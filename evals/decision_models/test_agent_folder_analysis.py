"""Integrity checks for archived decisions and adversarial receipt mutations."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import analyze_agent_folder as audit

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / 'results' / '2026-09-27-agent-folder'


class AgentFolderAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, _ = audit.load_cases(HERE / 'agent_folder_cases.json')
        cls.rows = {arm: audit.read_rows(ARCHIVE / (arm + '.jsonl.gz')) for arm in audit.ARMS}

    def test_every_archived_response_is_auditable(self):
        for arm in audit.ARMS:
            with self.subTest(arm=arm):
                report, _ = audit.arm_inputs(ARCHIVE, arm, self.cases)
                self.assertEqual(report['status'], 'complete')
                self.assertEqual(report['coverage']['observed'], 64)
                self.assertFalse(report['coverage']['missing'])

    def test_fabricated_normalized_fields_are_rejected(self):
        changes = {
            'choice': 'wait', 'correct': False, 'valid': False,
            'model_match': False, 'actual_model': 'invented-model',
            'prompt_tokens': 99999, 'completion_tokens': 99999,
            'confidence': .25, 'correct_integer': 1,
            'probabilities': {'research': .5, 'write': .5, 'verify': 0., 'wait': 0.},
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                row = copy.deepcopy(self.rows['jev'][0])
                row['correct' if field == 'correct_integer' else field] = value
                with self.assertRaises(ValueError):
                    audit.validate_row('jev', row, self.cases, set())

    def test_payload_changes_and_gold_leaks_are_rejected(self):
        for field, value in [('state', 'different state'), ('gold', 'research'), ('model', 'latest')]:
            with self.subTest(field=field):
                row = copy.deepcopy(self.rows['jev'][0])
                row['payload'][field] = value
                with self.assertRaises(ValueError):
                    audit.validate_row('jev', row, self.cases, set())

    def test_raw_choice_and_cost_tampering_are_rejected(self):
        row = copy.deepcopy(self.rows['jev'][0])
        row['raw']['answers']['decision']['choice'] = 'wait'
        with self.assertRaises(ValueError):
            audit.validate_row('jev', row, self.cases, set())
        row = copy.deepcopy(self.rows['openrouter'][0])
        row['cost_usd'] = 42
        with self.assertRaises(ValueError):
            audit.validate_row('openrouter', row, self.cases, set())

    def test_model_pin_cannot_be_changed_consistently(self):
        row = copy.deepcopy(self.rows['jev'][0])
        row['model'] = row['actual_model'] = row['raw']['model'] = row['payload']['model'] = 'jev-other'
        with self.assertRaises(ValueError):
            audit.validate_row('jev', row, self.cases, set())

    def test_duplicate_record_is_rejected(self):
        row = self.rows['jev'][0]
        seen = set()
        audit.validate_row('jev', row, self.cases, seen)
        with self.assertRaises(ValueError):
            audit.validate_row('jev', row, self.cases, seen)

    def test_metadata_cannot_claim_a_different_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'jev.jsonl.gz').write_bytes((ARCHIVE / 'jev.jsonl.gz').read_bytes())
            metadata = json.loads((ARCHIVE / 'jev.meta.json').read_text())
            metadata['cases_sha256'] = '0' * 64
            (path / 'jev.meta.json').write_text(json.dumps(metadata))
            with self.assertRaises(ValueError):
                audit.arm_inputs(path, 'jev', self.cases)

    def test_malformed_raw_cannot_masquerade_as_transport_failure(self):
        row = copy.deepcopy(next(r for r in self.rows['openrouter'] if r['raw'] is None))
        row['raw'] = 'unverified response text'
        with self.assertRaises(ValueError):
            audit.validate_row('openrouter', row, self.cases, set())

    def test_transport_failure_stays_in_denominator_with_unknown_cost(self):
        failures = [r for r in self.rows['openrouter'] if r['raw'] is None]
        self.assertEqual(len(failures), 3)
        for row in failures:
            audit.validate_row('openrouter', row, self.cases, set())
        report, _ = audit.arm_inputs(ARCHIVE, 'openrouter', self.cases)
        self.assertEqual(report['accuracy']['overall']['total'], 64)
        self.assertEqual(report['accuracy']['overall']['valid_model_rows'], 61)
        self.assertFalse(report['cost']['provider_cost_complete'])
        self.assertIsNone(report['cost']['provider_reported_usd'])
        self.assertGreater(report['cost']['provider_reported_known_subtotal_usd'], 0)
        fabricated = copy.deepcopy(failures[0])
        fabricated['prompt_tokens'] = 0
        with self.assertRaises(ValueError):
            audit.validate_row('openrouter', fabricated, self.cases, set())

    def test_partial_and_missing_arms_never_rank_as_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            missing, _ = audit.arm_inputs(path, 'jev', self.cases)
            self.assertEqual(missing['status'], 'unavailable')
            self.assertIsNone(missing['accuracy']['overall'])
            (path / 'jev.jsonl').write_text(json.dumps(self.rows['jev'][0]) + '\n')
            partial, _ = audit.arm_inputs(path, 'jev', self.cases)
            self.assertEqual(partial['status'], 'incomplete')
            self.assertFalse(partial['rankable'])
            self.assertEqual(len(partial['coverage']['missing']), 63)

    def test_dangerous_directions_are_counted_separately(self):
        pairs = [('next_worker', 'wait', 'write'), ('relevance', 'keep', 'drop'),
                 ('done', 'unknown', 'met'), ('risky', 'side_effect', 'read_only')]
        rows = [{'category': c, 'gold': gold, 'choice': choice, 'id': str(i), 'repeat': 1}
                for i, (c, gold, choice) in enumerate(pairs)]
        report = audit.dangerous_errors(rows)
        self.assertEqual(report['total'], 4)
        self.assertEqual(len(report['by_kind']), 4)


if __name__ == '__main__':
    unittest.main()
