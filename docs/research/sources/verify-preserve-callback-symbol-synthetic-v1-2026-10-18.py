"""Verify retained synthetic63 outcomes without decoder replay and preserve the exact small evidence."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import shlex
import stat

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
SOURCE = REPO / 'docs/research/sources'
EVIDENCE = Path('/tmp/callback-symbol-synthetic-evidence-20261018-v1')
LABELS = ('stage', 'run', 'observe')


# Preserve exact local file identities and timestamps as decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate two complete local reads and their held and named physical identities.
def read(path):
    assert path.is_absolute()
    path = path.resolve(strict=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        first = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert first == os.read(descriptor, 262145) and len(first) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return first, {'bytes': len(first), 'sha256': hashlib.sha256(first).hexdigest(), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Verify every named outcome, source byte, child exit and complete retained-file observation before exclusive copying.
def main():
    assert __debug__
    signal.alarm(30)
    inputs, raw_transports = {}, {}
    for label in LABELS:
        root = Path('/tmp/callback-symbol-synthetic-' + label + '-transport-20261018-v1')
        for name in ('stdout', 'stderr', 'exit.json'):
            path = root / name
            raw, row = read(path)
            inputs[str(path)] = (raw, row)
            if name == 'stdout':
                raw_transports[label] = raw
        terminal = json.loads(inputs[str(root / 'exit.json')][0])
        assert terminal['exit'] == 0 and all(terminal[k] is None for k in
            ('owned_SSH_group_stop', 'failure_class', 'cleanup_failure_class'))
        assert inputs[str(root / 'stderr')][0] == b''
        assert terminal['remote_quiescence_inferred_from_SSH_exit'] is False
        assert terminal['command'][:-1] == ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o',
            'UserKnownHostsFile=/tmp/checkpoint-image-hostkeys-20261017-v1', 'animallya96@172.16.8.3']
    stage = json.loads(raw_transports['stage'])
    stage_sha = hashlib.sha256(raw_transports['stage']).hexdigest()
    assert stage_sha == '5d91223b0ee59aabcc82b2232ce672123c28ffca21d792d765b0c8cf71691bc7'
    assert stage['uid'] == 1000 and stage['hostname'] == 'animallya-spark1' and stage['run_root_absent'] is True
    run_lines = raw_transports['run'].splitlines()
    assert len(run_lines) == 2
    owner_return, run_return = [json.loads(raw) for raw in run_lines]
    observation = json.loads(raw_transports['observe'])
    assert observation['scope'] == 'RETAINED_DATA_ONLY_NO_FIXTURE_OR_DECODER_REPLAY'
    files, decoded = observation['files'], {}
    for key, row in files.items():
        body = base64.b64decode(row['base64'], validate=True)
        assert len(body) == row['bytes'] <= 262144 and hashlib.sha256(body).hexdigest() == row['sha256']
        assert all(type(value) is str and str(int(value)) == value for value in row['physical'].values())
        assert row['physical']['st_uid'] == '1000' and row['physical']['st_nlink'] == '1'
        assert int(row['physical']['st_size']) == len(body)
        decoded[key] = body
    assert sum(map(len, decoded.values())) == observation['full_input_bytes'] <= 131072
    assert decoded['tools/stage.json'] == raw_transports['stage']
    bootstrap_path = SOURCE / 'callback-symbol-synthetic-bootstrap-v1-2026-10-18.py'
    bootstrap_raw, bootstrap_row = read(bootstrap_path)
    inputs[str(bootstrap_path)] = (bootstrap_raw, bootstrap_row)
    observer_path = SOURCE / 'observe-callback-symbol-synthetic-v1-2026-10-18.py'
    observer_raw, observer_row = read(observer_path)
    inputs[str(observer_path)] = (observer_raw, observer_row)
    bootstrap = ast.parse(bootstrap_raw)
    pins = ast.literal_eval(next(n.value for n in bootstrap.body if isinstance(n, ast.Assign) and
        any(isinstance(t, ast.Name) and t.id == 'PINS' for t in n.targets)))
    expected = {'tools/' + name for name in (*pins, 'stage.json', 'invocation.json')}
    expected.update({'run/' + name for name in (*pins, 'invocation.json', 'stdout.json', 'stderr.bin', 'exit.json')})
    assert set(files) == expected and len(files) == 14
    assert set(run_return['retained']) == {key for key in expected if key.startswith('run/') or key in
        ('tools/stage.json', 'tools/invocation.json')}
    for key, row in run_return['retained'].items():
        assert files[key] == row
    for label in LABELS:
        terminal_path = Path('/tmp/callback-symbol-synthetic-' + label + '-transport-20261018-v1/exit.json')
        terminal = json.loads(inputs[str(terminal_path)][0])
        command = shlex.split(terminal['command'][-1])
        expected_source = bootstrap_raw if label != 'observe' else observer_raw
        assert command[:5] == ['python3', '-I', '-S', '-B', '-c'] and command[5] == expected_source.decode()
        assert command[6:] == [label, stage_sha if label == 'run' else 'NONE']
    assert {label: sorted(key.split('/', 1)[1] for key in files if key.startswith(label + '/'))
        for label in ('tools', 'run')} == observation['inventories']
    for name, (digest, size) in pins.items():
        path = SOURCE / name
        body, row = read(path)
        inputs[str(path)] = (body, row)
        assert len(body) == size and hashlib.sha256(body).hexdigest() == digest
        assert decoded['tools/' + name] == decoded['run/' + name] == body
        assert stage['inventory'][name] == {k: v for k, v in files['tools/' + name].items() if k != 'base64'}
    owner = json.loads(decoded['run/exit.json'])
    assert owner == owner_return['receipt'] and owner['exit_code'] == 0 and owner['owned_child_reaped'] is True
    assert owner['timeout'] is False and all(owner[k] is None for k in
        ('exception', 'cleanup_failure', 'owned_child_stop', 'source_bookend_failure'))
    assert owner['stage_source_inventory'] == stage['inventory'] and decoded['run/stderr.bin'] == b''
    assert owner['command'] == ['/usr/bin/python3', '-I', '-S', '-B',
        '/home/animallya96/scratch/callback-symbol-synthetic-run-20261018-v1/run-callback-symbol-checks-v1-2026-10-18.py', '--child']
    invocation = json.loads(decoded['tools/invocation.json'])
    assert invocation['stage_sha256'] == stage_sha and invocation['source_inventory'] == stage['inventory']
    assert invocation['scope'] == 'ONE_NEW_SYNTHETIC63_ONLY'
    result = json.loads(decoded['run/stdout.json'])
    assert result['all_pass'] is True and result['actual_callback_or_native_runtime_acceptance'] is False
    for name in pins:
        row = {k: v for k, v in files['run/' + name].items() if k != 'base64'}
        assert row == (result['owner_source'] if name.startswith('run-') else result['source_inventory'][name])
    harness = ast.parse(decoded['run/check-callback-symbol-data-v1-2026-10-18.py'])
    declarations = {n.targets[0].id: ast.literal_eval(n.value) for n in harness.body if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('CASES', 'PAGE_UNITS')}
    expected_outcomes = []
    for name, reason, options in declarations['CASES']:
        expected_outcomes.append({'name': name, 'status': 'positive', 'scope': 'SYNTHETIC_KNOWN_VALUES_FULL_CANONICAL_AND_PAGE_PARITY'}
            if reason == 'positive' else {'name': name, 'status': 'expected_refusal', 'reason': reason, 'scope': 'SYNTHETIC_DATA_PARSER'})
    for name, reason in declarations['PAGE_UNITS']:
        expected_outcomes.append({'name': name, 'status': 'expected_refusal', 'reason': reason, 'scope': 'INJECTED_JSON_PAGING_UNIT_NOT_BINARY_DECODING'})
    assert result['outcomes'] == expected_outcomes and len(expected_outcomes) == 63
    assert len({r['name'] for r in expected_outcomes}) == 63
    assert sum(r['status'] == 'positive' for r in expected_outcomes) == 9
    controls = ('callback-symbol-synthetic-bootstrap-v1-2026-10-18.py',
        'prepare-callback-symbol-transport-v1-2026-10-18.py', 'callback-symbol-synthetic-transport-v1-2026-10-18.py',
        'observe-callback-symbol-synthetic-v1-2026-10-18.py', 'prepare-callback-symbol-observer-transport-v1-2026-10-18.py',
        'callback-symbol-synthetic-observer-transport-v1-2026-10-18.py', Path(__file__).name)
    for name in controls:
        path = SOURCE / name
        value = read(path)
        if str(path) in inputs:
            assert inputs[str(path)] == value
        else:
            inputs[str(path)] = value
    assert sum(len(raw) for raw, row in inputs.values()) <= 1048576
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)
    manifest = []
    for index, (name, (body, original)) in enumerate(sorted(inputs.items())):
        target = EVIDENCE / (str(index).zfill(3) + '-' + Path(name).name)
        with target.open('xb') as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        copy_body, copy = read(target)
        assert copy_body == body and read(Path(name))[1] == original
        manifest.append({'original': name, 'copy': str(target), 'original_identity': original, 'copy_identity': copy})
    for row in manifest:
        assert read(Path(row['original']))[1] == row['original_identity']
        assert read(Path(row['copy']))[1] == row['copy_identity']
    proof = {'schema': 'callback-symbol-synthetic-verification/1', 'status': 'VERIFIED_SYNTHETIC63_ONLY',
        'outcomes': expected_outcomes, 'child_pid': owner['pid'], 'child_exit': 0,
        'result_sha256': files['run/stdout.json']['sha256'], 'result_bytes': files['run/stdout.json']['bytes'],
        'stage_sha256': stage_sha, 'remote_files': len(files), 'remote_full_bytes': observation['full_input_bytes'],
        'elapsed_seconds': result['elapsed_seconds'], 'reported_Linux_ru_maxrss_KiB': result['reported_Linux_ru_maxrss_KiB'],
        'fresh_run_resources': invocation['resources'], 'local_preservation': manifest,
        'actual_callback_native_model_RAM_acceptance': False, 'crash_durability_guarantee': False}
    body = json.dumps(proof, sort_keys=True, indent=2).encode() + b'\n'
    assert len(body) <= 262144
    with (EVIDENCE / 'proof.json').open('xb') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    assert read(EVIDENCE / 'proof.json')[0] == body
    for directory in (EVIDENCE, EVIDENCE.resolve().parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'proof_bytes': len(body), 'proof_sha256': hashlib.sha256(body).hexdigest(),
        'local_files': len(manifest), 'local_bytes': sum(row['original_identity']['bytes'] for row in manifest),
        'outcomes': 63, 'status': proof['status']}))


if __name__ == '__main__':
    main()
