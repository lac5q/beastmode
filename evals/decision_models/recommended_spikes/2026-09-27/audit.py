"""Offline, independent receipt audit. No imports from candidate implementations."""
import gzip
import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path):
    path = Path(path)
    return gzip.decompress(path.read_bytes()).decode() if path.suffix == '.gz' else path.read_text()


def data(path):
    return json.loads(read(path))


def rows(path):
    return [json.loads(line) for line in read(path).splitlines()]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def result_text(messages):
    return '\n'.join(item['text'] for msg in messages for item in msg.get('toolResults', []))


def main():
    manifest = data(ROOT / 'SHA256.json')
    for name, expected in manifest.items():
        assert digest(ROOT / name) == expected, name
    cases_path = ROOT.parents[1] / 'agent_folder_cases.json'
    cases = {case['id']: case for case in data(cases_path)}
    freeze = data(ROOT / 'kev/freeze.json')
    assert digest(cases_path) == freeze['cases_sha256']
    assert digest(ROOT / 'kev/kev_probe.py') == freeze['runner_sha256']
    kev = rows(ROOT / 'kev/results.jsonl')
    for row in kev:
        case = cases[row['id']]
        payload = row['payload']['data']
        assert payload[0] == case['state']
        assert json.loads(payload[1]) == {'decision': {'type': 'choice',
            'instructions': case['question'], 'criteria': dict.fromkeys(case['options'])}}
        assert payload[2:] == ['Kev-4B', True, False, False, 4]
        if row['valid']:
            raw = next(e['data'][1] for e in row['raw_events'] if e['event'] == 'complete')
            assert raw == row['raw']
            assert raw['model'] == 'jaredpalmer/kev-4b'
            assert row['correct'] == (raw['answers']['decision']['choice'] == case['gold'])
    assert len(kev) == 3 and sum(r['valid'] for r in kev) == 2
    assert 'ZeroGPU runs limit' in str(kev[-1]['raw_events'])

    comp = rows(ROOT / 'compaction/compaction-live-cases.jsonl.gz')
    receipts = rows(ROOT / 'compaction/compaction-live-receipts.jsonl.gz')
    assert len(comp) == len(receipts) == 9
    for row in receipts:
        assert row['status'] == 200
        assert hashlib.sha256(row['responseText'].encode()).hexdigest() == row['responseBodyHash']
        assert json.loads(row['responseText'])['model'] == 'jev-1.13.0'
        assert row['requestBody']['model'] == 'jev-1.13.0'
    requirements = {'required-old-failure-receipt': 'FAILURE_RECEIPT::expected 2 to be 3',
                    'contradictory-old-evidence': 'CONTRADICTION::',
                    'approval-scope-constraint': 'APPROVAL_SCOPE::',
                    'long-middle-evidence': 'CRITICAL-MIDDLE-EVIDENCE'}
    retention = {}
    for row in comp:
        if row['fixture'] in requirements:
            marker = requirements[row['fixture']]
            assert marker in result_text(row['inputMessages'])
            retention[row['fixture']] = marker in result_text(row['outputMessages'])
    assert {name for name, retained in retention.items() if not retained} == {
        'approval-scope-constraint', 'long-middle-evidence'}
    assert receipts[4]['requestBody'] == receipts[8]['requestBody']
    assert receipts[4]['requestHash'] == receipts[8]['requestHash']
    assert result_text(comp[4]['inputMessages']) != result_text(comp[8]['inputMessages'])

    browser = ROOT / 'browser'
    freeze = data(browser / 'live-freeze.json')
    for name in ['run_local_trials.py', 'contract.json', 'validate_contract.py']:
        assert digest(browser / name) == freeze['hashes'][name]
    contract = data(browser / 'contract.json')
    trial_root = next((browser / 'trials').iterdir())
    summary = data(trial_root / 'run-summary.json.gz')
    logical = []
    for trial in summary['results']:
        path = trial_root / f"trial-{trial['trial']:02}"
        state = data(path / 'final-state.json.gz')
        assert len(state['history']) <= 20
        raw = rows(path / 'raw-model-receipts.jsonl.gz')
        logical.extend(raw)
        for row in raw:
            assert row['response']['model'] == row['request']['model']
            assert row['request']['model'] in {'jev-1.13.0', 'inception/mercury-2.5'}
        if trial['passed']:
            observed = data(path / 'verification.json.gz')['observed']
            assert observed == contract['acceptance']['expected_dom']
            assert len(state['history']) == 5
        else:
            assert trial['trial'] == 1 and len(state['history']) == 0
            content = raw[-1]['response']['choices'][0]['message']['content']
            try:
                json.loads(content)
            except json.JSONDecodeError:
                pass
            else:
                raise AssertionError('Expected invalid writer JSON')
    assert summary['passed_trials'] == 2 and len(summary['results']) == 3
    assert len(logical) == 16
    head = data(ROOT / 'local-backends/clm/root-smoke.json')
    assert head['status'] == 'pass' and head['advertised_model_inference'] is False
    assert head['torch_force_weights_only_load'] == '1'
    laya = data(ROOT / 'local-backends/laya-mlx/root-preflight.json')
    assert laya['package_import']['status'] == 'blocked'
    assert laya['pure_python_contracts']['status'] == 'pass'
    out = {'audit': 'passed', 'files_verified': len(manifest),
           'kev': {'measured_attempts': 3, 'valid': 2, 'full_corpus_accuracy': None},
           'compaction': {'required_evidence_retention': retention,
               'identical_critical_benign_requests': True,
               'request_count': len(receipts),
               'median_request_ms': statistics.median(r['wallMs'] for r in receipts),
               'input_tokens': sum(r['usage']['input_tokens'] for r in receipts)},
           'browser': {'trials': 3, 'successes': 2, 'logical_provider_calls': len(logical),
               'jev_calls': sum(r['request']['model'] == 'jev-1.13.0' for r in logical),
               'writer_cost_usd_reported': sum(r['response'].get('usage', {}).get('cost', 0) for r in logical),
               'jev_input_tokens': sum(r['response']['usage']['input_tokens'] for r in logical
                                      if r['request']['model'] == 'jev-1.13.0')},
           'clm_semantic_inference': False, 'laya_semantic_inference': False}
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
