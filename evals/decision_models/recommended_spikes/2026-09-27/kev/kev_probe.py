"""Bounded public Kev Space spike; queue latency is not self-hosted latency."""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.request

BASE = 'https://jaredpalmer-kev.hf.space/gradio_api/call/decide'
MODEL = 'jaredpalmer/kev-4b'


def run_one(case):
    questions = {'decision': {'type': 'choice', 'instructions': case['question'],
                              'criteria': {key: None for key in case['options']}}}
    payload = {'data': [case['state'], json.dumps(questions), 'Kev-4B', True, False, False, 4]}
    record = {'id': case['id'], 'category': case['category'], 'gold': case['gold'],
              'payload': payload, 'requested_model': MODEL, 'raw_events': [],
              'valid': False, 'correct': False, 'error': None,
              'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    started = time.monotonic()
    try:
        req = urllib.request.Request(BASE, data=json.dumps(payload).encode(),
              headers={'Content-Type': 'application/json', 'User-Agent': 'Beastmode-decision-spike/1.0'})
        with urllib.request.urlopen(req, timeout=120) as response:
            ack = json.load(response)
        record['ack'] = ack
        event_id = ack['event_id']
        if not isinstance(event_id, str) or not event_id.isalnum():
            raise ValueError('Malformed event identifier')
        with urllib.request.urlopen(BASE + '/' + event_id, timeout=120) as stream:
            event = None
            result = None
            for line in stream:
                if time.monotonic() - started > 120:
                    raise TimeoutError('120 second client budget')
                text = line.decode().strip()
                if text.startswith('event:'):
                    event = text[6:].strip()
                elif text.startswith('data:'):
                    data = json.loads(text[5:].strip())
                    record['raw_events'].append({'event': event, 'data': data})
                    if event == 'error':
                        raise RuntimeError('Space returned error event')
                    if event == 'complete':
                        result = data
                        break
        if not isinstance(result, list) or len(result) != 3:
            raise ValueError('No complete three-output response')
        raw = result[1]
        if isinstance(raw, str):
            raw = json.loads(raw)
        record['raw'] = raw
        if raw.get('model') != MODEL:
            raise ValueError('Observed model ID mismatch')
        answer = raw['answers']['decision']
        probabilities = answer['probabilities']
        if set(probabilities) != set(case['options']):
            raise ValueError('Option probability keys differ')
        if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p)
               or not 0 <= p <= 1 for p in probabilities.values()):
            raise ValueError('Invalid probabilities')
        if abs(sum(probabilities.values()) - 1) > .02:
            raise ValueError('Probabilities do not sum to one')
        if answer['choice'] not in case['options']:
            raise ValueError('Invalid label')
        record.update(choice=answer['choice'], probabilities=probabilities,
                      confidence=answer.get('confidence'), valid=True,
                      correct=answer['choice'] == case['gold'])
    except urllib.error.HTTPError as exc:
        record.update(error='http_error', http_status=exc.code,
                      error_body=exc.read(10000).decode(errors='replace'))
    except Exception as exc:
        record.update(error=type(exc).__name__, error_message=str(exc))
    record['client_latency_ms'] = (time.monotonic() - started) * 1000
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    freeze = {'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with (args.out / 'freeze.json').open('x') as out:
        json.dump(freeze, out, indent=2)
    cases = json.loads(args.cases.read_text())
    warmup = run_one(cases[0])
    (args.out / 'warmup.json').write_text(json.dumps(warmup, indent=2) + '\n')
    print('Warmup:', warmup['valid'], warmup['error'], flush=True)
    if not warmup['valid']:
        (args.out / 'status.json').write_text(json.dumps({'status': 'unavailable', 'measured': 0, 'reason': warmup['error']})+'\n')
        return 2
    count = 0
    with (args.out / 'results.jsonl').open('x') as out:
        for repeat in (1, 2):
            for case in cases:
                row = run_one(case)
                row['repeat'] = repeat
                out.write(json.dumps(row) + '\n'); out.flush(); count += 1
                print(repeat, case['id'], row['valid'], row['choice'] if row['valid'] else row['error'], flush=True)
                if not row['valid']:
                    (args.out / 'status.json').write_text(json.dumps({'status': 'incomplete', 'measured': count, 'reason': row['error']})+'\n')
                    return 2
    (args.out / 'status.json').write_text(json.dumps({'status': 'complete', 'measured': count})+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
